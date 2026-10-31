"""Document AI (ROADMAP-V2 7.4): a photo or PDF in, typed fields out, with a confidence for every field.

1. store    the file under var/documents/<org>/<id>.<ext>, its SHA-256 and who sent it
2. read     the `vision` tier reads the image (a PDF: its text if it has any, else the photo inside its first page)
3. check    code, not the model: required fields present, amounts add up (subtotal + taxes = total), CGST = SGST,
            GSTIN format and check digit, a plausible date, the same file or the same bill seen before
4. decide   each failed check lowers that field's confidence; every required field at or above the threshold and no
            blocking check -> ready, else needs_review (a person checks the fields on the document page)

Mock mode (no models, tests): the sample receipts in mock-data/documents are "read" from samples.json; anything else
is "not a document".
"""
import base64
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import runs
from agentry.config import ROOT, settings
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

MAX_BYTES = 10 * 1024 * 1024
TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
SAMPLES = ROOT / "mock-data" / "documents"

# name -> (type, required)
RECEIPT_FIELDS: dict[str, tuple[str, bool]] = {
    "vendor": ("text", True), "vendor_gstin": ("gstin", False), "bill_number": ("text", False), "date": ("date", True),
    "currency": ("text", False), "subtotal": ("money", False), "cgst": ("money", False), "sgst": ("money", False),
    "igst": ("money", False), "total": ("money", True), "category": ("text", True), "payment_method": ("text", False),
    "description": ("text", False),
}
GSTIN = re.compile(r"^(\d{2})[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class DocumentError(ValueError):
    pass


# ---------- checks ----------

def gstin_ok(g: str) -> bool:
    """Format, state code (01-38, 97 other territory, 99 centre) and the check digit."""
    g = (g or "").strip().upper()
    m = GSTIN.match(g)
    if not m or not (1 <= int(m[1]) <= 38 or m[1] in ("97", "99")):
        return False
    s = 0
    for i, c in enumerate(g[:14]):
        p = _B36.index(c) * (1 if i % 2 == 0 else 2)
        s += p // 36 + p % 36
    return g[14] == _B36[(36 - s % 36) % 36]


def _money(v: object) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, int | float):
        return round(float(v), 2)
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return round(float(s), 2) if s else None
    except ValueError:
        return None


def _date(v: object) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalise(raw: dict, categories: list[str]) -> dict:
    """Model output -> {name: {"value", "confidence"}} with typed values; unknown fields dropped, missing ones null."""
    out = {}
    for name, (kind, _req) in RECEIPT_FIELDS.items():
        f = raw.get(name) if isinstance(raw.get(name), dict) else {"value": raw.get(name), "confidence": 0.5 if raw.get(name) else 0}
        v, c = f.get("value"), f.get("confidence")
        try:
            c = max(0.0, min(1.0, float(c)))
        except (TypeError, ValueError):
            c = 0.5
        if kind == "money":
            v = _money(v)
        elif kind == "date":
            parsed = _date(v)
            c = c if parsed or v is None else min(c, 0.3)
            v = parsed
        elif kind == "gstin":
            v = re.sub(r"\s", "", str(v)).upper() if v else None
        else:
            v = str(v).strip()[:200] if v not in (None, "") else None
        if name == "category" and v and categories and v not in categories:
            match = next((k for k in categories if k.lower() == v.lower()), None)
            v, c = (match, c) if match else (v, min(c, 0.5))
        out[name] = {"value": v, "confidence": round(c if v is not None else (c if not RECEIPT_FIELDS[name][1] else 0.0), 2)}
    return out


def items_of(raw: object) -> list[dict]:
    out = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict) and (a := _money(it.get("amount"))) is not None:
            out.append({"description": str(it.get("description") or "")[:120], "amount": a})
    return out[:60]


def mark_unclear(fields: dict, unclear: object) -> list[str]:
    """Fields the model says it partly guessed: never above 0.4, whatever confidence it gave."""
    names = [n for n in (unclear if isinstance(unclear, list) else []) if n in fields]
    for n in names:
        fields[n]["confidence"] = min(fields[n]["confidence"], 0.4)
    return names


