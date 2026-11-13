"""Document chaser (CA Firm pack): a checklist per filing, polite reminders until every document is in.

    checklist  built from the filing type and the client's profile (salaried -> Form 16, pays rent -> rent receipts,
               sold shares -> capital gains statement…); the firm can add, tick off or drop items on the filing
    intake     a client sends a PDF or photo on WhatsApp (or the firm uploads it): it's read, matched to the item it
               answers, filed against the filing, and the client is told what's still needed
    reminders  every N days (settings) while items are missing: WhatsApp inside the 24-hour window, else the approved
               template, else Telegram, else email; at most M reminders, then a Needs-you card for a person to call
    done       when nothing is missing the card moves to In preparation and the firm gets a card
"""
import base64
import json
import re
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.db import tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


class ChaserConfig(BaseModel):
    every_days: int = Field(3, ge=1, le=14, title="Remind clients every (days)", json_schema_extra={"editable_by": "client"})
    max_reminders: int = Field(5, ge=1, le=15, title="Stop after this many reminders (then a person calls)",
                               json_schema_extra={"editable_by": "client"})
    whatsapp_template: str | None = Field(None, title="Approved WhatsApp template for reminders",
                                          description="Needed to message a client who hasn't written in the last 24 hours. One "
                                                      "parameter: the list of documents.", json_schema_extra={"editable_by": "agentry"})
    take_from_whatsapp: bool = Field(True, title="Take documents clients send on WhatsApp", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_document_chaser", name="Document chaser",
    description="A checklist per client per filing; WhatsApp and email reminders until every document is in.",
    config_model=ChaserConfig, metrics=("documents_collected",),
))

ITEMS = {  # key -> (label, doc types that answer it)
    "form16": ("Form 16 from your employer", ("form16",)),
    "bank_statements": ("Bank statements for the year (all accounts)", ("bank_statement", "interest_certificate")),
    "interest_certificates": ("Interest certificates for FDs and savings", ("interest_certificate", "bank_statement")),
    "rent_receipts": ("Rent receipts and your landlord's PAN (for HRA)", ("rent_receipt",)),
    "home_loan": ("Home loan interest certificate", ("home_loan_certificate",)),
    "rent_received": ("Rent received on your property (amount and tenant)", ("other",)),
    "capital_gains": ("Capital gains statement (broker tax P&L, CAMS or KFintech)", ("broker_pnl", "cas_statement")),
    "property_sale": ("Sale and purchase deeds of property sold", ("sale_deed",)),
    "proofs_80c": ("80C proofs (LIC, PPF, ELSS, tuition fees, home loan principal)", ("investment_proof", "insurance_receipt")),
    "proofs_80d": ("Health insurance premium receipt (80D)", ("insurance_receipt",)),
    "books": ("Books of accounts or profit & loss for the year", ("financial_statements", "trial_balance", "ledger")),
    "foreign": ("Foreign income and foreign assets details", ("other",)),
    "financials": ("Audited financial statements", ("financial_statements",)),
    "tds_certificates": ("TDS certificates (Form 16A) received", ("form16a",)),
    "sales_register": ("Sales invoices / sales register for the period", ("sales_register",)),
    "purchase_register": ("Purchase bills / purchase register for the period", ("purchase_register", "gstr2b")),
    "payments_register": ("Salary and vendor payments with TDS for the quarter", ("tds_register", "other")),
    "challans": ("TDS challans paid", ("challan",)),
    "trial_balance": ("Trial balance and ledgers", ("trial_balance", "ledger", "financial_statements")),
    "fixed_assets": ("Fixed asset register (additions and sales)", ("fixed_asset_register", "other")),
    "loan_confirmations": ("Loan confirmations from lenders", ("other",)),
    "board_resolution": ("Signed financials and AGM / board resolution details", ("financial_statements",)),
    "director_kyc": ("Director's PAN, Aadhaar, mobile and email (for the OTP)", ("pan_aadhaar",)),
    "notice": ("The notice and any earlier replies", ("notice",)),
    "income_estimate": ("Estimate of this year's income (salary, interest, gains)", ("other",)),
}


