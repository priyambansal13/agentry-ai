"""Catalogue & quotes (ROADMAP-V3 A3): product questions answered from the catalogue; quotes made, sent and followed up.

    catalogue  a CSV / Excel of products (code, name, description, category, unit, price, GST %, stock, minimum quantity)
               uploaded or replaced any time; the chat agent's search_catalog answers only from it
    quote      make_quote (chat) or the portal: the products and quantities, prices from the catalogue (never from the
               model), GST per item, a total and a validity date -> a numbered PDF (Q-2026-0001) behind a private link
    send       WhatsApp: the PDF as a document inside the 24-hour window, else a message with the link; else email.
               Approval mode: a quote the agent made waits on a card for a person to send it
    follow-up  after N days (settings: 2 and 5) a short reminder while it's still open; past its validity it expires;
               won / lost are marked in the portal (quote.won feeds results)
"""
import io
import json
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dbos import DBOS
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.automations.content import images
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.worker.handlers import on


class QuoteConfig(BaseModel):
    valid_days: int = Field(7, ge=1, le=90, title="Quotes are valid for (days)", json_schema_extra={"editable_by": "client"})
    follow_up_days: list[int] = Field(default_factory=lambda: [2, 5], title="Follow up this many days after sending",
                                      json_schema_extra={"editable_by": "client"})
    prices_include_gst: bool = Field(False, title="Catalogue prices already include GST", json_schema_extra={"editable_by": "client"})
    terms: str = Field("Prices are valid until the date shown. Delivery and installation charges, if any, are extra.",
                       title="Terms printed on quotes", json_schema_extra={"editable_by": "client"})
    gstin: str | None = Field(None, title="Your GSTIN (printed on quotes)", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="catalog_quotes", name="Catalogue & quotes",
    description="Answers product, price and stock questions from your catalogue, sends GST quotes as PDFs and follows them up.",
    config_model=QuoteConfig, metrics=("quotes_won",),
))

COLS = {"code": ("code", "sku", "item code", "product code"), "name": ("name", "product", "product name", "item"),
        "description": ("description", "details"), "category": ("category", "type", "group"), "unit": ("unit", "uom"),
        "price": ("price", "rate", "mrp", "selling price", "unit price"), "gst_rate": ("gst", "gst %", "gst rate", "tax %"),
        "stock": ("stock", "qty in stock", "available", "inventory"), "min_qty": ("min qty", "minimum", "moq")}


def money(v: Decimal | float) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'catalog_quotes'"))).first()
    return (row.status, QuoteConfig(**(row.config or {})).model_dump()) if row else (None, QuoteConfig().model_dump())


async def import_products(conn: AsyncConnection, org_id: str, rows: list[list[str]]) -> dict:
    from agentry.automations.ca.core import find_col
    from agentry.automations.ca.core import money as num
    if len(rows) < 2:
        raise ValueError("the sheet needs a header row and at least one product")
    col = {k: find_col(rows[0], *names) for k, names in COLS.items()}
    if col["name"] is None or col["price"] is None:
        raise ValueError("the sheet needs a product name column and a price column")
    n, skipped = 0, []
    for i, r in enumerate(rows[1:], start=2):
        g = {k: (str(r[c]).strip() if c is not None and c < len(r) else "") for k, c in col.items()}
        price = num(g["price"])
        if not g["name"] or price is None:
            skipped.append(i)
            continue
        code = (g["code"] or re.sub(r"[^A-Z0-9]+", "-", g["name"].upper()).strip("-")[:30]).upper()
        gst = num(g["gst_rate"].rstrip("%")) if g["gst_rate"] else 18
        await conn.execute(text("""insert into app.products (org_id, code, name, description, category, unit, price, gst_rate, stock, min_qty)
            values (:o, :c, :n, :d, :cat, :u, :p, :g, :s, :m) on conflict (org_id, code) do update set name = excluded.name,
            description = excluded.description, category = excluded.category, unit = excluded.unit, price = excluded.price,
            gst_rate = excluded.gst_rate, stock = excluded.stock, min_qty = excluded.min_qty, active = true, updated_at = now()"""),
            {"o": org_id, "c": code, "n": g["name"], "d": g["description"] or None, "cat": g["category"] or None, "u": g["unit"] or "pc",
             "p": price, "g": gst, "s": num(g["stock"]) if g["stock"] else None, "m": num(g["min_qty"]) or 1})
        n += 1
    return {"imported": n, "skipped_rows": skipped[:20]}


