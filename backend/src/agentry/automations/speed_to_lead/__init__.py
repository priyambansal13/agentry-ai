"""Speed-to-lead, text version (voice calls arrive in Phase 4): a new form/ad lead gets a first message within about
a minute, then the assistant takes over when they reply."""
import secrets

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.db import tenant_session
from agentry.events import emit
from agentry.leads import claim, record_consent, resolve_contact
from agentry.sequences import enroll
from agentry.worker.handlers import on


class SpeedToLeadConfig(BaseModel):
    first_message_after_seconds: int = Field(60, ge=0, le=900, title="Send the first message after (seconds)",
                                             json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="speed_to_lead",
    name="Speed-to-lead",
    description="New form and ad leads get a message within about a minute; replies go straight to your assistant.",
    config_model=SpeedToLeadConfig,
    metrics=("leads_captured", "appointments_booked"),
))


async def create_source(conn: AsyncConnection, org_id: str, name: str) -> dict:
    key = "ls_" + secrets.token_urlsafe(18)
    sid = (await conn.execute(text("insert into app.lead_sources (org_id, name, key) values (:o, :n, :k) returning id"),
                              {"o": org_id, "n": name, "k": key})).scalar_one()
    return {"id": str(sid), "name": name, "key": key}


async def capture(conn: AsyncConnection, org_id: str, source_name: str, data: dict) -> str:
    """A form submission becomes a contact + lead. Ticking a WhatsApp opt-in box grants WhatsApp consent."""
    cid = await resolve_contact(conn, org_id, name=data.get("name"), phone=data.get("phone"), email=data.get("email"),
                                source=f"form:{source_name}")
    if str(data.get("whatsapp_optin", "")).lower() in ("1", "true", "yes", "on"):
        await record_consent(conn, org_id, cid, "whatsapp", True, f"form:{source_name}")
    qual = {k: v for k, v in {"need": data.get("message"), "form": source_name, "utm_source": data.get("utm_source")}.items() if v}
    import json
    lid = str((await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage, qualification)
        values (:o, :c, :s, 'new', cast(:q as jsonb)) returning id"""),
        {"o": org_id, "c": cid, "s": f"form:{source_name}", "q": json.dumps(qual)})).scalar_one())
    await emit(conn, org_id, "lead.created", {"lead_id": lid, "source": "form", "form": source_name})
    return lid


@DBOS.step()
async def start_first_touch(org_id: str, lead_id: str) -> str | None:
    from datetime import UTC, datetime, timedelta
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select a.status, a.config, l.contact_id from app.leads l
            left join app.automation_instances a on a.template_key = 'speed_to_lead' where l.id = :l"""), {"l": lead_id})).first()
        if not row or row.status not in ("live", "approval_mode"):
            return None
        if not await claim(conn, lead_id, "speed_to_lead"):
            return None
        delay = SpeedToLeadConfig(**(row.config or {})).first_message_after_seconds
        return await enroll(conn, org_id, sequence_key="speed_to_lead_default", subject_type="lead", subject_id=lead_id,
                            contact_id=str(row.contact_id), start_at=datetime.now(UTC) + timedelta(seconds=delay - 60))


@on("lead.created")
@DBOS.workflow()
async def on_new_lead(event: dict) -> None:
    if event["payload"].get("source") == "form":
        await start_first_touch(event["org_id"], event["payload"]["lead_id"])
