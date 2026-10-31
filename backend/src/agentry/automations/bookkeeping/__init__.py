"""Bookkeeping assistant (ROADMAP-V2 9.5): receipts and bills by photo, read by Document AI, checked, exported.

    in       a photo or PDF in the portal, on the business's WhatsApp or Telegram (from anyone, or only the senders
             listed in settings), or the samples
    read     documents.process: fields + confidence + checks (totals, GSTIN, dates, duplicates)
    ready    confident and clean: filed straight away; the sender gets "Got it: FreshMart, ₹1,254.76 on 28 Oct"
    check    otherwise a Needs-you card (money permission: owner, manager, finance); the document page shows each
             field with its confidence; Accept / fix / Reject there, or Approve the card to accept as read
    budgets  a category passing 80% of its monthly budget alerts once a month (event budget.alert)
    monthly  on the 1st: last month by category vs the month before, top vendors, what still needs checking
             (event bookkeeping.monthly), numbers from code; the one-line observation can't add numbers
    export   Tally (XML vouchers) or CSV for Google Sheets / Excel; only ready documents
"""
import csv
import io
import json
import re
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import documents
from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.worker.handlers import on

CATEGORIES = ["Rent", "Salaries & wages", "Supplies & materials", "Groceries & pantry", "Utilities", "Travel & fuel", "Meals & entertainment",
              "Repairs & maintenance", "Marketing", "Software & subscriptions", "Professional fees", "Equipment", "Other"]


class BookkeepingConfig(BaseModel):
    categories: list[str] = Field(default_factory=lambda: list(CATEGORIES), title="Expense categories",
                                  json_schema_extra={"editable_by": "client"})
    budgets: dict[str, float] = Field(default_factory=dict, title="Monthly budgets by category (₹)",
                                      description="e.g. {\"Supplies & materials\": 40000}. An alert when a category passes 80%.",
                                      json_schema_extra={"editable_by": "client"})
    review_below: float = Field(0.85, ge=0.5, le=0.99, title="A person checks anything read with less confidence than",
                                json_schema_extra={"editable_by": "client"})
    senders: list[str] = Field(default_factory=list, title="Who may send receipts on WhatsApp / Telegram",
                               description="Phone numbers (+91…) or Telegram @usernames. Empty: anyone who sends a photo of a bill.",
                               json_schema_extra={"editable_by": "client"})
    monthly_insights: bool = Field(True, title="Monthly summary on the 1st", json_schema_extra={"editable_by": "client"})
    email_intake: bool = Field(True, title="Read bills attached to emails in the connected Gmail",
                               description="PDFs and photos attached to emails that look like a bill, invoice or receipt (subject or file name)",
                               json_schema_extra={"editable_by": "client"})
    email_senders: list[str] = Field(default_factory=list, title="Always read attachments from these senders",
                                     description="e.g. billing@supplier.com: any attachment from them is treated as a bill",
                                     json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="bookkeeping",
    name="Bookkeeping assistant",
    description="Reads receipts and bills sent by photo, checks GST and totals, flags duplicates, and exports to Tally or Sheets.",
    config_model=BookkeepingConfig,
    metrics=("documents_processed",),
))


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'bookkeeping'"))).first()
    return (row.status, BookkeepingConfig(**(row.config or {})).model_dump()) if row else (None, BookkeepingConfig().model_dump())


def _month(d: str | None) -> str | None:
    return d[:7] if d else None


# ---------- in ----------

async def ingest(org_id: str, data: bytes, *, mime: str, filename: str | None, source: str, contact_id: str | None = None,
                 conversation_id: str | None = None, user_id: str | None = None) -> dict:
    """Store, read and file one document; a card if a person must check it. Returns the processed document."""
    async with tenant_session(org_id) as conn:
        _st, cfg = await settings_of(conn)
        did = await documents.store(conn, org_id, data, mime=mime, filename=filename, source=source, automation_key="bookkeeping",
                                    contact_id=contact_id, conversation_id=conversation_id, user_id=user_id)
    doc = await documents.process(org_id, did, categories=cfg["categories"], threshold=cfg["review_below"])
    await after(org_id, did, doc, cfg)
    return {**doc, "id": did}


