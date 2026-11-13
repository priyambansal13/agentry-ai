"""Upload hub (CA desk part 2, docs/PLAN-CA-DESK-2.md #3): a client (or staff) drops many files or a zip at once; each file
is recognised, filed on the client, ticked off the checklist it answers, and the right agent run on it.

    unpack      zips opened (folders flattened; hidden and system files skipped); limits on count, size and compression
                ratio so a zip bomb can't fill the disk
    recognise   spreadsheets and GSTR-2B JSON by their columns and title lines (code, no AI, free); PDFs and photos by the
                document chaser's reader (filename and text rules, the AI for the rest)
    same file   a file the client already sent (same SHA-256) isn't stored twice
    file        through the document chaser when it's on (matched to the checklist item, ticked), else stored with its type
    route       bank statement -> bank classifier · broker P&L -> capital gains · payments register with TDS -> TDS returns ·
                sales / purchase register, day book, ledger -> anomaly finder · GSTR-2B + purchase register in the same
                batch -> GST reconciliation · Form 16 / 16A / AIS / TIS / 26AS -> tax documents reader · notice -> notice
                handler. Only agents the firm has switched on; a failed run is reported, never blocks the rest.
The batch itself is saved as one piece of work (agent "ca_upload_hub") listing every file, what it was recognised as, the
checklist item it ticked and the work each agent produced.
"""
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import text

from agentry import audit
from agentry.automations.ca import core
from agentry.db import tenant_session

MAX_FILES = 40
MAX_TOTAL = 100 * 1024 * 1024
MAX_RATIO = 200  # uncompressed : compressed, per file in a zip
LABEL = {"bank_statement": "Bank statement", "broker_pnl": "Broker capital gains statement", "tds_register": "Payments register with TDS",
         "sales_register": "Sales register", "purchase_register": "Purchase register", "ledger": "Ledger / day book", "gstr2b": "GSTR-2B",
         "trial_balance": "Trial balance", "fixed_asset_register": "Fixed asset register", "form16": "Form 16", "form16a": "Form 16A",
         "ais": "AIS", "tis": "TIS", "26as": "Form 26AS", "notice": "Tax notice", "cas_statement": "Mutual fund statement (CAS)",
         "interest_certificate": "Interest certificate", "rent_receipt": "Rent receipt", "home_loan_certificate": "Home loan certificate",
         "insurance_receipt": "Insurance premium receipt", "investment_proof": "Investment proof", "challan": "Tax challan",
         "financial_statements": "Financial statements", "pan_aadhaar": "PAN / Aadhaar", "sale_deed": "Property deed", "other": "Not recognised"}
AGENT = {"bank_statement": "ca_bank_classifier", "broker_pnl": "ca_capital_gains", "tds_register": "ca_tds_returns",
         "sales_register": "ca_anomaly_finder", "purchase_register": "ca_anomaly_finder", "ledger": "ca_anomaly_finder",
         "form16": "ca_tax_docs_reader", "form16a": "ca_tax_docs_reader", "ais": "ca_tax_docs_reader", "tis": "ca_tax_docs_reader",
         "26as": "ca_tax_docs_reader", "notice": "ca_notice_handler"}