async def search_catalog(org_id: str, query: str, limit: int = 6) -> dict:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1][:6]
    if not words:
        return {"error": "say what product they're asking about"}
    score = " + ".join(f"(case when lower(code || ' ' || name || ' ' || coalesce(category, '') || ' ' || coalesce(description, '')) like :w{i} then 1 else 0 end)"
                       for i in range(len(words)))
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text(f"""select code, name, description, category, unit, price, gst_rate, stock, min_qty, ({score}) as hits
            from app.products where active and ({score}) > 0 order by hits desc, name limit :l"""),
            {**{f"w{i}": f"%{w}%" for i, w in enumerate(words)}, "l": limit})).mappings().all()
        _s, cfg = await settings_of(conn)
    if not rows:
        return {"found": False, "note": "not in the catalogue: say the team will confirm"}
    return {"found": True, "prices": "include GST" if cfg["prices_include_gst"] else "before GST",
            "products": [{"code": r["code"], "name": r["name"], "price": float(r["price"]), "unit": r["unit"], "gst_percent": float(r["gst_rate"]),
                          "in_stock": None if r["stock"] is None else float(r["stock"]) > 0, "stock": None if r["stock"] is None else float(r["stock"]),
                          "min_qty": float(r["min_qty"]), "details": (r["description"] or "")[:200]} for r in rows]}


# ---------- quotes ----------

async def build(conn: AsyncConnection, items: list[dict], prices_include_gst: bool) -> tuple[list[dict], dict, list[str]]:
    """Lines priced from the catalogue. Returns (lines, totals, problems)."""
    lines, problems = [], []
    for it in items:
        code = str(it.get("code") or "").strip().upper()
        qty = Decimal(str(it.get("qty") or 0))
        p = (await conn.execute(text("select * from app.products where upper(code) = :c and active"), {"c": code})).mappings().first()
        if not p:
            problems.append(f"{code or 'a product'} isn't in the catalogue")
            continue
        if qty <= 0:
            problems.append(f"{p['name']}: the quantity must be more than 0")
            continue
        if qty < p["min_qty"]:
            problems.append(f"{p['name']}: the minimum order is {p['min_qty']:g} {p['unit']}")
            continue
        rate, unit = Decimal(p["gst_rate"]), Decimal(p["price"])
        if prices_include_gst:
            unit = unit / (1 + rate / 100)
        amount = money(unit * qty)
        lines.append({"code": p["code"], "name": p["name"], "unit": p["unit"], "qty": float(qty), "unit_price": float(money(unit)), "gst_rate": float(rate),
                      "amount": float(amount), "gst": float(money(amount * rate / 100))})
    sub = money(sum((Decimal(str(x["amount"])) for x in lines), Decimal(0)))
    gst = money(sum((Decimal(str(x["gst"])) for x in lines), Decimal(0)))
    return lines, {"subtotal": sub, "gst": gst, "total": sub + gst}, problems