def check(fields: dict, today: date | None = None, items: list[dict] | None = None) -> list[dict]:
    """What code verifies on the extracted fields. Lowers the confidence of the fields involved (in place)."""
    today = today or datetime.now(UTC).date()
    out: list[dict] = []

    def flag(code: str, msg: str, severity: str, *names: str, cap: float | None = None) -> None:
        out.append({"code": code, "message": msg, "severity": severity, "fields": list(names)})
        for n in names:
            if cap is not None:
                fields[n]["confidence"] = min(fields[n]["confidence"], cap)

    val = {k: f["value"] for k, f in fields.items()}
    for name, (_k, req) in RECEIPT_FIELDS.items():
        if req and val.get(name) in (None, ""):
            flag("missing", f"{name.replace('_', ' ').capitalize()} couldn't be read", "error", name, cap=0.0)
    if val["total"] is not None and val["total"] <= 0:
        flag("total", "The total isn't a positive amount", "error", "total", cap=0.2)
    taxes = sum(v for v in (val["cgst"], val["sgst"], val["igst"]) if v)
    if val["subtotal"] is not None and val["total"] is not None:
        expected = round(val["subtotal"] + taxes, 2)
        if abs(expected - val["total"]) > max(1.0, 0.01 * val["total"]):
            flag("totals", f"Subtotal plus taxes is {expected:,.2f}, but the total reads {val['total']:,.2f}", "error",
                 "total", "subtotal", cap=0.5)
    if items and len(items) > 1 and val["total"] is not None:
        added = round(sum(i["amount"] for i in items), 2)
        target = val["subtotal"] if val["subtotal"] is not None else val["total"]
        # items may add up to the amount before tax or (tax-inclusive bills) to the total
        if all(abs(added - t) > max(1.0, 0.01 * t) for t in {target, val["total"]}):
            flag("items", f"The items add up to {added:,.2f}, not {target:,.2f}", "error", "total", cap=0.5)
    if (val["cgst"] or val["sgst"]) and abs((val["cgst"] or 0) - (val["sgst"] or 0)) > 0.05:
        flag("tax_split", "CGST and SGST should be equal", "warning", "cgst", "sgst", cap=0.6)
    if (val["cgst"] or val["sgst"]) and val["igst"]:
        flag("tax_mix", "A bill has either CGST + SGST or IGST, not both", "warning", "igst", cap=0.6)
    if val["vendor_gstin"] and not gstin_ok(val["vendor_gstin"]):
        flag("gstin", f"GSTIN {val['vendor_gstin']} isn't valid (format or check digit)", "error", "vendor_gstin", cap=0.3)
    if taxes and not val["vendor_gstin"]:
        flag("gstin_missing", "GST is charged but no GSTIN was read: input credit needs it", "warning")
    if val["date"]:
        d = date.fromisoformat(val["date"])
        if d > today + timedelta(days=1):
            flag("date_future", "The date is in the future", "error", "date", cap=0.3)
        elif d < today - timedelta(days=730):
            flag("date_old", "The date is more than two years ago", "warning", "date", cap=0.6)
    return out


def decide(fields: dict, checks: list[dict], threshold: float) -> tuple[str, float]:
    """(status, overall confidence): the weakest required field decides."""
    overall = min(fields[n]["confidence"] for n, (_k, req) in RECEIPT_FIELDS.items() if req)
    blocking = any(c["severity"] == "error" for c in checks)
    return ("ready" if overall >= threshold and not blocking else "needs_review"), round(overall, 2)


# ---------- reading ----------

@lru_cache
def _samples() -> dict[str, dict]:
    """sha256 -> what the model should read (mock mode)."""
    data = json.loads((SAMPLES / "samples.json").read_text())
    return {hashlib.sha256((SAMPLES / name).read_bytes()).hexdigest(): {"name": name, **v} for name, v in data.items()}


def sample_files() -> list[Path]:
    return [SAMPLES / n for n in json.loads((SAMPLES / "samples.json").read_text())]