async def after(org_id: str, did: str, doc: dict, cfg: dict) -> None:
    async with tenant_session(org_id) as conn:
        await emit(conn, org_id, "document.processed", {"document_id": did, "status": doc["status"]})
        if doc["status"] == "needs_review":
            weak = [n.replace("_", " ") for n, f in doc["fields"].items() if documents.RECEIPT_FIELDS[n][1] and f["confidence"] < cfg["review_below"]]
            reasons = [c["message"] for c in doc["checks"]] + ([f"Not sure about: {', '.join(weak)}"] if weak else [])
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
                values (:o, 'document_review', 'bookkeeping', :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "t": f"Check this {doc['kind']}: {documents.summary(doc['fields'])}", "b": "\n".join(f"• {r}" for r in reasons),
                 "p": json.dumps({"document_id": did})})
        elif doc["status"] == "ready":
            await budget_check(conn, org_id, doc["fields"], cfg)
    if doc["status"] == "ready":
        await push_to_sheets(org_id)


def allowed_sender(cfg: dict, phone: str | None, tg_username: str | None) -> bool:
    """Empty list: anyone. Else a listed phone number (last 10 digits match) or Telegram @username."""
    if not cfg["senders"]:
        return True
    digits = re.sub(r"\D", "", phone or "")
    for s in cfg["senders"]:
        s = s.strip()
        want = re.sub(r"\D", "", s)
        if s.startswith("@") or not want:
            if tg_username and s.lstrip("@").lower() == tg_username.lower():
                return True
        elif digits and digits[-10:] == want[-10:]:
            return True
    return False


