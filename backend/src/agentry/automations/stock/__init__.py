"""Stock shelf scanner (ROADMAP-V3 B2, v2 11.3): a photo of a shelf -> counts -> what to reorder -> a message to the supplier.

    items    what the business tracks: name, unit, reorder level and quantity, supplier and their WhatsApp (a CSV / Excel
             or added by hand); items read from a photo that aren't tracked yet can be added from the scan
    scan     a photo (portal) is read by the vision model: each product with a count and a confidence; matched to tracked
             items by name; shown next to the last count. A person confirms (or corrects) the counts and applies the scan
    reorder  tracked items at or below their reorder level, grouped by supplier, with a ready WhatsApp message each
             (copy it, or send it when the supplier is a contact and WhatsApp is connected)
"""
import base64
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

SAMPLE = {"name": "shelf_sample.jpg", "items": [{"name": "Amul Taaza milk 500 ml", "count": 6, "unit": "packet", "confidence": 0.95},
                                                {"name": "Parle-G 250 g", "count": 14, "unit": "packet", "confidence": 0.9},
                                                {"name": "Tata Salt 1 kg", "count": 2, "unit": "packet", "confidence": 0.65}]}


class StockConfig(BaseModel):
    confirm_below: float = Field(0.8, ge=0.5, le=0.99, title="Ask a person to check counts read with less confidence than",
                                 json_schema_extra={"editable_by": "client"})
    business_signoff: str | None = Field(None, title="Sign-off on supplier messages", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="stock_scanner", name="Stock shelf scanner",
    description="A photo of a shelf becomes a stock count; what's running low is grouped by supplier with the reorder message ready.",
    config_model=StockConfig, metrics=(),
))


def _norm(s: str) -> str:
    s = re.sub(r"(\d)\s+(ml|ltr|l|gm|g|kg|pc|pcs)\b", r"\1\2", (s or "").lower())  # "1 kg" = "1kg"
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def match(name: str, items: list[dict]) -> dict | None:
    n = set(_norm(name).split())
    best, score = None, 0.0
    for it in items:
        m = set(_norm(it["name"]).split())
        if not m:
            continue
        s = len(n & m) / len(n | m)
        if s > score:
            best, score = it, s
    return best if score >= 0.5 else None


async def scan(org_id: str, data: bytes, mime: str, filename: str | None, area: str | None, user_id: str | None) -> dict:
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("send a photo (JPG, PNG or WEBP)")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("photos can be up to 10 MB")
    async with tenant_session(org_id) as conn:
        tracked = [dict(r) for r in (await conn.execute(text("select id::text, name, unit, count from app.stock_items order by name"))).mappings().all()]
    prompt = load("stock_scan")
    msgs = prompt.render(known="; ".join(t["name"] for t in tracked[:200]) or "(none yet)", area=area or "not given")
    msgs[-1] = {"role": "user", "content": [{"type": "text", "text": msgs[-1]["content"]},
                                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}]}
    mock = {"items": SAMPLE["items"]} if (filename or "") == SAMPLE["name"] else {"items": []}
    try:
        r = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                           mock_response=json.dumps(mock), temperature=0)
        raw = r.data.get("items") if isinstance(r.data, dict) else []
    except AllModelsFailed as e:
        raise ValueError("the reading service is busy: try again in a minute") from e
    lines = []
    for x in raw or []:
        if not isinstance(x, dict) or not x.get("name"):
            continue
        try:
            count = max(0, round(float(x.get("count") or 0)))
            conf = max(0.0, min(1.0, float(x.get("confidence") or 0)))
        except (TypeError, ValueError):
            continue
        hit = match(str(x["name"]), tracked)
        lines.append({"name": hit["name"] if hit else str(x["name"])[:120], "read_as": str(x["name"])[:120], "count": count, "unit": (hit or x).get("unit") or "pc",
                      "confidence": round(conf, 2), "item_id": hit["id"] if hit else None, "previous": float(hit["count"]) if hit and hit["count"] is not None else None})
    p = Path(settings.documents_dir) / org_id / "stock"
    p.mkdir(parents=True, exist_ok=True)
    f = p / f"{uuid.uuid4()}{Path(filename or 'photo.jpg').suffix.lower() or '.jpg'}"
    f.write_bytes(data)
    async with tenant_session(org_id) as conn:
        sid = str((await conn.execute(text("""insert into app.stock_scans (org_id, path, area, items, created_by) values (:o, :p, :a, cast(:i as jsonb), :u)
            returning id"""), {"o": org_id, "p": str(f.relative_to(Path(settings.documents_dir))), "a": area, "i": json.dumps(lines), "u": user_id})).scalar_one())
    return {"id": sid, "items": lines}