def _pdf_content(data: bytes) -> tuple[str | None, bytes | None, str | None]:
    """(text, image, image mime) from a PDF's first pages: text if it has some, else the photo inside the first page."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        txt = "\n".join((p.extract_text() or "") for p in reader.pages[:3]).strip()
        if len(txt) > 40:
            return txt[:8000], None, None
        for img in reader.pages[0].images if reader.pages else []:
            return None, img.data, "image/png" if img.name.lower().endswith(".png") else "image/jpeg"
    except Exception as e:
        raise DocumentError("This PDF can't be opened (is it password-protected?)") from e
    raise DocumentError("This PDF has no text or photo to read")


async def read(org_id: str, data: bytes, mime: str, categories: list[str], country: str = "IN", currency: str = "INR") -> dict:
    """The model's reading: {"is_document", "kind", "fields": {...}}, with the model used."""
    sha = hashlib.sha256(data).hexdigest()
    mock = _samples().get(sha) or {"is_document": False, "kind": "other", "fields": {}}
    note, image, image_mime = "The document is attached as an image.", data, mime
    if mime == "application/pdf":
        txt, image, image_mime = _pdf_content(data)
        if txt:
            note = "The document's text:\n" + txt
    prompt = load("document_receipt")
    messages = prompt.render(categories=", ".join(categories), country=country, currency=currency, text=note)
    if image:
        messages[-1] = {"role": "user", "content": [
            {"type": "text", "text": messages[-1]["content"]},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{base64.b64encode(image).decode()}"}}]}
    res = await complete(prompt.tier, messages, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version,
                         json_output=True, mock_response=json.dumps({k: v for k, v in mock.items() if k != "name"}), temperature=0)
    out = res.data if isinstance(res.data, dict) else {"is_document": False, "kind": "other", "fields": {}}
    out["model"] = res.model
    return out


# ---------- the whole thing ----------

def folder(org_id: str) -> Path:
    p = Path(settings.documents_dir) / org_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def path_of(row: dict) -> Path:
    return Path(settings.documents_dir) / row["file_path"]


def mime_of(filename: str | None, declared: str | None) -> str | None:
    if declared in TYPES:
        return declared
    ext = Path(filename or "").suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}.get(ext)


async def store(conn: AsyncConnection, org_id: str, data: bytes, *, mime: str, filename: str | None, source: str,
                automation_key: str, contact_id: str | None = None, conversation_id: str | None = None, user_id: str | None = None) -> str:
    if mime not in TYPES:
        raise DocumentError("Send a photo (JPG, PNG, WEBP) or a PDF")
    if len(data) > MAX_BYTES:
        raise DocumentError("Files can be up to 10 MB")
    if not data:
        raise DocumentError("The file is empty")
    sha = hashlib.sha256(data).hexdigest()
    did = str((await conn.execute(text("""insert into app.documents (org_id, source, filename, mime, bytes, sha256, file_path, contact_id,
            conversation_id, automation_key, created_by) values (:o, :s, :f, :m, :b, :h, '', :k, :c, :a, :u) returning id"""),
        {"o": org_id, "s": source, "f": (filename or "")[:200] or None, "m": mime, "b": len(data), "h": sha, "k": contact_id,
         "c": conversation_id, "a": automation_key, "u": user_id})).scalar_one())
    path = folder(org_id) / f"{did}{TYPES[mime]}"
    path.write_bytes(data)
    await conn.execute(text("update app.documents set file_path = :p where id = cast(:i as uuid)"),
                       {"p": str(path.relative_to(Path(settings.documents_dir))), "i": did})
    return did


async def _duplicates(conn: AsyncConnection, doc_id: str, sha: str, fields: dict) -> tuple[str | None, list[dict]]:
    """(exact duplicate's id, checks): the same file, or the same vendor + bill number / date + total, seen before."""
    same = (await conn.execute(text("""select id::text from app.documents where sha256 = :h and id <> cast(:i as uuid) and status <> 'rejected'
        order by created_at limit 1"""), {"h": sha, "i": doc_id})).scalar_one_or_none()
    if same:
        return same, [{"code": "duplicate_file", "message": "This exact file was already received", "severity": "error", "fields": []}]
    v = {k: f["value"] for k, f in fields.items()}
    if not v.get("vendor"):
        return None, []
    like = (await conn.execute(text("""select id::text from app.documents where id <> cast(:i as uuid) and status in ('ready','needs_review')
        and lower(fields->'vendor'->>'value') = lower(:v)
        and ((cast(:n as text) is not null and fields->'bill_number'->>'value' = cast(:n as text))
             or (fields->'date'->>'value' = cast(:d as text) and (fields->'total'->>'value')::numeric = cast(:t as numeric)))
        order by created_at limit 1"""), {"i": doc_id, "v": v["vendor"], "n": v.get("bill_number"), "d": v.get("date"), "t": v.get("total")})).scalar_one_or_none()
    if like:
        return like, [{"code": "duplicate", "message": "Looks like a bill already received (same vendor and bill number, or same date and total)",
                       "severity": "error", "fields": ["vendor", "total"]}]
    return None, []


async def process(org_id: str, doc_id: str, *, categories: list[str], threshold: float, agent: str = "bookkeeping") -> dict:
    """Read, check and decide one stored document. Returns its row (status ready / needs_review / rejected / failed)."""
    async with runs.run(org_id, agent, "document", key=f"document:{doc_id}", subject=("document", doc_id)) as r:
        async with tenant_session(org_id) as conn:
            row = dict((await conn.execute(text("select * from app.documents where id = cast(:i as uuid)"), {"i": doc_id})).mappings().one())
            country, currency = (await conn.execute(text("select country, currency from app.org_settings"))).one()
        data = path_of(row).read_bytes()
        try:
            raw = await read(org_id, data, row["mime"], categories, country or "IN", currency or "INR")
        except (DocumentError, AllModelsFailed) as e:
            msg = str(e) if isinstance(e, DocumentError) else "The reading models are unavailable right now; try again shortly"
            r.fail(msg)
            async with tenant_session(org_id) as conn:
                await conn.execute(text("update app.documents set status = 'failed', error = :e where id = cast(:i as uuid)"), {"e": msg, "i": doc_id})
            return {**row, "status": "failed", "error": msg}
        r.step("read", model=raw.get("model"), is_document=bool(raw.get("is_document")))
        if not raw.get("is_document"):
            async with tenant_session(org_id) as conn:
                await conn.execute(text("""update app.documents set status = 'failed', kind = 'other', error = 'Not a receipt or bill'
                    where id = cast(:i as uuid)"""), {"i": doc_id})
            return {**row, "status": "failed", "kind": "other", "error": "Not a receipt or bill"}
        fields = normalise(raw.get("fields") or {}, categories)
        items = items_of(raw.get("line_items"))
        unclear = mark_unclear(fields, raw.get("unclear"))
        checks = check(fields, items=items)
        if unclear:
            checks.append({"code": "unclear", "message": "Partly unreadable: " + ", ".join(n.replace("_", " ") for n in unclear), "severity": "warning",
                           "fields": unclear})
        async with tenant_session(org_id) as conn:
            dup, dup_checks = await _duplicates(conn, doc_id, row["sha256"], fields)
            checks += dup_checks
            status, overall = decide(fields, checks, threshold)
            if dup_checks and dup_checks[0]["code"] == "duplicate_file":
                status = "rejected"
            kind = raw.get("kind") if raw.get("kind") in ("receipt", "bill") else "receipt"
            await conn.execute(text("""update app.documents set status = :s, kind = :k, fields = cast(:f as jsonb), checks = cast(:c as jsonb),
                confidence = :conf, duplicate_of = cast(:d as uuid), line_items = cast(:li as jsonb), error = null where id = cast(:i as uuid)"""),
                {"s": status, "k": kind, "f": json.dumps(fields), "c": json.dumps(checks), "conf": overall, "d": dup, "i": doc_id,
                 "li": json.dumps(items)})
        r.step("checked", status=status, confidence=overall, checks=[c["code"] for c in checks])
    return {**row, "status": status, "kind": kind, "fields": fields, "checks": checks, "confidence": overall, "duplicate_of": dup, "line_items": items}


def summary(fields: dict) -> str:
    v = {k: f["value"] for k, f in fields.items()}
    amount = f"{v.get('currency') or ''} {v['total']:,.2f}".strip() if v.get("total") is not None else "amount unclear"
    when = date.fromisoformat(v["date"]).strftime("%d %b") if v.get("date") else "date unclear"
    return f"{v.get('vendor') or 'Unknown vendor'}, {amount.replace('INR ', '₹')} on {when}"