async def create_quote(conn: AsyncConnection, org_id: str, *, items: list[dict], customer: str, phone: str | None = None, email: str | None = None,
                       note: str | None = None, conversation_id: str | None = None, source: str = "person", user_id: str | None = None) -> dict:
    from agentry.leads import resolve_contact
    _s, cfg = await settings_of(conn)
    lines, totals, problems = await build(conn, items, cfg["prices_include_gst"])
    if problems or not lines:
        raise ValueError("; ".join(problems) or "add at least one product")
    contact = await resolve_contact(conn, org_id, name=customer, phone=phone, email=email, source="quote") if (phone or email) else None
    await conn.execute(text("select pg_advisory_xact_lock(hashtext(:o || '/quotes'))"), {"o": org_id})
    year = datetime.now(UTC).year
    n = (await conn.execute(text("select count(*) from app.quotes where number like :p"), {"p": f"Q-{year}-%"})).scalar_one() + 1
    number = f"Q-{year}-{n:04d}"
    currency = (await conn.execute(text("select currency from app.org_settings"))).scalar_one_or_none() or "INR"
    qid = (await conn.execute(text("""insert into app.quotes (org_id, number, token, contact_id, conversation_id, customer, phone, email, items, subtotal,
        gst, total, currency, valid_until, note, source, created_by) values (:o, :n, :t, cast(:k as uuid), cast(:c as uuid), :cu, :p, :e, cast(:i as jsonb),
        :s, :g, :tot, :cur, :v, :note, :src, :u) returning id::text"""),
        {"o": org_id, "n": number, "t": secrets.token_urlsafe(24), "k": contact, "c": conversation_id, "cu": customer[:120], "p": phone, "e": email,
         "i": json.dumps(lines), "s": totals["subtotal"], "g": totals["gst"], "tot": totals["total"], "cur": currency,
         "v": date.today() + timedelta(days=cfg["valid_days"]), "note": note, "src": source, "u": user_id})).scalar_one()
    await emit(conn, org_id, "quote.created", {"quote_id": qid, "number": number, "total": float(totals["total"]), "source": source})
    return {"id": qid, "number": number, "total": float(totals["total"]), "lines": lines}


def public_link(token: str) -> str:
    return f"{settings.api_public_url.rstrip('/')}/public/quotes/{token}.pdf"


def pdf(q: dict, business: str, cfg: dict, kit: dict) -> bytes:
    """An A4 quote, drawn with Pillow and saved as PDF (no extra dependency)."""
    W, H = 1240, 1754  # A4 at 150 dpi
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    brand = images._rgb(kit.get("primary_color"), (31, 42, 26))
    ink, muted = (20, 20, 20), (110, 110, 110)
    d.rectangle([0, 0, W, 170], fill=brand)
    d.text((80, 60), business, font=images._font(48), fill=images._ink_on(brand))
    d.text((W - 80, 60), "QUOTATION", font=images._font(40), fill=images._ink_on(brand), anchor="ra")
    y = 220
    f, fs = images._font(26), images._font(22)
    d.text((80, y), f"Quote {q['number']}", font=images._font(32), fill=ink)
    d.text((W - 80, y), f"Date: {q['created_at']:%d %b %Y}", font=f, fill=ink, anchor="ra")
    d.text((W - 80, y + 40), f"Valid until: {q['valid_until']:%d %b %Y}", font=f, fill=ink, anchor="ra")
    if cfg.get("gstin"):
        d.text((80, y + 45), f"GSTIN: {cfg['gstin']}", font=fs, fill=muted)
    y += 110
    d.text((80, y), "For", font=fs, fill=muted)
    d.text((80, y + 30), q["customer"], font=f, fill=ink)
    contact = " · ".join(x for x in (q.get("phone"), q.get("email")) if x)
    if contact:
        d.text((80, y + 65), contact, font=fs, fill=muted)
    y += 130
    cols = [(80, "Item"), (640, "Qty"), (760, "Rate"), (900, "GST"), (W - 80, "Amount")]
    d.rectangle([60, y - 10, W - 60, y + 40], fill=(242, 242, 236))
    for x, h in cols:
        d.text((x, y), h, font=fs, fill=ink, anchor="ra" if x == W - 80 else "la")
    y += 60
    for it in q["items"]:
        name = it["name"] if len(it["name"]) <= 38 else it["name"][:36] + "…"
        d.text((80, y), name, font=fs, fill=ink)
        d.text((80, y + 28), it["code"], font=images._font(18), fill=muted)
        d.text((640, y), f"{it['qty']:g} {it['unit']}", font=fs, fill=ink)
        d.text((760, y), f"{it['unit_price']:,.2f}", font=fs, fill=ink)
        d.text((900, y), f"{it['gst_rate']:g}%", font=fs, fill=ink)
        d.text((W - 80, y), f"{it['amount']:,.2f}", font=fs, fill=ink, anchor="ra")
        y += 70
        if y > H - 420:
            d.text((80, y), f"… and {len(q['items'])} items in all", font=fs, fill=muted)
            y += 50
            break
    d.line([60, y, W - 60, y], fill=(220, 220, 214), width=2)
    y += 20
    cur = "₹" if q["currency"] == "INR" else q["currency"] + " "
    for label, val, big in (("Subtotal", q["subtotal"], False), ("GST", q["gst"], False), ("Total", q["total"], True)):
        d.text((900, y), label, font=images._font(30 if big else 24), fill=ink)
        d.text((W - 80, y), f"{cur}{float(val):,.2f}", font=images._font(30 if big else 24), fill=ink, anchor="ra")
        y += 48 if big else 40
    if q.get("note"):
        d.text((80, y + 30), q["note"][:120], font=fs, fill=ink)
    d.text((80, H - 150), cfg.get("terms") or "", font=images._font(20), fill=muted)
    d.text((80, H - 100), f"Quote {q['number']} · {business}", font=images._font(18), fill=muted)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150.0)
    return buf.getvalue()