async def _reply(org_id: str, channel: str, conversation_id: str, to: str, body: str) -> None:
    if channel == "whatsapp":
        from agentry.connectors.whatsapp import send_text
        ext = f"wa:{await send_text(org_id, to, body)}"
    else:
        from agentry.connectors.telegram import send_to_customer
        ext = f"tg:{to}:{await send_to_customer(org_id, int(to), body)}"
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb))"""),
            {"o": org_id, "c": conversation_id, "b": body, "m": json.dumps({"external_id": ext, "sent_from": "bookkeeping"})})


def reply_text(doc: dict) -> str:
    if doc["status"] == "ready":
        cat = doc["fields"]["category"]["value"]
        return f"Got it: {documents.summary(doc['fields'])}" + (f", filed under {cat}." if cat else ".")
    if doc["status"] == "needs_review":
        return f"Got it: {documents.summary(doc['fields'])}. A couple of details are unclear, so a person will check it."
    if doc["status"] == "rejected":
        return "We already have this one, so it wasn't filed twice."
    return f"Sorry, I couldn't read that ({doc.get('error') or 'unclear'}). Could you send a clearer photo, flat and in good light?"


@DBOS.step()
async def take_from_chat(org_id: str, channel: str, conversation_id: str, payload: dict) -> bool:
    """For the WhatsApp / Telegram assistants: a photo or PDF from an allowed sender is a receipt. True = handled."""
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode"):
            return False
        who = (await conn.execute(text("""select k.id::text, k.phone_e164, k.attributes->>'telegram_username' as tg from app.conversations c
            join app.contacts k on k.id = c.contact_id where c.id = cast(:c as uuid)"""), {"c": conversation_id})).mappings().first()
    if not who or not allowed_sender(cfg, who["phone_e164"], who["tg"]):
        return False
    try:
        if channel == "whatsapp":
            from agentry.connectors.whatsapp import download_media
            media = payload.get("media") or {}
            if not media.get("id"):
                return False
            data, mime = await download_media(org_id, media["id"])
            filename, to = media.get("filename"), payload["wa_id"]
        else:
            from agentry.connectors.store import get_connection
            from agentry.connectors.telegram import download
            f = payload.get("file") or {}
            if not f.get("file_id"):
                return False
            conn_row = await get_connection(org_id, "telegram")
            data, mime, filename, to = await download(conn_row["secret"]["bot_token"], f["file_id"]), f.get("mime"), f.get("name"), str(payload["chat_id"])
        mime = documents.mime_of(filename, mime)
        if not mime:
            return False
        doc = await ingest(org_id, data, mime=mime, filename=filename, source=channel, contact_id=who["id"], conversation_id=conversation_id)
    except documents.DocumentError as e:
        doc = {"status": "failed", "error": str(e)}
    if doc["status"] == "failed" and doc.get("kind") == "other" and not cfg["senders"]:
        return False  # anyone may send photos, and this isn't a bill: the assistant deals with it as before
    await _reply(org_id, channel, conversation_id, to, reply_text(doc))
    return True


# ---------- email ----------

BILLISH = re.compile(r"invoice|bill|receipt|tax|gst|payment|statement|challan|voucher|purchase order", re.IGNORECASE)
FILE_TYPES = (".pdf", ".jpg", ".jpeg", ".png", ".webp")


def email_wants(cfg: dict, sender: str, subject: str, filename: str) -> bool:
    """Is this attachment a bill to read? Files from listed senders always; otherwise the subject or name must say so."""
    if not filename.lower().endswith(FILE_TYPES):
        return False
    if (sender or "").lower() in {x.strip().lower() for x in cfg["email_senders"]}:
        return True
    return bool(BILLISH.search(subject or "") or BILLISH.search(filename))


@on("email.received")
@DBOS.workflow()
async def bills_from_email(event: dict) -> None:
    await bills_from_email_step(event["org_id"], event["payload"]["message_id"])


@DBOS.step()
async def bills_from_email_step(org_id: str, message_id: str) -> int:
    """Gmail: download the bill-like attachments of a new email and file them (same checks as uploads). Returns how many."""
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode") or not cfg["email_intake"]:
            return 0
        m = (await conn.execute(text("""select m.metadata, c.subject, c.contact_id::text, c.id::text as conv, k.email
            from app.messages m join app.conversations c on c.id = m.conversation_id left join app.contacts k on k.id = c.contact_id
            where m.id = cast(:i as uuid)"""), {"i": message_id})).mappings().first()
    meta = (m or {}).get("metadata") or {}
    names = [a.get("filename", "") for a in meta.get("attachments", [])]
    gm = meta.get("gmail") or {}
    if not m or not gm.get("message_id") or not any(email_wants(cfg, m["email"] or "", m["subject"] or "", n) for n in names):
        return 0
    from agentry.connectors.gmail import Gmail, GmailError, parse_message
    from agentry.connectors.store import get_connection_for
    box = await get_connection_for(org_id, "gmail", meta.get("mailbox"))
    if not box:
        return 0
    g = Gmail(org_id, box)
    try:
        full = parse_message(await g.call("GET", f"/messages/{gm['message_id']}", params={"format": "full"}))
    except GmailError:
        return 0
    n = 0
    for a in full["attachments"]:
        if not email_wants(cfg, m["email"] or "", m["subject"] or "", a["filename"]) or not 0 < a["size"] <= documents.MAX_BYTES:
            continue
        mime = documents.mime_of(a["filename"], a["mime"])
        if not mime:
            continue
        try:
            import base64
            data = await g.call("GET", f"/messages/{gm['message_id']}/attachments/{a['attachment_id']}")
            raw = base64.urlsafe_b64decode(data["data"] + "=" * (-len(data["data"]) % 4))
            await ingest(org_id, raw, mime=mime, filename=a["filename"], source="email", contact_id=m["contact_id"], conversation_id=m["conv"])
            n += 1
        except (GmailError, documents.DocumentError, KeyError, ValueError):
            continue
    return n


# ---------- Google Sheets ----------

async def push_to_sheets(org_id: str) -> int:
    """Append every filed document not in the sheet yet. A broken connection is marked (the owner is alerted) and the
    documents wait; nothing is lost."""
    from agentry.connectors import sheets
    from agentry.connectors.store import get_connection, update_state
    conn_row = await get_connection(org_id, "google_sheets")
    if not conn_row:
        return 0
    async with tenant_session(org_id) as conn:
        docs = [dict(r) for r in (await conn.execute(text("""select id::text, fields from app.documents where status = 'ready'
            and sheet_synced_at is null order by fields->'date'->>'value', created_at limit 500"""))).mappings().all()]
    if not docs:
        return 0
    try:
        await sheets.append(org_id, conn_row, [sheets.row(d) for d in docs])
    except sheets.SheetsError as e:
        await update_state(org_id, conn_row["id"], error=str(e)[:300])
        return 0
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.documents set sheet_synced_at = now() where id = any(cast(:ids as uuid[]))"), {"ids": [d["id"] for d in docs]})
    await update_state(org_id, conn_row["id"], synced=True)
    return len(docs)


# ---------- a person checks ----------

async def review(org_id: str, did: str, *, action: str, edits: dict | None, user_id: str | None) -> dict:
    """accept (with any corrected fields: those count as checked, confidence 1) or reject. Resolves the card."""
    async with tenant_session(org_id) as conn:
        _st, cfg = await settings_of(conn)
        row = (await conn.execute(text("select status, fields, line_items from app.documents where id = cast(:i as uuid) for update"),
                                  {"i": did})).mappings().first()
        if not row:
            raise LookupError("document not found")
        if row["status"] in ("processing", "failed"):
            raise ValueError("this document wasn't read, so there's nothing to check")
        fields = dict(row["fields"])
        if action == "accept":
            raw = {k: {"value": v, "confidence": 1.0} for k, v in (edits or {}).items() if k in documents.RECEIPT_FIELDS}
            fixed = documents.normalise({**fields, **raw}, cfg["categories"])
            for k in raw:
                fixed[k]["confidence"] = 1.0
            fields = {**fixed, **{k: {**fixed[k], "checked": True} for k in raw}}
            missing = [n for n, (_t, req) in documents.RECEIPT_FIELDS.items() if req and fields[n]["value"] in (None, "")]
            if missing:
                raise ValueError(f"fill in: {', '.join(m.replace('_', ' ') for m in missing)}")
            checks = [c for c in documents.check(fields, items=row["line_items"]) if not (set(c["fields"]) & set(raw))]
            for k in raw:  # a person typed it: their value stands even if a check still doubts it
                fields[k]["confidence"] = 1.0
        status = "ready" if action == "accept" else "rejected"
        await conn.execute(text("""update app.documents set status = :s, fields = cast(:f as jsonb), reviewed_by = :u, reviewed_at = now(),
            confidence = case when :s = 'ready' then 1 else confidence end,
            checks = case when :s = 'ready' then cast(:c as jsonb) else checks end where id = cast(:i as uuid)"""),
            {"s": status, "f": json.dumps(fields), "u": user_id, "i": did, "c": json.dumps(checks if action == "accept" else [])})
        await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
            where kind = 'document_review' and status = 'pending' and payload->>'document_id' = :d"""), {"u": user_id, "d": did})
        if status == "ready":
            await budget_check(conn, org_id, fields, cfg)
    if status == "ready":
        await push_to_sheets(org_id)
    return {"status": status, "fields": fields}


