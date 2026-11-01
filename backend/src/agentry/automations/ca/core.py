"""What every CA Firm agent shares (docs/PACKS.md): the firm's clients, their filings and the files they send.

    clients   a person or business the firm files for; linked to a contact, so WhatsApp / email reach them through the
              same conversations (and consent) as every other agent
    filings   one card per filing (ITR AY 2026-27, GSTR-3B 2026-10…), on the filing tracker's board
    files     what a client sent or the firm uploaded; readers store what they took out of a file next to it, with the
              source of every number
Who works on it: owners, managers, front desk and finance (anyone who acts on conversations or money); viewers read.
"""
import csv
import hashlib
import io
import json
import re
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.leads import normalize_phone, record_consent, resolve_contact

CA_KEYS = ("ca_filing_tracker", "ca_document_chaser", "ca_tax_docs_reader", "ca_compliance_calendar", "ca_gst_reconciliation",
           "ca_itr_prep", "ca_capital_gains", "ca_bank_classifier", "ca_notice_handler", "ca_tds_returns", "ca_tax_audit",
           "excel_desk")
STATUSES = ["docs_pending", "in_prep", "review", "filed", "verified"]
STATUS_LABEL = {"docs_pending": "Documents pending", "in_prep": "In preparation", "review": "In review", "filed": "Filed",
                "verified": "Verified"}
CLIENT_KINDS = ("individual", "huf", "firm", "llp", "company", "trust")
# what a client's profile can say about them; drives checklists and the compliance calendar
PROFILE_FLAGS = {
    "salaried": "Salary income (Form 16)", "business": "Business or profession", "capital_gains": "Shares, mutual funds or property sold",
    "house_property": "Owns a let-out or home-loan property", "rent_paid": "Pays rent (HRA)", "foreign": "Foreign income or assets",
    "deductions": "Claims 80C / 80D deductions", "audit": "Tax audit (44AB)", "gst": "GST registered", "gst_qrmp": "GST quarterly (QRMP)",
    "tds": "Deducts TDS", "pf_esi": "PF / ESI employer", "company_roc": "Company or LLP (ROC filings)", "advance_tax": "Pays advance tax",
}
KINDS = {  # filing kind -> label
    "itr": "ITR", "gstr1": "GSTR-1", "gstr3b": "GSTR-3B", "gstr9": "GSTR-9 annual", "tds_24q": "TDS 24Q (salary)",
    "tds_26q": "TDS 26Q (non-salary)", "tds_payment": "TDS payment", "advance_tax": "Advance tax", "tax_audit": "Tax audit (3CA/3CD)",
    "roc_aoc4": "ROC AOC-4", "roc_mgt7": "ROC MGT-7", "dir3_kyc": "DIR-3 KYC", "pf_esi": "PF / ESI", "notice_reply": "Notice reply",
    "other": "Other",
}
FILE_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "text/csv", "text/plain", "application/json",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_FILE = 20 * 1024 * 1024


class CaError(ValueError):
    pass


def can_work(ctx) -> bool:
    return ctx.can("conversation", "act") or ctx.can("invoice", "act")


def can_read(ctx) -> bool:
    return can_work(ctx) or ctx.can("invoice", "read")


async def enabled(conn: AsyncConnection, key: str) -> dict | None:
    """The agent's settings when it's switched on (setup, approval mode or live), else None."""
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = :k"), {"k": key})).first()
    return {"status": row.status, **(row.config or {})} if row else None


# ---------- clients ----------

def pan_ok(pan: str | None) -> bool:
    return bool(pan and re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan.upper()))


async def save_client(conn: AsyncConnection, org_id: str, data: dict, client_id: str | None = None) -> str:
    """Create or update a client; their contact (for WhatsApp / email) is found or created from the phone and email.
    data: name, kind, pan, gstin, phone, email, profile, assignee, notes, whatsapp_ok."""
    pan = (data.get("pan") or "").strip().upper() or None
    if pan and not pan_ok(pan):
        raise CaError(f"{pan} isn't a valid PAN (5 letters, 4 digits, 1 letter)")
    gstin = (data.get("gstin") or "").strip().upper() or None
    if data.get("kind", "individual") not in CLIENT_KINDS:
        raise CaError("unknown client type")
    profile = {k: bool(v) for k, v in (data.get("profile") or {}).items() if k in PROFILE_FLAGS}
    contact = None
    if data.get("phone") or data.get("email"):
        contact = await resolve_contact(conn, org_id, name=data["name"], email=data.get("email"), phone=data.get("phone"), source="ca_client")
        if data.get("whatsapp_ok", True) and data.get("phone"):
            await record_consent(conn, org_id, contact, "whatsapp", True, "ca_client")  # an existing client of the firm
    params = {"o": org_id, "n": data["name"].strip(), "k": data.get("kind", "individual"), "p": pan, "g": gstin, "ph": data.get("phone"),
              "e": data.get("email"), "pr": json.dumps(profile), "a": data.get("assignee"), "no": data.get("notes"), "c": contact}
    try:
        if client_id:
            done = (await conn.execute(text("""update app.ca_clients set name = :n, kind = :k, pan = :p, gstin = :g, phone = :ph,
                email = :e, profile = cast(:pr as jsonb), assignee = :a, notes = :no, contact_id = coalesce(:c, contact_id), updated_at = now()
                where id = cast(:i as uuid) returning id"""), params | {"i": client_id})).first()
            if not done:
                raise CaError("client not found")
            return client_id
        return str((await conn.execute(text("""insert into app.ca_clients (org_id, name, kind, pan, gstin, phone, email, profile, assignee,
            notes, contact_id) values (:o, :n, :k, :p, :g, :ph, :e, cast(:pr as jsonb), :a, :no, :c) returning id"""), params)).scalar_one())
    except Exception as e:
        if "ca_clients_pan" in str(e):
            raise CaError(f"another client already has PAN {pan}") from e
        raise


