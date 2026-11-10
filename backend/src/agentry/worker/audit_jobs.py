"""The free website audit in the worker (agentry/site_audit.py): run it, and when the visitor leaves their details,
tell the Agentry team, email them the report link and add them to Agentry's own leads."""
import json

from dbos import DBOS
from sqlalchemy import text

from agentry import site_audit
from agentry.config import settings
from agentry.db import system_session
from agentry.worker.handlers import on
from agentry.worker.sales_jobs import email_step, mirror_lead_step


@DBOS.step()
async def site_audit_step(audit_id: str) -> str:
    return (await site_audit.run(audit_id))["status"]


@on("site_audit.requested")
@DBOS.workflow()
async def on_audit_requested(event: dict) -> None:
    await site_audit_step(event["payload"]["audit_id"])


@DBOS.step()
async def load_site_audit(audit_id: str) -> dict:
    async with system_session() as conn:
        a = (await conn.execute(text("select *, id::text as id from app.site_audits where id = cast(:i as uuid)"), {"i": audit_id})).mappings().first()
    return json.loads(json.dumps(dict(a), default=str))


@DBOS.step()
async def mark_audit_sent(audit_id: str) -> None:
    async with system_session() as conn:
        await conn.execute(text("update app.site_audits set report_sent_at = now() where id = cast(:i as uuid)"), {"i": audit_id})


@on("site_audit.unlocked")
@DBOS.workflow()
async def on_audit_unlocked(event: dict) -> None:
    a = await load_site_audit(event["payload"]["audit_id"])
    r = a.get("result") or {}
    await email_step(settings.ops_email, f"Website audit lead: {r.get('name') or a['domain']} ({a['score']}/100)",
                     f"{a['name']} <{a['email']}> {a.get('phone') or ''}\n{a['service']} in {a['city']}: {a['url']}\n\n"
                     + "\n".join(f"- {p['title']}" for p in r.get("problems") or [])
                     + f"\n\nReport: {settings.web_url.rstrip('/')}/audit/r/{a['id']}"
                     + f"\nOpen it in Agentry HQ: {settings.dashboard_url}/hq/demo-requests/{event['payload']['demo_request_id']}")
    await email_step(a["email"], *site_audit.report_email(a["name"], a))
    await mark_audit_sent(a["id"])
    await mirror_lead_step(event["payload"]["demo_request_id"])


@DBOS.step()
async def audit_release_step() -> int:
    from agentry import instant_demo
    await instant_demo.purge()
    return await site_audit.release_waiting()


@DBOS.workflow()
async def release_waiting_audits(scheduled_time, context) -> None:
    await audit_release_step()