@on("approval.decided")
@DBOS.workflow()
async def document_card_decided(event: dict) -> None:
    p = event["payload"]
    if p.get("kind") == "document_review" and p.get("status") in ("approved", "edited", "rejected"):
        await document_card_step(event["org_id"], p["approval_id"], p["status"])


@DBOS.step()
async def document_card_step(org_id: str, approval_id: str, status: str) -> str:
    async with tenant_session(org_id) as conn:
        did = (await conn.execute(text("select payload->>'document_id' from app.approvals where id = cast(:a as uuid)"), {"a": approval_id})).scalar_one()
    try:
        return (await review(org_id, did, action="reject" if status == "rejected" else "accept", edits=None, user_id=None))["status"]
    except ValueError:  # a required field is missing: approving can't file it; the document stays to be fixed
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.approvals set status = 'pending', decided_at = null, decided_by = null,
                title = 'Fill in the missing details: ' || title where id = cast(:a as uuid) and title not like 'Fill in%'"""), {"a": approval_id})
        return "needs_review"


# ---------- budgets and the month ----------

async def spend(conn: AsyncConnection, month: str) -> dict[str, float]:
    rows = (await conn.execute(text("""select fields->'category'->>'value' as cat, sum((fields->'total'->>'value')::numeric) as total
        from app.documents where status = 'ready' and left(fields->'date'->>'value', 7) = :m group by 1"""), {"m": month})).all()
    return {r.cat or "Other": float(r.total or 0) for r in rows}


async def budget_check(conn: AsyncConnection, org_id: str, fields: dict, cfg: dict) -> str | None:
    """Once a month per category: an alert when spending passes 80% of its budget."""
    cat, month = fields["category"]["value"], _month(fields["date"]["value"])
    budget = (cfg.get("budgets") or {}).get(cat or "")
    if not budget or not month:
        return None
    used = (await spend(conn, month)).get(cat, 0.0)
    if used < 0.8 * float(budget):
        return None
    sent = (await conn.execute(text("""select 1 from app.events where type = 'budget.alert' and payload->>'category' = :c and payload->>'month' = :m"""),
                               {"c": cat, "m": month})).first()
    if sent:
        return None
    await emit(conn, org_id, "budget.alert", {"category": cat, "month": month, "spent": round(used, 2), "budget": float(budget),
                                              "percent": round(100 * used / float(budget))})
    return cat


def _inr(v: float) -> str:
    from agentry.pulse import _money
    return _money(v)


def _prev(month: str) -> str:
    y, m = int(month[:4]), int(month[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


async def monthly(org_id: str, month: str, with_model: bool = True) -> dict:
    """The summary for `month` (YYYY-MM): numbers from code; an optional one-line observation that can't add numbers."""
    async with tenant_session(org_id) as conn:
        now, before = await spend(conn, month), await spend(conn, _prev(month))
        vendors = (await conn.execute(text("""select fields->'vendor'->>'value' as vendor, sum((fields->'total'->>'value')::numeric) as amount, count(*) as docs
            from app.documents where status = 'ready' and left(fields->'date'->>'value', 7) = :m group by 1 order by 2 desc limit 3"""), {"m": month})).all()
        waiting = (await conn.execute(text("select count(*) from app.documents where status = 'needs_review'"))).scalar_one()
        _st, cfg = await settings_of(conn)
    total, prev_total = sum(now.values()), sum(before.values())
    label = date.fromisoformat(month + "-01").strftime("%B %Y")
    lines = [f"Spent {_inr(total)} in {label}" + (f" ({'up' if total > prev_total else 'down'} from {_inr(prev_total)} the month before)." if prev_total else ".")]
    for cat, v in sorted(now.items(), key=lambda kv: -kv[1])[:5]:
        b = (cfg.get("budgets") or {}).get(cat)
        change = f", was {_inr(before[cat])}" if before.get(cat) else ""
        lines.append(f"• {cat}: {_inr(v)}" + (f" of {_inr(b)} budget" if b else "") + change)
    if vendors:
        lines.append("Top vendors: " + "; ".join(f"{r.vendor} {_inr(float(r.amount))}" for r in vendors))
    if waiting:
        lines.append(f"{waiting} document{'s' if waiting != 1 else ''} still to check.")
    observation = None
    if with_model and now:
        facts = "\n".join(lines)
        try:
            res = await complete("writer", [{"role": "user", "content": (
                "In one short sentence, the most useful observation for a small-business owner from these expense numbers. "
                "Use only these facts and no numbers that aren't in them. No greeting, no emojis.\n\n" + facts)}],
                org_id=org_id, prompt_key="bookkeeping_observation", prompt_version="v1", mock_response="")
            line = (res.text or "").strip().splitlines()[0] if (res.text or "").strip() else ""
            allowed = set(re.findall(r"\d[\d,.]*", facts))
            if line and len(line) <= 220 and all(n in allowed for n in re.findall(r"\d[\d,.]*", line)):
                observation = line
        except AllModelsFailed:
            pass
    body = "\n".join(([observation, ""] if observation else []) + lines)
    return {"month": month, "title": f"Expenses for {label}: {_inr(total)}", "body": body, "total": round(total, 2), "by_category": now,
            "previous_total": round(prev_total, 2), "waiting": waiting}