IMPORT_COLUMNS = {"name": ("name", "client", "client name"), "pan": ("pan", "pan no", "pan number"), "phone": ("phone", "mobile", "whatsapp"),
                  "email": ("email", "e-mail", "mail"), "gstin": ("gstin", "gst", "gst no"), "kind": ("type", "kind", "status")}


async def import_clients(conn: AsyncConnection, org_id: str, csv_text: str, profile: dict | None = None) -> dict:
    """A CSV with a header row (name, PAN, phone, email, GSTIN, type). Rows with a PAN that already exists update it."""
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if len(rows) < 2:
        raise CaError("the file needs a header row and at least one client")
    head = [h.strip().lower() for h in rows[0]]
    col = {k: next((head.index(a) for a in names if a in head), None) for k, names in IMPORT_COLUMNS.items()}
    if col["name"] is None:
        raise CaError("no 'name' column")
    added, updated, errors = 0, 0, []
    for n, r in enumerate(rows[1:], start=2):
        row = {k: (r[i].strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        get = row.__getitem__
        if not get("name"):
            continue
        kind = get("kind").lower()
        kind = kind if kind in CLIENT_KINDS else ("company" if "pvt" in get("name").lower() or "ltd" in get("name").lower() else "individual")
        existing = None
        if get("pan"):
            existing = (await conn.execute(text("select id::text from app.ca_clients where upper(pan) = upper(:p)"), {"p": get("pan")})).scalar_one_or_none()
        try:
            async with conn.begin_nested():
                await save_client(conn, org_id, {"name": get("name"), "pan": get("pan"), "phone": get("phone"), "email": get("email"),
                                                 "gstin": get("gstin"), "kind": kind, "profile": profile or {}}, existing)
            updated += bool(existing)
            added += not existing
        except CaError as e:
            errors.append(f"row {n}: {e}")
    return {"added": added, "updated": updated, "errors": errors[:20]}


async def client_by_phone(conn: AsyncConnection, phone: str | None) -> dict | None:
    """The firm's client whose WhatsApp number this is (the last 10 digits match)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return None
    rows = (await conn.execute(text("""select c.id::text, c.name, c.phone, c.contact_id::text, c.profile from app.ca_clients c
        left join app.contacts k on k.id = c.contact_id where right(regexp_replace(coalesce(k.phone_e164, c.phone, ''), '\\D', '', 'g'), 10) = :d
        order by c.created_at"""), {"d": digits[-10:]})).mappings().all()
    return dict(rows[0]) if rows else None


async def who(conn: AsyncConnection, client_id: str) -> dict:
    """The `who` that outbound.reach_contact takes."""
    r = (await conn.execute(text("""select c.name, c.email, c.contact_id::text, k.phone_e164, k.attributes->>'telegram_id' as telegram_id
        from app.ca_clients c left join app.contacts k on k.id = c.contact_id where c.id = cast(:i as uuid)"""), {"i": client_id})).mappings().one()
    return {"contact_id": r["contact_id"], "contact_name": r["name"], "phone_e164": r["phone_e164"], "email": r["email"],
            "telegram_id": r["telegram_id"]}


# ---------- files ----------

def folder(org_id: str) -> Path:
    p = Path(settings.documents_dir) / org_id / "ca"
    p.mkdir(parents=True, exist_ok=True)
    return p


def path_of(row) -> Path:
    return Path(settings.documents_dir) / row["path"]


def mime_of(filename: str | None, declared: str | None) -> str | None:
    if declared in FILE_TYPES:
        return declared
    ext = Path(filename or "").suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf",
            ".csv": "text/csv", ".txt": "text/plain", ".json": "application/json",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(ext)


async def store_file(conn: AsyncConnection, org_id: str, client_id: str, data: bytes, *, filename: str | None, mime: str | None,
                     source: str = "portal", filing_id: str | None = None, item_key: str | None = None, doc_type: str | None = None,
                     user_id: str | None = None) -> str:
    mime = mime_of(filename, mime)
    if not mime:
        raise CaError("send a PDF, photo, CSV, Excel (.xlsx), JSON or text file")
    if not data:
        raise CaError("the file is empty")
    if len(data) > MAX_FILE:
        raise CaError("files can be up to 20 MB")
    fid = str(uuid.uuid4())
    ext = Path(filename or "").suffix.lower() or {"application/pdf": ".pdf", "image/jpeg": ".jpg"}.get(mime, "")
    p = folder(org_id) / f"{fid}{ext}"
    p.write_bytes(data)
    await conn.execute(text("""insert into app.ca_files (id, org_id, client_id, filing_id, item_key, doc_type, filename, mime, path, bytes,
        sha256, source, created_by) values (cast(:id as uuid), :o, cast(:c as uuid), cast(:f as uuid), :ik, :dt, :fn, :m, :p, :b, :s, :src, :u)"""),
        {"id": fid, "o": org_id, "c": client_id, "f": filing_id, "ik": item_key, "dt": doc_type, "fn": filename or f"file{ext}", "m": mime,
         "p": str(p.relative_to(Path(settings.documents_dir))), "b": len(data), "s": hashlib.sha256(data).hexdigest(), "src": source, "u": user_id})
    return fid


def text_of(data: bytes, mime: str, max_chars: int = 60000) -> str | None:
    """The file as text for a reader agent: PDF text layer, CSV/TXT/JSON as is, Excel as tab-separated rows. None for
    photos and scanned PDFs (they're read as images)."""
    if mime == "application/pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise CaError("this PDF is password-protected: AIS / 26AS PDFs open with PAN (lowercase) + date of birth (DDMMYYYY); "
                              "save an unlocked copy or upload the JSON / text version")
            txt = "\n".join((p.extract_text() or "") for p in reader.pages[:40]).strip()
        except CaError:
            raise
        except Exception as e:
            raise CaError("this PDF can't be opened") from e
        return txt[:max_chars] if len(txt) > 40 else None
    if mime in ("text/csv", "text/plain", "application/json"):
        return data.decode("utf-8-sig", errors="ignore")[:max_chars]
    if mime.endswith("spreadsheetml.sheet"):
        return "\n".join("\t".join(r) for r in xlsx_rows(data))[:max_chars]
    return None


def xlsx_rows(data: bytes, sheet: int = 0) -> list[list[str]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise CaError("this Excel file can't be opened") from e
    ws = wb.worksheets[min(sheet, len(wb.worksheets) - 1)]
    out = []
    for row in ws.iter_rows(values_only=True):
        vals = ["" if v is None else (v.isoformat()[:10] if isinstance(v, date) else str(v)) for v in row]
        if any(v.strip() for v in vals):
            out.append(vals)
    return out


def table_rows(data: bytes, mime: str) -> list[list[str]]:
    """CSV or Excel as rows of strings (header first)."""
    if mime.endswith("spreadsheetml.sheet"):
        return xlsx_rows(data)
    return [r for r in csv.reader(io.StringIO(data.decode("utf-8-sig", errors="ignore"))) if any(c.strip() for c in r)]


def xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    """An Excel workbook from {sheet name: rows}; the first row of each sheet is bold."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", " ", name)[:31])
        for r in rows:
            ws.append(r)
        for c in ws[1] if rows else []:
            c.font = Font(bold=True)
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def money(v: object) -> float | None:
    """'₹1,23,456.50', '1,23,456', '(2,000)', 1234 -> float; None if it isn't a number."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^\d.]", "", s)
    if not s or s.count(".") > 1:
        return None
    return -float(s) if neg else float(s)


def inr(v: float | None) -> str:
    if v is None:
        return "-"
    neg, v = v < 0, abs(round(v))
    s = str(int(v))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if len(head) > 2 else head
        s = f"{head},{tail}"
    return f"{'-' if neg else ''}₹{s}"


async def card(conn: AsyncConnection, org_id: str, agent: str, title: str, body: str, payload: dict) -> str | None:
    """A Needs-you card for the firm (deduplicated: the same `payload["key"]` while one is still open)."""
    if (await conn.execute(text("""select 1 from app.approvals where kind = 'ca_task' and status = 'pending' and payload->>'key' = :k"""),
                           {"k": payload["key"]})).first():
        return None
    return str((await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
        values (:o, 'ca_task', :a, :t, :b, cast(:p as jsonb)) returning id"""),
        {"o": org_id, "a": agent, "t": title[:200], "b": body, "p": json.dumps(payload)})).scalar_one())


def phone_of(raw: str | None) -> str | None:
    return normalize_phone(raw, "IN")