async def send_quote(org_id: str, qid: str, *, user_id: str | None = None) -> dict:
    from agentry.connectors.store import get_connection
    from agentry.outbound import reach_contact
    async with tenant_session(org_id) as conn:
        q = (await conn.execute(text("select * from app.quotes where id = cast(:i as uuid)"), {"i": qid})).mappings().one()
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        link = public_link(q["token"])
        body = (f"Hi {q['customer'].split()[0]}, here is your quote {q['number']} from {business}: {q['currency'].replace('INR', '₹')}"
                f"{float(q['total']):,.2f} including GST, valid until {q['valid_until']:%d %b}.\n{link}\nReply here to confirm or ask anything.")
        result = {"status": "no_channel"}
        wa = re.sub(r"\D", "", q["phone"] or "")
        if wa and await get_connection(org_id, "whatsapp") and q["conversation_id"]:
            from agentry.connectors.whatsapp import WhatsAppError, send_document, within_window
            try:
                if await within_window(org_id, str(q["conversation_id"])):
                    await send_document(org_id, wa, link, f"{q['number']}.pdf", caption=body.split("\n")[0])
                    result = {"status": "sent", "channel": "whatsapp"}
            except WhatsAppError:
                result = {"status": "no_channel"}
        if result["status"] != "sent" and q["contact_id"]:
            who = (await conn.execute(text("""select id::text as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
                from app.contacts where id = :k"""), {"k": q["contact_id"]})).mappings().one()
            result = await reach_contact(conn, org_id, dict(who), body, agent="catalog_quotes", subject=f"Your quote {q['number']} from {business}",
                                         email_ref=f"quote:{qid}")
        if result["status"] in ("sent", "recorded"):
            await conn.execute(text("update app.quotes set status = 'sent', sent_at = now() where id = cast(:i as uuid) and status = 'draft'"), {"i": qid})
            await audit.record(conn, org_id=org_id, actor_type="user" if user_id else "agent", actor_user_id=user_id, action="quote.sent",
                               target_type="quote", target_id=qid, metadata={"channel": result.get("channel")})
    return result


async def quote_from_chat(org_id: str, conversation_id: str, args: dict, source: str) -> dict:
    """The chat agent's make_quote: create the quote; live -> send it; approval mode -> a card for a person to send it."""
    async with tenant_session(org_id) as conn:
        status, _cfg = await settings_of(conn)
        if status not in ("live", "approval_mode"):
            return {"error": "quotes aren't available here: offer to have the team send one"}
        try:
            q = await create_quote(conn, org_id, items=args.get("items") or [], customer=str(args.get("name") or "Customer"), phone=args.get("phone"),
                                   email=args.get("email"), note=args.get("note"), conversation_id=conversation_id, source="agent")
        except ValueError as e:
            return {"error": str(e)}
        if status == "approval_mode":
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
                values (:o, 'outbound_draft', 'catalog_quotes', cast(:c as uuid), :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "c": conversation_id, "t": f"Send quote {q['number']} ({q['total']:,.2f})?",
                 "b": "\n".join(f"{x['qty']:g} x {x['name']}: {x['amount']:,.2f}" for x in q["lines"]), "p": json.dumps({"quote_id": q["id"]})})
            return {"quote": q["number"], "total": q["total"], "tell_customer": "Say the team will send the quote here shortly."}
    sent = await send_quote(org_id, q["id"])
    return {"quote": q["number"], "total": q["total"], "sent": sent["status"] == "sent",
            "tell_customer": f"Say quote {q['number']} for {q['total']:,.2f} including GST has been sent to them."}