async def send_monthly(now: datetime | None = None) -> int:
    """On the 1st (IST): last month's summary to every business with bookkeeping and monthly insights on."""
    now = now or datetime.now(UTC)
    month = _prev(now.date().isoformat()[:7])
    async with system_session() as conn:
        orgs = (await conn.execute(text("""select org_id from app.automation_instances where template_key = 'bookkeeping'
            and status in ('live','approval_mode') and coalesce((config->>'monthly_insights')::boolean, true)"""))).scalars().all()
    n = 0
    for org_id in orgs:
        async with tenant_session(org_id) as conn:
            if (await conn.execute(text("select 1 from app.events where type = 'bookkeeping.monthly' and payload->>'month' = :m"), {"m": month})).first():
                continue
        s = await monthly(org_id, month)
        async with tenant_session(org_id) as conn:
            await emit(conn, org_id, "bookkeeping.monthly", {k: s[k] for k in ("month", "title", "body", "total", "waiting")})
        n += 1
    return n


@DBOS.step()
async def monthly_step() -> int:
    return await send_monthly()


@DBOS.workflow()
async def bookkeeping_monthly(scheduled_time: datetime, context) -> None:
    await monthly_step()


# ---------- export ----------

async def exportable(conn: AsyncConnection, month: str | None, include_exported: bool) -> list[dict]:
    rows = (await conn.execute(text("""select id::text, kind, fields, exported_at from app.documents where status = 'ready'
        and (cast(:m as text) is null or left(fields->'date'->>'value', 7) = :m) and (:all or exported_at is null)
        order by fields->'date'->>'value', created_at"""), {"m": month, "all": include_exported})).mappings().all()
    return [dict(r) for r in rows]