def checklist_for(kind: str, profile: dict, client_kind: str = "individual") -> list[dict]:
    p = profile or {}
    keys: list[str] = []
    if kind == "itr" and client_kind in ("individual", "huf"):
        keys = ["bank_statements"]
        keys += ["form16"] if p.get("salaried") else []
        keys += ["rent_receipts"] if p.get("rent_paid") else []
        keys += ["home_loan", "rent_received"] if p.get("house_property") else []
        keys += ["capital_gains"] if p.get("capital_gains") else []
        keys += ["proofs_80c", "proofs_80d"] if p.get("deductions") else []
        keys += ["books"] if p.get("business") else []
        keys += ["foreign"] if p.get("foreign") else []
        keys += ["interest_certificates"]
    elif kind == "itr":
        keys = ["financials" if p.get("audit") else "books", "bank_statements", "tds_certificates"]
    elif kind in ("gstr1",):
        keys = ["sales_register"]
    elif kind in ("gstr3b", "gstr9"):
        keys = ["sales_register", "purchase_register"]
    elif kind in ("tds_24q", "tds_26q"):
        keys = ["payments_register", "challans"]
    elif kind == "tax_audit":
        keys = ["trial_balance", "bank_statements", "fixed_assets", "loan_confirmations"]
    elif kind in ("roc_aoc4", "roc_mgt7"):
        keys = ["board_resolution"]
    elif kind == "dir3_kyc":
        keys = ["director_kyc"]
    elif kind == "notice_reply":
        keys = ["notice"]
    elif kind == "advance_tax":
        keys = ["income_estimate"]
    return [{"key": k, "label": ITEMS[k][0], "status": "missing", "file_ids": [], "received_at": None} for k in dict.fromkeys(keys)]


def missing(checklist: list[dict]) -> list[dict]:
    return [i for i in checklist or [] if i.get("status") == "missing"]


async def set_item(conn: AsyncConnection, org_id: str, filing_id: str, key: str, status: str, *, file_id: str | None = None,
                   label: str | None = None) -> dict:
    """Mark a checklist item received / missing / not needed, or add a new one (label). When nothing is missing any
    more, a card waiting for documents moves to In preparation."""
    from agentry.automations.ca.tracker import update_filing
    f = (await conn.execute(text("select checklist, status, title, client_id::text from app.ca_filings where id = cast(:i as uuid) for update"),
                            {"i": filing_id})).mappings().first()
    if not f:
        raise core.CaError("filing not found")
    if status not in ("missing", "received", "not_needed"):
        raise core.CaError("unknown status")
    items = list(f["checklist"] or [])
    item = next((i for i in items if i["key"] == key), None)
    if not item:
        if not label:
            raise core.CaError("no such item on this checklist")
        item = {"key": key, "label": label.strip()[:120], "status": "missing", "file_ids": [], "received_at": None}
        items.append(item)
    was = item["status"]
    item["status"] = status
    if file_id:
        item["file_ids"] = [*item.get("file_ids", []), file_id]
    if status == "received" and was != "received":
        item["received_at"] = datetime.now(UTC).isoformat()
        await emit(conn, org_id, "ca.document_received", {"filing_id": filing_id, "item": key, "file_id": file_id})
    await conn.execute(text("update app.ca_filings set checklist = cast(:c as jsonb), updated_at = now() where id = cast(:i as uuid)"),
                       {"c": json.dumps(items), "i": filing_id})
    complete_now = not missing(items) and f["status"] == "docs_pending" and any(i["status"] == "received" for i in items)
    if complete_now:
        await update_filing(conn, org_id, filing_id, {"status": "in_prep"}, user_id=None, actor_type="agent")
        client = (await conn.execute(text("select name from app.ca_clients where id = cast(:c as uuid)"), {"c": f["client_id"]})).scalar_one()
        await core.card(conn, org_id, "ca_document_chaser", f"{client}: every document for {f['title']} is in",
                        "The card moved to In preparation.", {"key": f"docs_in:{filing_id}", "filing_id": filing_id})
    return {"checklist": items, "complete": complete_now}


# ---------- intake ----------

def _guess(filename: str | None, text_: str | None, wanted: list[dict]) -> dict:
    """What the file is from its name and text, without a model (also the test mock)."""
    s = f"{filename or ''} {(text_ or '')[:3000]}".lower()
    rules = [("notice", r"notice u/s|section 143|section 139\(9\)|section 148|intimation u/s"),  # a notice quotes 26AS / Form 16: first
             ("form16", r"form[\s_-]*16(?!a)|form no\.?\s*16"), ("form16a", r"form[\s_-]*16a"), ("26as", r"26as|annual tax statement"),
             ("ais", r"\bais\b|annual information statement"), ("bank_statement", r"statement of account|bank statement|account statement"),
             ("interest_certificate", r"interest certificate"), ("broker_pnl", r"tax p&?l|tradewise|capital gains?"),
             ("cas_statement", r"cams|kfintech|consolidated account statement"), ("rent_receipt", r"rent receipt"),
             ("home_loan_certificate", r"home loan|housing loan"), ("insurance_receipt", r"premium|insurance|mediclaim"),
             ("investment_proof", r"\bppf\b|\belss\b|tuition|80c"),
             ("challan", r"challan|itns ?281"), ("sales_register", r"sales register|sales invoices"), ("purchase_register", r"purchase register"),
             ("gstr2b", r"gstr[\s_-]*2b"), ("trial_balance", r"trial[\s_-]*balance"), ("fixed_asset_register", r"fixed[\s_-]*asset"),
             ("tds_register", r"tds[\s_-]*register|payments? register"), ("ledger", r"day[\s_-]*book|ledger")]
    doc_type = next((t for t, rx in rules if re.search(rx, s)), "other")
    item = next((i["key"] for i in wanted if doc_type in ITEMS.get(i["key"], ("", ()))[1]), "other")
    return {"item": item, "doc_type": doc_type, "label": doc_type.replace("_", " "), "confidence": 0.9 if doc_type != "other" else 0.3}