async def apply(conn: AsyncConnection, org_id: str, sid: str, counts: list[dict], add_new: bool) -> dict:
    """counts: [{name, count, item_id?}] as the person confirmed them. Untracked items are added when add_new."""
    s = (await conn.execute(text("select status from app.stock_scans where id = cast(:i as uuid) for update"), {"i": sid})).scalar_one_or_none()
    if s != "review":
        raise ValueError("this scan was already applied or discarded")
    now, updated, added = datetime.now(UTC), 0, 0
    for c in counts:
        n = max(0, float(c.get("count") or 0))
        if c.get("item_id"):
            updated += (await conn.execute(text("update app.stock_items set count = :n, counted_at = :t where id = cast(:i as uuid)"),
                                           {"n": n, "t": now, "i": c["item_id"]})).rowcount
        elif add_new and c.get("name"):
            await conn.execute(text("""insert into app.stock_items (org_id, name, unit, count, counted_at) values (:o, :n, :u, :c, :t)
                on conflict (org_id, lower(name)) do update set count = excluded.count, counted_at = excluded.counted_at"""),
                {"o": org_id, "n": str(c["name"])[:120], "u": c.get("unit") or "pc", "c": n, "t": now})
            added += 1
    await conn.execute(text("update app.stock_scans set status = 'applied', items = cast(:i as jsonb) where id = cast(:s as uuid)"),
                       {"i": json.dumps(counts), "s": sid})
    return {"updated": updated, "added": added}


async def reorder(conn: AsyncConnection, org_id: str, signoff: str | None) -> list[dict]:
    rows = (await conn.execute(text("""select name, unit, count, reorder_at, reorder_qty, supplier, supplier_phone from app.stock_items
        where count is not null and reorder_at > 0 and count <= reorder_at order by supplier nulls last, name"""))).mappings().all()
    business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["supplier"] or "(no supplier set)", []).append(r)
    out = []
    for sup, items in by.items():
        lines = "\n".join(f"• {i['name']}: {float(i['reorder_qty'] or i['reorder_at']):g} {i['unit']}" for i in items)
        out.append({"supplier": sup, "phone": items[0]["supplier_phone"], "items": [{"name": i["name"], "count": float(i["count"]), "reorder_at": float(i["reorder_at"]),
                    "order": float(i["reorder_qty"] or i["reorder_at"]), "unit": i["unit"]} for i in items],
                    "message": f"Hello{(' ' + sup) if not sup.startswith('(') else ''}, please send:\n{lines}\n\nThank you,\n{signoff or business}"})
    return out


COLS = {"name": ("item", "name", "product"), "unit": ("unit", "uom"), "reorder_at": ("reorder at", "reorder level", "min", "minimum", "par"),
        "reorder_qty": ("reorder qty", "order qty", "reorder quantity"), "supplier": ("supplier", "vendor"), "supplier_phone": ("supplier phone", "vendor phone", "phone"),
        "count": ("count", "stock", "qty", "quantity")}


async def import_items(conn: AsyncConnection, org_id: str, rows: list[list[str]]) -> dict:
    from agentry.automations.ca.core import find_col, money
    if len(rows) < 2:
        raise ValueError("the sheet needs a header row and at least one item")
    col = {k: find_col(rows[0], *n) for k, n in COLS.items()}
    if col["name"] is None:
        raise ValueError("the sheet needs an item name column")
    n = 0
    for r in rows[1:]:
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        if not g["name"]:
            continue
        await conn.execute(text("""insert into app.stock_items (org_id, name, unit, reorder_at, reorder_qty, supplier, supplier_phone, count, counted_at)
            values (:o, :n, :u, :ra, :rq, :s, :sp, :c, case when cast(:c as numeric) is null then null else now() end)
            on conflict (org_id, lower(name)) do update set unit = excluded.unit, reorder_at = excluded.reorder_at, reorder_qty = excluded.reorder_qty,
            supplier = excluded.supplier, supplier_phone = excluded.supplier_phone, count = coalesce(excluded.count, app.stock_items.count)"""),
            {"o": org_id, "n": g["name"][:120], "u": g["unit"] or "pc", "ra": money(g["reorder_at"]) or 0, "rq": money(g["reorder_qty"]) or 0,
             "s": g["supplier"] or None, "sp": g["supplier_phone"] or None, "c": money(g["count"])})
        n += 1
    return {"imported": n}
