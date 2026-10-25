"""Lead reactivation (docs/automations/lead-reactivation.md): old leads -> consent check -> paced "hi again"
messages -> replies handed to the assistant, which re-qualifies and books."""
import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.leads import can_contact, opt_out, record_consent, resolve_contact
from agentry.sequences import DEFAULTS, enroll, ensure_sequence


class ReactivationConfig(BaseModel):
    per_hour: int = Field(20, ge=1, le=200, title="Messages per hour (pacing)", json_schema_extra={"editable_by": "client"})
    offer: str | None = Field(None, title="Offer you're happy to mention (optional)",
                              description="e.g. 'free assessment this month'. The AI never invents offers.",
                              json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="lead_reactivation",
    name="Lead reactivation",
    description="Re-engages old leads one by one on WhatsApp or email, re-qualifies the interested ones and books them.",
    config_model=ReactivationConfig,
    metrics=("appointments_booked", "messages_sent", "leads_captured"),
))

TERMINAL = ("booked", "showed", "won", "lost", "disqualified", "opted_out")


async def import_old_leads(conn: AsyncConnection, org_id: str, rows: list[dict]) -> dict:
    """Rows need name and phone and/or email; optional: last_interest, last_contact, status, notes,
    consent ('whatsapp_optin' | 'opted_out' | 'none')."""
    stats = {"rows": len(rows), "leads_created": 0, "leads_updated": 0, "opted_out": 0, "skipped": 0}
    for r in rows:
        if not (r.get("phone") or r.get("email")):
            stats["skipped"] += 1
            continue
        cid = await resolve_contact(conn, org_id, name=r.get("name"), phone=r.get("phone"), email=r.get("email"),
                                    source="import:old_leads")
        consent = (r.get("consent") or "").strip().lower()
        if consent == "whatsapp_optin":
            await record_consent(conn, org_id, cid, "whatsapp", True, "import:whatsapp_optin")
        qual = {k: v for k, v in {"interest": r.get("last_interest"), "last_contact": r.get("last_contact"),
                                  "previous_status": r.get("status"), "notes": r.get("notes")}.items() if v}
        existing = (await conn.execute(text("""select id, stage from app.leads where contact_id = :c and stage not in
            ('won','lost','disqualified') order by created_at desc limit 1"""), {"c": cid})).first()
        if existing:
            await conn.execute(text("update app.leads set qualification = qualification || cast(:q as jsonb) where id = :l"),
                               {"q": json.dumps(qual), "l": existing.id})
            stats["leads_updated"] += 1
        else:
            await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage, qualification)
                values (:o, :c, 'old_leads', 'nurture', cast(:q as jsonb))"""), {"o": org_id, "c": cid, "q": json.dumps(qual)})
            stats["leads_created"] += 1
        if consent == "opted_out":
            for ch in ("whatsapp", "email", "sms"):
                await opt_out(conn, org_id, cid, ch, source="import:opted_out")
            stats["opted_out"] += 1
    return stats


async def eligibility(conn: AsyncConnection) -> dict:
    """Who a reactivation campaign would contact, and why the others are left out."""
    channels = DEFAULTS["reactivation_default"]["steps"][0]["channels"]
    rows = (await conn.execute(text("""select l.id, l.contact_id, k.name from app.leads l join app.contacts k on k.id = l.contact_id
        where l.stage in ('nurture','contacted','new') and k.merged_into is null
          and not exists (select 1 from app.sequence_enrollments e where e.subject_id = l.id and e.status in ('active','paused'))"""))).all()
    eligible, blocked = [], {}
    for r in rows:
        reasons = []
        for ch in channels:
            ok, why = await can_contact(conn, str(r.contact_id), ch)
            if ok:
                eligible.append({"lead_id": str(r.id), "contact_id": str(r.contact_id), "name": r.name, "channel": ch})
                break
            reasons.append(f"{ch}: {why}")
        else:
            key = "; ".join(reasons)
            blocked[key] = blocked.get(key, 0) + 1
    return {"eligible": eligible, "blocked": blocked}


async def start_campaign(conn: AsyncConnection, org_id: str, name: str, per_hour: int) -> dict:
    seq_id = await ensure_sequence(conn, org_id, "reactivation_default")
    elig = await eligibility(conn)
    cid = str((await conn.execute(text("""insert into app.campaigns (org_id, kind, name, sequence_id, status, per_hour, stats)
        values (:o, 'reactivation', :n, :s, 'running', :p, cast(:st as jsonb)) returning id"""),
        {"o": org_id, "n": name, "s": seq_id, "p": per_hour,
         "st": json.dumps({"eligible": len(elig["eligible"]), "blocked": elig["blocked"]})})).scalar_one())
    start, gap = datetime.now(UTC), timedelta(seconds=3600 / per_hour)
    for i, e in enumerate(elig["eligible"]):  # one by one: each gets its own start slot
        await enroll(conn, org_id, sequence_key="reactivation_default", subject_type="lead", subject_id=e["lead_id"],
                     contact_id=e["contact_id"], start_at=start + i * gap)
        await conn.execute(text("update app.leads set owner_automation = 'lead_reactivation', owner_since = now() where id = :l"),
                           {"l": e["lead_id"]})
    return {"campaign_id": cid, "enrolled": len(elig["eligible"]), "blocked": elig["blocked"],
            "finishes_at": (start + len(elig["eligible"]) * gap).isoformat()}