async def classify(org_id: str, data: bytes, mime: str, filename: str | None, wanted: list[dict]) -> dict:
    txt = None
    try:
        txt = core.text_of(data, mime, 6000)
    except core.CaError:
        txt = None
    guess = _guess(filename, txt, wanted)
    prompt = load("ca_document_classify")
    items = "\n".join(f"- {i['key']}: {i['label']}" for i in wanted) or "- (nothing: the checklist is complete)"
    messages = prompt.render(items=items, filename=filename or "(none)", text=f"The file's text:\n{txt}" if txt else "The file is attached as an image.")
    if not txt and mime.startswith("image/"):
        messages[-1] = {"role": "user", "content": [{"type": "text", "text": messages[-1]["content"]},
                                                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}]}
    try:
        res = await complete(prompt.tier, messages, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(guess), temperature=0)
        out = res.data if isinstance(res.data, dict) else guess
    except AllModelsFailed:
        out = guess
    if out.get("item") not in {i["key"] for i in wanted}:
        out["item"] = "other"
    return out


def _known(doc_type: str, wanted: list[dict]) -> dict:
    """The classification for a file whose type is already known (a spreadsheet recognised by its columns): no model call."""
    item = next((i["key"] for i in wanted if doc_type in ITEMS.get(i["key"], ("", ()))[1]), "other")
    return {"item": item, "doc_type": doc_type, "label": doc_type.replace("_", " "), "confidence": 0.95}


