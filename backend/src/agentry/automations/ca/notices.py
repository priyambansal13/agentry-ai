"""Notice handler (CA Firm pack): an income-tax or GST notice -> what it is, by when, how much, a draft reply.

    read     the notice (PDF, photo or text): section, assessment year, DIN, dates, demand, why it was sent, what to do,
             documents needed and a draft reply; each date, amount and DIN must appear in the notice's own text (a value
             that doesn't is dropped and flagged, never guessed)
    track    a "Notice reply" card on the filing board, due on the respond-by date, with the documents to collect as its
             checklist (the document chaser asks the client for them); a Needs-you card for the firm
The CA reviews and submits the reply on the portal.
"""
import base64
import json
import re
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.automations.ca.taxdocs import _samples
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


class NoticeConfig(BaseModel):
    days_before: int = Field(5, ge=0, le=30, title="Plan to reply this many days before the deadline",
                             description="The board card's due date is set this much earlier than the notice's.",
                             json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_notice_handler", name="Notice handler",
    description="Income-tax notices explained, the difference computed and a reply drafted.",
    config_model=NoticeConfig, metrics=(),
))


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _date_in(d: date, body: str) -> bool:
    forms = {d.strftime(f) for f in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%d/%m/%y")}
    low = body.lower()
    return any(f.lower() in low for f in forms)


def verify(raw: dict, body: str | None) -> tuple[dict, list[str]]:
    """Keep only what the notice's text supports (when there is text to check)."""
    out, flags = dict(raw), []
    if body is None:
        return out, ["The notice was a photo: check the dates, amount and DIN against it."]
    for k in ("issued_on", "respond_by"):
        d = core.parse_date(out.get(k))
        if out.get(k) and (not d or not _date_in(d, body)):
            flags.append(f"The {k.replace('_', ' ')} date read ({out[k]}) isn't in the notice: check it.")
            out[k] = None
    if out.get("din") and _digits(out["din"]) not in _digits(body):
        flags.append("The DIN read isn't in the notice: check it.")
        out["din"] = None
    demand = core.money(out.get("demand")) or 0
    if demand and not any(abs((core.money(m) or 0) - demand) < 1 for m in re.findall(r"\d[\d,]*(?:\.\d+)?", body)):
        flags.append(f"The demand read ({core.inr(demand)}) isn't in the notice: check it.")
        out["demand"] = 0
    out["quotes"] = [q for q in out.get("quotes") or [] if re.sub(r"\s+", " ", q).strip().lower() in re.sub(r"\s+", " ", body).lower()]
    return out, flags


async def read(org_id: str, client: dict, data: bytes, mime: str, filename: str | None) -> dict:
    body = core.text_of(data, mime, 30000)
    prompt = load("ca_notice")
    messages = prompt.render(client=client["name"], pan=client.get("pan") or "unknown", filename=filename or "",
                             text=f"The notice's text:\n{body}" if body else "The notice is attached as an image.")
    if not body:
        if not mime.startswith("image/"):
            raise core.CaError("this notice has no text to read: upload the PDF with text or a clear photo")
        messages[-1] = {"role": "user", "content": [{"type": "text", "text": messages[-1]["content"]},
                                                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}]}
    mock = _samples().get(filename or "") or {"authority": "other", "summary": "A notice", "what_to_do": [], "documents_needed": [], "draft_reply": ""}
    try:
        res = await complete("vision" if not body else prompt.tier, messages, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version,
                             json_output=True, mock_response=json.dumps(mock), temperature=0)
    except AllModelsFailed as e:
        raise core.CaError("the reading service is busy: try again in a minute") from e
    raw = res.data if isinstance(res.data, dict) else {}
    out, flags = verify(raw, body)
    return {**{k: out.get(k) for k in ("authority", "section", "assessment_year", "din", "issued_on", "respond_by", "demand", "summary", "why",
                                       "what_to_do", "documents_needed", "draft_reply", "quotes")}, "flags": flags}


async def handle(org_id: str, client_id: str, file_id: str, user_id: str | None) -> dict:
    """Read the notice, record it, and put a reply card on the board."""
    from agentry.automations.ca import chaser
    from agentry.automations.ca.tracker import create_filing
    async with tenant_session(org_id) as conn:
        data, f = await core.file_bytes(conn, file_id, client_id)
        client = dict((await conn.execute(text("select name, pan from app.ca_clients where id = cast(:i as uuid)"), {"i": client_id})).mappings().one())
        cfg = await core.enabled(conn, "ca_notice_handler") or {}
    n = await read(org_id, client, data, f["mime"], f["filename"])
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.ca_files set doc_type = 'notice', extracted = cast(:e as jsonb) where id = cast(:i as uuid)"),
                           {"e": json.dumps(n), "i": file_id})
        due = core.parse_date(n.get("respond_by"))
        plan = date.fromordinal(due.toordinal() - int(cfg.get("days_before", 5))) if due else None
        period = f"{n.get('section') or 'notice'} {('AY ' + n['assessment_year']) if n.get('assessment_year') else ''}".strip()
        fid = await create_filing(conn, org_id, client_id, kind="notice_reply", period=period[:40], due_on=plan, source="notice",
                                  title=f"Reply to {n.get('section') or 'notice'}" + (f" (AY {n['assessment_year']})" if n.get("assessment_year") else ""),
                                  notes=n.get("summary"))
        if fid:
            items = [{"key": f"n{i}", "label": d[:120], "status": "missing", "file_ids": [], "received_at": None}
                     for i, d in enumerate(n.get("documents_needed") or [])] or chaser.checklist_for("notice_reply", {})
            await conn.execute(text("update app.ca_filings set checklist = cast(:c as jsonb), data = data || cast(:d as jsonb), status = 'docs_pending' where id = cast(:i as uuid)"),
                               {"c": json.dumps(items), "d": json.dumps({"notice_file": file_id}), "i": fid})
            await conn.execute(text("update app.ca_files set filing_id = cast(:f as uuid) where id = cast(:i as uuid)"), {"f": fid, "i": file_id})
        demand = core.money(n.get("demand")) or 0
        await core.card(conn, org_id, "ca_notice_handler", f"{client['name']}: {n.get('section') or 'a'} notice"
                        + (f", respond by {due:%d %b %Y}" if due else ""),
                        f"{n.get('summary') or ''}{f' Demand: {core.inr(demand)}.' if demand else ''} The reply is drafted on the client's page.",
                        {"key": f"notice:{file_id}", "file_id": file_id, "client_id": client_id})
        wid = await core.save_work(conn, org_id, client_id, "ca_notice_handler", f"{n.get('section') or 'Notice'}"
                                   + (f" AY {n['assessment_year']}" if n.get("assessment_year") else ""), n | {"filing_id": fid},
                                   file_ids=[file_id], user_id=user_id)
    return n | {"filing_id": fid, "work_id": wid}