def to_csv(docs: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    cols = ["date", "vendor", "vendor_gstin", "bill_number", "category", "description", "subtotal", "cgst", "sgst", "igst", "total", "currency",
            "payment_method"]
    w.writerow([c.replace("_", " ").title().replace("Gstin", "GSTIN").replace("Cgst", "CGST").replace("Sgst", "SGST").replace("Igst", "IGST") for c in cols]
               + ["Agentry id"])
    for d in docs:
        f = d["fields"]
        w.writerow([("" if f.get(c, {}).get("value") is None else f[c]["value"]) for c in cols] + [d["id"]])
    return out.getvalue()


def to_tally(docs: list[dict], company: str) -> str:
    """Tally Prime / ERP 9 import: one Purchase voucher per bill (expense ledger = category, GST input ledgers, party =
    vendor). Ledgers that don't exist in Tally yet are created on import if 'create masters' is on, else Tally lists them."""
    def amt(v: float) -> str:
        return f"{v:.2f}"
    vouchers = []
    for d in docs:
        f = {k: v.get("value") for k, v in d["fields"].items()}
        taxes = [(name, f[k]) for k, name in (("cgst", "Input CGST"), ("sgst", "Input SGST"), ("igst", "Input IGST")) if f.get(k)]
        base = round(f["total"] - sum(v for _n, v in taxes), 2)  # never the read subtotal: the voucher must balance with the (checked) total
        entries = [f"""<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(f['vendor'])}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
<AMOUNT>{amt(f['total'])}</AMOUNT></ALLLEDGERENTRIES.LIST>""",
                   f"""<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(f.get('category') or 'Other')}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>-{amt(base)}</AMOUNT></ALLLEDGERENTRIES.LIST>"""]
        entries += [f"""<ALLLEDGERENTRIES.LIST><LEDGERNAME>{n}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>-{amt(v)}</AMOUNT></ALLLEDGERENTRIES.LIST>""" for n, v in taxes]
        vouchers.append(f"""<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Purchase" ACTION="Create">
<DATE>{f['date'].replace('-', '')}</DATE><VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
<REFERENCE>{escape(f.get('bill_number') or '')}</REFERENCE><PARTYLEDGERNAME>{escape(f['vendor'])}</PARTYLEDGERNAME>
<PARTYGSTIN>{escape(f.get('vendor_gstin') or '')}</PARTYGSTIN>
<NARRATION>{escape((f.get('description') or '') + ' [Agentry ' + d['id'][:8] + ']')}</NARRATION>
{''.join(entries)}
</VOUCHER></TALLYMESSAGE>""")
    return f"""<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>
<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>
<REQUESTDATA>
{''.join(vouchers)}
</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>
"""
