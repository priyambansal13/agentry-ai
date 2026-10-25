"""Waiting for a reply (#10): the business wrote last, a client or lead has gone quiet for `nudge_after_days`, so a
short follow-up draft appears in Needs you (in the same Gmail thread). Once per quiet spell: a new message from either
side starts a fresh wait. Nothing is sent without a person, like every inbox draft.
"""
import json
import logging

from sqlalchemy import text

from agentry.automations.inbox_triage.config import TriageConfig
from agentry.connectors.mailbox import mailbox_for
from agentry.db import system_session, tenant_session
from agentry.llm.gateway import AllModelsFailed, complete

log = logging.getLogger("agentry.inbox.nudges")
FOLLOW_UP_CATEGORIES = ("Client", "Lead")
PROMPT = """Write a short, friendly follow-up email (under 60 words) from {business} to someone who hasn't replied to the
last email below. Don't repeat the whole email; one line on what it was about, one easy question, a sign-off "{signoff}".
Match the language of the conversation. Reply with the email body only.

Last email from us:
\"\"\"{last}\"\"\""""

QUIET_SQL = """
select c.id, c.subject, m_in.metadata->>'from' as contact, m_out.body as last_out, m_out.created_at as last_out_at
from app.conversations c
join lateral (select * from app.messages where conversation_id = c.id order by created_at desc limit 1) m_out on m_out.direction = 'out'
join lateral (select * from app.messages where conversation_id = c.id and direction = 'in' and metadata ? 'triage'
              order by created_at desc limit 1) m_in on true
where c.channel = 'email' and c.automation_key = 'inbox_triage' and c.status not in ('closed')
  and m_out.created_at < now() - make_interval(days => :days) and m_out.created_at > now() - make_interval(days => :days + 14)
  and m_in.metadata->'triage'->>'category' = any(:cats)
  and not coalesce((m_in.metadata->'triage'->>'suspicious')::boolean, false)
  and not exists (select 1 from app.approvals a where a.conversation_id = c.id and a.status = 'pending')
  and coalesce((c.metadata->>'nudged_after')::timestamptz, 'epoch') < m_out.created_at
"""


async def suggest_follow_ups(org_id: str) -> int:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select a.config, a.status, s.persona, o.name from app.automation_instances a
            join app.org_settings s on s.org_id = a.org_id join auth.organization o on o.id = a.org_id
            where a.template_key = 'inbox_triage'"""))).first()
        if not row or row.status not in ("live", "approval_mode"):
            return 0
        cfg = TriageConfig(**(row.config or {}))
        if not cfg.nudge_after_days:
            return 0
        quiet = (await conn.execute(text(QUIET_SQL), {"days": cfg.nudge_after_days, "cats": [*FOLLOW_UP_CATEGORIES, *cfg.custom_categories]})).mappings().all()
    signoff = (row.persona or {}).get("signoff") or f"The {row.name} team"
    made = 0
    for q in quiet:
        first = (q["contact"] or "there").split("@")[0].split(".")[0].capitalize()
        fallback = f"Hi {first},\n\nJust following up on my last email about \"{q['subject'] or 'our conversation'}\". Any thoughts?\n\n{signoff}"
        try:
            res = await complete("writer", [{"role": "user", "content": PROMPT.format(business=row.name, signoff=signoff, last=(q["last_out"] or "")[:1500])}],
                                 org_id=org_id, prompt_key="inbox_follow_up", prompt_version="v1", mock_response=fallback)
            body = res.text.strip() or fallback
        except AllModelsFailed:
            body = fallback
        try:
            await (await mailbox_for(org_id, str(q["id"]))).create_draft(org_id, str(q["id"]), body)
        except Exception as e:  # noqa: BLE001 - the card still works without the Gmail draft; approving sends a fresh reply
            log.info("follow-up draft not saved in the mailbox for %s: %s", q["id"], e)
        days = cfg.nudge_after_days
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
                values (:o, 'reply_draft', 'inbox_triage', :c, :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "c": q["id"], "t": f"No reply from {q['contact']} in {days} days: send a follow-up?", "b": body,
                 "p": json.dumps({"nudge": True, "category": "Follow-up", "draft": body})})
            await conn.execute(text("update app.conversations set metadata = metadata || jsonb_build_object('nudged_after', cast(:t as text)) where id = :c"),
                               {"t": q["last_out_at"].isoformat(), "c": q["id"]})
        made += 1
    return made


async def run_daily() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("select org_id from app.automation_instances where template_key = 'inbox_triage'"))).scalars())
    return sum([await suggest_follow_ups(o) for o in orgs])