async def quote_card_decided(org_id: str, approval_id: str, status: str) -> None:
    async with tenant_session(org_id) as conn:
        qid = (await conn.execute(text("select payload->>'quote_id' from app.approvals where id = cast(:a as uuid)"), {"a": approval_id})).scalar_one_or_none()
    if qid and status in ("approved", "edited"):
        await send_quote(org_id, qid)


@on("approval.decided")
@DBOS.workflow()
async def quote_card(event: dict) -> None:
    p = event["payload"]
    if p.get("kind") == "outbound_draft" and p.get("status") in ("approved", "edited"):
        await quote_card_step(event["org_id"], p["approval_id"], p["status"])


@DBOS.step()
async def quote_card_step(org_id: str, approval_id: str, status: str) -> None:
    await quote_card_decided(org_id, approval_id, status)


async def set_outcome(conn: AsyncConnection, org_id: str, qid: str, outcome: str, user_id: str | None) -> None:
    if outcome not in ("won", "lost"):
        raise ValueError("won or lost")
    row = (await conn.execute(text("""update app.quotes set status = :s, decided_at = now() where id = cast(:i as uuid) and status in ('sent','draft','expired')
        returning number, total"""), {"s": outcome, "i": qid})).first()
    if not row:
        raise ValueError("this quote is already decided")
    await emit(conn, org_id, f"quote.{outcome}", {"quote_id": qid, "number": row.number, "total": float(row.total)})
    await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"quote.{outcome}", target_type="quote", target_id=qid)


async def follow_ups(org_id: str, now: datetime | None = None) -> int:
    from agentry.outbound import reach_contact
    now = now or datetime.now(UTC)
    n = 0
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        await conn.execute(text("update app.quotes set status = 'expired' where status = 'sent' and valid_until < :d"), {"d": now.date()})
        if status != "live":
            return 0
        days = sorted({int(x) for x in cfg["follow_up_days"] if 0 < int(x) <= 60})
        rows = (await conn.execute(text("""select q.*, k.name as contact_name, k.phone_e164, k.attributes->>'telegram_id' as telegram_id
            from app.quotes q left join app.contacts k on k.id = q.contact_id where q.status = 'sent' and q.contact_id is not null"""))).mappings().all()
        for q in rows:
            if q["followups"] >= len(days) or now < q["sent_at"] + timedelta(days=days[q["followups"]]):
                continue
            body = (f"Hi {q['customer'].split()[0]}, just checking whether you had a chance to look at quote {q['number']}. "
                    f"It's valid until {q['valid_until']:%d %b}. Happy to answer any questions here.\n{public_link(q['token'])}")
            await reach_contact(conn, org_id, {"contact_id": str(q["contact_id"]), "contact_name": q["contact_name"], "phone_e164": q["phone_e164"],
                                               "email": q["email"], "telegram_id": q["telegram_id"]}, body, agent="catalog_quotes",
                                subject=f"Your quote {q['number']}", email_ref=f"quote:{q['id']}")
            await conn.execute(text("update app.quotes set followups = followups + 1, last_followup_at = :n where id = :i"), {"n": now, "i": q["id"]})
            n += 1
    return n


async def quote_jobs() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'catalog_quotes'
            and status in ('live','approval_mode')"""))).scalars())
    return sum([await follow_ups(o) for o in orgs])


@DBOS.step()
async def quote_jobs_step() -> int:
    return await quote_jobs()


@DBOS.workflow()
async def quote_schedule(scheduled_time: datetime, context) -> None:
    await quote_jobs_step()