async def receive(org_id: str, client_id: str, data: bytes, *, mime: str | None, filename: str | None, source: str,
                  filing_id: str | None = None, user_id: str | None = None, doc_type: str | None = None) -> dict:
    """A file from a client: stored, matched to the checklist item it answers (on the given filing, else the oldest
    filing still waiting for documents), and that item ticked off when the match is confident."""
    mime = core.mime_of(filename, mime)
    if not mime:
        raise core.CaError("send a PDF, photo, CSV or Excel file")
    async with tenant_session(org_id) as conn:
        q = "select id::text, title, checklist from app.ca_filings where client_id = cast(:c as uuid) and status = 'docs_pending'"
        filings = (await conn.execute(text(q + (" and id = cast(:f as uuid)" if filing_id else "") + " order by due_on nulls last, created_at"),
                                      {"c": client_id, "f": filing_id})).mappings().all()
    wanted = [dict(i, filing=f["id"]) for f in filings for i in missing(f["checklist"])]
    c = _known(doc_type, wanted) if doc_type else await classify(org_id, data, mime, filename, wanted)
    match = next((i for i in wanted if i["key"] == c["item"]), None) if c.get("confidence", 0) >= 0.6 else None
    target = match["filing"] if match else (filing_id or (filings[0]["id"] if filings else None))
    async with tenant_session(org_id) as conn:
        fid = await core.store_file(conn, org_id, client_id, data, filename=filename, mime=mime, source=source, filing_id=target,
                                    item_key=match["key"] if match else None, doc_type=c.get("doc_type"), user_id=user_id)
        result = {"file_id": fid, "doc_type": c.get("doc_type"), "label": c.get("label"), "item": match["key"] if match else None,
                  "filing_id": target, "complete": False}
        if match:
            r = await set_item(conn, org_id, match["filing"], match["key"], "received", file_id=fid)
            result["complete"] = r["complete"]
            result["still_missing"] = [i["label"] for i in missing(r["checklist"])]
        else:
            result["still_missing"] = [i["label"] for i in wanted]
            if filings:
                name = (await conn.execute(text("select name from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).scalar_one()
                await core.card(conn, org_id, "ca_document_chaser", f"{name} sent a file we couldn't match",
                                f"{filename or 'A file'} ({c.get('label') or 'unknown'}). Open the client's file and tick the item it answers.",
                                {"key": f"unmatched:{fid}", "file_id": fid, "client_id": client_id})
    return result


def reply_for(r: dict) -> str:
    got = f"Thank you, we've received your {r['label']}." if r.get("item") else "Thank you, we've received your file; the team will check it."
    if r.get("complete"):
        return got + " That's everything we need for now: we'll start preparing your filing and keep you posted."
    if r.get("still_missing"):
        return got + "\n\nStill needed:\n" + "\n".join(f"• {m}" for m in r["still_missing"]) + "\n\nYou can send them here as photos or PDFs."
    return got


async def take_from_whatsapp(org_id: str, conversation_id: str, payload: dict) -> bool:
    """A PDF or photo on WhatsApp from one of the firm's clients: it's a document for their filing. False = not ours."""
    async with tenant_session(org_id) as conn:
        cfg = await core.enabled(conn, "ca_document_chaser")
        if not cfg or cfg["status"] not in ("live", "approval_mode") or not cfg.get("take_from_whatsapp", True):
            return False
        client = await core.client_by_phone(conn, payload.get("wa_id"))
    media = payload.get("media") or {}
    if not client or not media.get("id"):
        return False
    from agentry.connectors.whatsapp import download_media, send_text
    data, mime = await download_media(org_id, media["id"])
    try:
        r = await receive(org_id, client["id"], data, mime=mime, filename=media.get("filename"), source="whatsapp")
        body = reply_for(r)
    except core.CaError as e:
        body = f"Sorry, we couldn't take that file: {e}."
    mid = await send_text(org_id, payload["wa_id"], body)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb))"""),
            {"o": org_id, "c": conversation_id, "b": body, "m": json.dumps({"external_id": f"wa:{mid}", "sent_from": "ca_document_chaser"})})
    return True


# ---------- reminders ----------

def reminder_text(name: str, title: str, items: list[str], firm: str, n: int) -> str:
    first = (name or "").split()[0] if name else ""
    opener = f"Hi {first}," if first else "Hello,"
    lead = (f"for your {title} we still need:" if n == 0 else f"a gentle reminder: for your {title} we're still waiting for:")
    return f"{opener} {lead}\n" + "\n".join(f"• {i}" for i in items) + \
        f"\n\nYou can reply here with photos or PDFs. Thank you!\n{firm}"


async def send_reminders(org_id: str, now: datetime | None = None) -> int:
    from agentry.outbound import reach_contact
    now = now or datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        cfg = await core.enabled(conn, "ca_document_chaser")
        if not cfg or cfg["status"] not in ("live", "approval_mode"):
            return 0
        every, most = int(cfg.get("every_days", 3)), int(cfg.get("max_reminders", 5))
        firm = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        rows = (await conn.execute(text("""select f.id::text, f.title, f.checklist, f.chase, f.client_id::text, c.name from app.ca_filings f
            join app.ca_clients c on c.id = f.client_id where f.status = 'docs_pending' and coalesce((f.chase->>'paused')::boolean, false) = false
            order by f.due_on nulls last"""))).mappings().all()
        sent = 0
        for r in rows:
            items = [i["label"] for i in missing(r["checklist"])]
            chase = dict(r["chase"] or {})
            n = int(chase.get("sent", 0))
            last = datetime.fromisoformat(chase["last_at"]) if chase.get("last_at") else None
            if not items or (last and now - last < timedelta(days=every) - timedelta(hours=1)):
                continue
            if n >= most:
                await core.card(conn, org_id, "ca_document_chaser", f"{r['name']} hasn't sent documents after {n} reminders",
                                f"{r['title']}: still waiting for {', '.join(items)}. A call usually helps.",
                                {"key": f"chase_out:{r['id']}", "filing_id": r["id"]})
                continue
            if cfg["status"] != "live":
                continue  # approval mode: the firm sees what's missing on the board; nothing goes out by itself
            who = await core.who(conn, r["client_id"])
            body = reminder_text(r["name"], r["title"], items, firm, n)
            res = await reach_contact(conn, org_id, who, body, agent="ca_document_chaser", subject=f"Documents for your {r['title']}",
                                      email_ref=f"ca-chase:{r['id']}", wa_template=cfg.get("whatsapp_template"),
                                      wa_params=["; ".join(items)])
            if res["status"] in ("sent", "recorded"):
                chase.update(sent=n + 1, last_at=now.isoformat(), last_channel=res["channel"])
                await conn.execute(text("update app.ca_filings set chase = cast(:c as jsonb) where id = cast(:i as uuid)"),
                                   {"c": json.dumps(chase), "i": r["id"]})
                sent += 1
    return sent


def today() -> date:
    return datetime.now(UTC).date()