GATE = {"ca_anomaly_finder": "excel_desk"}  # agents that come with another switch
SHEETS = ("text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
AFTER = {"trial_balance": "kept on the client for the financial statements agent", "gstr2b": "kept; reconciled when a purchase register comes in"}


class HubError(core.CaError):
    pass


# ---------- unpack ----------

def unpack(uploads: list[tuple[bytes, str | None, str | None]]) -> tuple[list[tuple[bytes, str, str | None]], list[dict]]:
    """(files, skipped). Zips are opened one level deep; everything is checked against the batch limits."""
    out: list[tuple[bytes, str, str | None]] = []
    skipped: list[dict] = []
    total = 0

    def take(data: bytes, name: str, ctype: str | None) -> None:
        nonlocal total
        if len(out) >= MAX_FILES:
            skipped.append({"filename": name, "why": f"more than {MAX_FILES} files in one go: send the rest separately"})
        elif total + len(data) > MAX_TOTAL:
            skipped.append({"filename": name, "why": "the batch is over 100 MB: send the rest separately"})
        else:
            total += len(data)
            out.append((data, name, ctype))

    for data, name, ctype in uploads:
        name = name or "file"
        if name.lower().endswith(".zip") or ctype in ("application/zip", "application/x-zip-compressed") or data[:4] == b"PK\x03\x04" and not name.lower().endswith(".xlsx"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                skipped.append({"filename": name, "why": "this zip can't be opened"})
                continue
            for info in z.infolist():
                inner = PurePosixPath(info.filename)
                if info.is_dir() or inner.name.startswith((".", "~$")) or "__MACOSX" in inner.parts or inner.name.lower() in ("thumbs.db", "desktop.ini"):
                    continue
                if info.flag_bits & 0x1:
                    skipped.append({"filename": inner.name, "why": "password-protected inside the zip: send it on its own"})
                elif info.file_size > core.MAX_FILE:
                    skipped.append({"filename": inner.name, "why": "over 20 MB"})
                elif info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                    skipped.append({"filename": inner.name, "why": "compressed too much to be a real document"})
                elif inner.suffix.lower() == ".zip":
                    skipped.append({"filename": inner.name, "why": "a zip inside a zip: send it on its own"})
                else:
                    take(z.read(info), inner.name, None)
        else:
            take(data, name, ctype)
    return out, skipped


# ---------- recognise ----------

def _head(rows: list[list[str]]) -> tuple[str, str]:
    """(the title lines above the header, the header) in lower case."""
    from agentry.automations.ca import cleaner
    hi, head = cleaner.find_header(rows)
    return " ".join(" ".join(r) for r in rows[:hi]).lower(), " | ".join(head).lower()


def sniff(data: bytes, mime: str, filename: str | None = None) -> str | None:
    """What a spreadsheet or JSON is from its columns, title lines and name; None when it can't tell (the chaser's reader
    decides)."""
    name = (filename or "").lower()
    if mime == "application/json" or data[:1] == b"{":
        try:
            j = json.loads(data.decode("utf-8-sig"))
        except ValueError:
            return None
        s = json.dumps(j)[:20000].lower()
        if '"b2b"' in s and ('"ctin"' in s or '"rtnprd"' in s):
            return "gstr2b"
        if "annual information statement" in s or '"tds_tcs' in s:
            return "ais"
        return None
    if mime not in SHEETS:
        return None
    try:
        rows = core.table_rows(data, mime)[:80]
    except core.CaError:
        return None
    if not rows:
        return None
    title, head = _head(rows)
    both = f"{name} {title} {head}"
    has = lambda rx: bool(re.search(rx, head))
    if has(r"narration|description|particulars|remarks") and has(r"withdrawal|debit|dr\b") and has(r"deposit|credit|cr\b") and has(r"balance"):
        return "bank_statement"
    if has(r"symbol|scrip|isin|security|scheme") and has(r"buy|purchase|entry") and has(r"sell|sale|exit|redemption"):
        return "broker_pnl"
    if has(r"\bsection\b") and has(r"tds|tax deducted") and has(r"\bpan\b|deductee"):
        return "tds_register"
    if has(r"asset") and has(r"depreciation|wdv|written down|put to use|useful life|block"):
        return "fixed_asset_register"
    if has(r"ledger|account|particulars|head") and has(r"debit|dr\b") and has(r"credit|cr\b") and not has(r"\bdate\b|voucher|vch"):
        return "trial_balance"
    if re.search(r"trial balance", both) and has(r"debit|dr\b|closing"):
        return "trial_balance"
    register = has(r"gstin|invoice|bill|voucher|taxable|amount")
    if register and (re.search(r"purchase|inward", both) or has(r"supplier|vendor")):
        return "purchase_register"
    if register and (re.search(r"sales|outward", both) or has(r"customer|buyer|recipient")):
        return "sales_register"
    if re.search(r"day ?book|ledger|journal|cash ?book", both) or (has(r"\bdate\b") and has(r"debit|dr\b") and has(r"credit|cr\b")):
        return "ledger"
    return None


# ---------- route ----------

async def _run_agent(conn, org_id: str, client: dict, agent: str, data: bytes, mime: str, fid: str, title: str, user_id: str | None) -> dict:
    """Run one agent on one stored file; returns {"agent", "work_id"} (or the notice / reader result)."""
    from agentry.automations.ca import anomalies, bank, capgains, notices, taxdocs, tds
    if agent == "ca_tax_docs_reader":
        await taxdocs.read_file(org_id, fid)
        return {"agent": agent, "work_id": None, "note": "read: figures on the client's tax documents"}
    if agent == "ca_notice_handler":
        r = await notices.handle(org_id, client["id"], fid, user_id)
        return {"agent": agent, "work_id": r.get("id") or r.get("work_id"), "note": "explained, reply drafted, card on the board"}
    if agent == "ca_bank_classifier":
        cfg = await core.enabled(conn, "ca_bank_classifier") or {}
        result = await bank.run(org_id, conn, data, mime, bool(cfg.get("use_model", True)))
    elif agent == "ca_capital_gains":
        result = capgains.compute(data, mime)
    elif agent == "ca_tds_returns":
        result = tds.compute(data, mime)
    elif agent == "ca_anomaly_finder":
        result = anomalies.compute(data, mime, firm_gstin=client.get("gstin"))
    else:
        raise HubError(f"no runner for {agent}")
    wid = await core.save_work(conn, org_id, client["id"], agent, title, result, file_ids=[fid], params={"from": "upload_hub"}, user_id=user_id)
    return {"agent": agent, "work_id": wid}


async def _gst(conn, org_id: str, client: dict, two_b: dict, books: dict, user_id: str | None) -> dict:
    from agentry.automations.ca import gst
    cfg = await core.enabled(conn, "ca_gst_reconciliation") or {}
    r = gst.reconcile(gst.records(two_b["data"], two_b["mime"]), gst.records(books["data"], books["mime"]), float(cfg.get("tolerance", 10)))
    period = _period(two_b["data"]) or f"uploaded {datetime.now(UTC):%d %b %Y}"
    r["messages"] = gst.supplier_messages(r, client["name"], client["gstin"], period)
    wid = await core.save_work(conn, org_id, client["id"], "ca_gst_reconciliation", f"GST reconciliation {period}", r,
                               file_ids=[two_b["file_id"], books["file_id"]], params={"period": period, "from": "upload_hub"}, user_id=user_id)
    return {"agent": "ca_gst_reconciliation", "work_id": wid}


def _period(data: bytes) -> str | None:
    m = re.search(rb'"rtnprd"\s*:\s*"(\d{2})(\d{4})"', data[:4000])
    return datetime(int(m[2]), int(m[1]), 1).strftime("%b %Y") if m and 1 <= int(m[1]) <= 12 else None


async def process(org_id: str, client_id: str, uploads: list[tuple[bytes, str | None, str | None]], *, source: str = "portal",
                  user_id: str | None = None, actor_type: str = "user", filing_id: str | None = None) -> dict:
    """The whole batch: unpack, recognise, file, tick, route. Returns the saved batch (also stored as ca_work)."""
    from agentry.automations.ca import chaser
    from agentry.features import enabled_automations
    files, skipped = unpack(uploads)
    if not files and not skipped:
        raise HubError("no files")
    async with tenant_session(org_id) as conn:
        client = (await conn.execute(text("select id::text, name, pan, gstin from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).mappings().first()
        if not client:
            raise HubError("client not found")
        client = dict(client)
        on = set(await enabled_automations(conn))
        have = {r[0]: r[1] for r in (await conn.execute(text("select sha256, filename from app.ca_files where client_id = cast(:c as uuid)"), {"c": client_id})).all()}
    out: list[dict] = []
    stored: list[dict] = []
    for data, name, ctype in files:
        row: dict = {"filename": name}
        mime = core.mime_of(name, ctype)
        sha = hashlib.sha256(data).hexdigest()
        if not mime:
            out.append(row | {"status": "skipped", "why": "not a PDF, photo, CSV, Excel (.xlsx), JSON or text file"})
            continue
        if sha in have:
            out.append(row | {"status": "duplicate", "why": f"already on the client's file as {have[sha]}"})
            continue
        have[sha] = name
        doc_type = sniff(data, mime, name)
        try:
            if "ca_document_chaser" in on:
                r = await chaser.receive(org_id, client_id, data, mime=mime, filename=name, source=source, filing_id=filing_id,
                                         user_id=user_id, doc_type=doc_type)
                fid, doc_type, item = r["file_id"], r.get("doc_type") or doc_type, r.get("item")
                row["ticked"] = chaser.ITEMS[item][0] if item in chaser.ITEMS else None
            else:
                async with tenant_session(org_id) as conn:
                    fid = await core.store_file(conn, org_id, client_id, data, filename=name, mime=mime, source=source, doc_type=doc_type, user_id=user_id)
        except core.CaError as e:
            out.append(row | {"status": "error", "why": str(e)})
            continue
        doc_type = doc_type or "other"
        row |= {"status": "filed", "file_id": fid, "doc_type": doc_type, "recognised": LABEL.get(doc_type, doc_type.replace("_", " ").capitalize())}
        stored.append({"row": row, "data": data, "mime": mime, "file_id": fid, "doc_type": doc_type})
        out.append(row)

    # GSTR-2B with a purchase register in the same batch -> GST reconciliation (instead of the anomaly finder for that register)
    two_b = next((s for s in stored if s["doc_type"] == "gstr2b"), None)
    books = next((s for s in stored if s["doc_type"] == "purchase_register"), None)
    if two_b and books and "ca_gst_reconciliation" in on:
        try:
            async with tenant_session(org_id) as conn:
                ran = await _gst(conn, org_id, client, two_b, books, user_id)
            for s in (two_b, books):
                s["row"]["ran"] = ran
                s["done"] = True
        except (core.CaError, ValueError, KeyError, IndexError) as e:
            two_b["row"]["agent_error"] = books["row"]["agent_error"] = f"GST reconciliation: {e}"
    for s in stored:
        if s.get("done"):
            continue
        agent = AGENT.get(s["doc_type"])
        if not agent:
            if s["doc_type"] in AFTER:
                s["row"]["next"] = AFTER[s["doc_type"]]
            continue
        if GATE.get(agent, agent) not in on:
            s["row"]["next"] = "the agent for this isn't switched on"
            continue
        try:
            async with tenant_session(org_id) as conn:
                s["row"]["ran"] = await _run_agent(conn, org_id, client, agent, s["data"], s["mime"], s["file_id"],
                                                   f"{LABEL.get(s['doc_type'], s['doc_type'])}: {s['row']['filename']}", user_id)
        except (core.CaError, ValueError, KeyError, IndexError) as e:
            s["row"]["agent_error"] = str(e) or "couldn't be read"

    out += [{"filename": s["filename"], "status": "skipped", "why": s["why"]} for s in skipped]
    summary = {"files": len(out), "filed": sum(1 for r in out if r["status"] == "filed"), "ticked": sum(1 for r in out if r.get("ticked")),
               "agents": sum(1 for r in out if r.get("ran")), "duplicates": sum(1 for r in out if r["status"] == "duplicate"),
               "problems": sum(1 for r in out if r["status"] in ("skipped", "error") or r.get("agent_error"))}
    result = {"files": out, "summary": summary, "source": source}
    async with tenant_session(org_id) as conn:
        wid = await core.save_work(conn, org_id, client_id, "ca_upload_hub", f"{summary['files']} files received", result,
                                   file_ids=[s["file_id"] for s in stored], params={"source": source}, user_id=user_id)
        await audit.record(conn, org_id=org_id, actor_type=actor_type, actor_user_id=user_id, action="ca_upload_hub.run",
                           target_type="ca_work", target_id=wid, metadata=summary)
    return {"id": wid, **result}


def sheet(result: dict) -> bytes:
    return core.xlsx_bytes({"Files": [["File", "Status", "Recognised as", "Checklist item ticked", "Agent run", "Note"],
                                      *[[r["filename"], r["status"], r.get("recognised"), r.get("ticked"), (r.get("ran") or {}).get("agent"),
                                         r.get("why") or r.get("agent_error") or r.get("next") or (r.get("ran") or {}).get("note")] for r in result["files"]]]})


SAMPLE_FILES = {  # name in the zip -> sample file
    "HDFC statement Oct.csv": "bank_statement_sample.csv", "Zerodha tax P&L FY25-26.csv": "broker_pnl_sample.csv",
    "Purchases Oct.csv": "purchase_register_sample.csv", "GSTR2B_Oct2026.json": "gstr2b_sample.json",
    "TDS payments Q2.csv": "tds_register_sample.csv", "Day book Apr-Oct.csv": "purchase_daybook_sample.csv",
    "Form16.txt": "form16_sample.txt", "AIS.txt": "ais_sample.txt", "IT notice.txt": "notice_143_1_sample.txt",
}


def sample_zip() -> bytes:
    from agentry.automations.ca.taxdocs import SAMPLES
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in SAMPLE_FILES.items():
            z.writestr(f"Mehta docs/{name}", (SAMPLES / src).read_bytes())
        z.writestr("__MACOSX/._Form16.txt", b"junk")
    return buf.getvalue()


AGENT_LABEL = {"ca_bank_classifier": "Bank statement classifier", "ca_capital_gains": "Capital gains", "ca_tds_returns": "TDS returns",
               "ca_anomaly_finder": "Anomaly finder", "ca_tax_docs_reader": "Tax documents reader", "ca_notice_handler": "Notice handler",
               "ca_gst_reconciliation": "GST reconciliation"}


def preview(uploads: list[tuple[bytes, str | None, str | None]]) -> dict:
    """What the hub would do with these files, without storing anything or calling a model (the website's try-it box):
    spreadsheets by their columns, other files by the chaser's name-and-text rules."""
    from agentry.automations.ca import chaser
    files, skipped = unpack(uploads)
    out = []
    for data, name, ctype in files:
        mime = core.mime_of(name, ctype)
        if not mime:
            out.append({"filename": name, "recognised": None, "agent": None, "why": "not a document type we take"})
            continue
        t = sniff(data, mime, name)
        if not t:
            try:
                txt = core.text_of(data, mime, 4000)
            except core.CaError:
                txt = None
            t = chaser._guess(name, txt, [])["doc_type"]
        out.append({"filename": name, "doc_type": t, "recognised": LABEL.get(t, t), "agent": AGENT.get(t), "next": AFTER.get(t)})
    pair = [next((f for f in out if f.get("doc_type") == t), None) for t in ("gstr2b", "purchase_register")]
    if all(pair):  # the 2B and the first purchase register go to GST reconciliation together
        for f in pair:
            f["agent"], f["next"] = "ca_gst_reconciliation", None
    for f in out:
        f["agent_label"] = AGENT_LABEL.get(f["agent"]) if f.get("agent") else None
    return {"files": out, "skipped": skipped}
