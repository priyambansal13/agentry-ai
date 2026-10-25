"""Inbox triage numbers that show the value (#17, #18) and the daily clean-up of old email text (#4).

- Response time: for each email conversation, time from the client's first email to the business's first reply
  (sent through Agentry or straight from Gmail, which sync now records). Median per month; the "before Agentry"
  baseline is measured from Gmail once, when it is connected.
- Draft quality: of the AI's reply drafts that were decided, how many were sent as written, edited, or discarded.
- Retention: email text older than `keep_email_text_days` is removed; summaries, labels and replies stay.
"""
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.db import system_session

# first reply per conversation: (minutes from the first inbound email to the first outbound message after it)
FIRST_REPLY_SQL = """
with firsts as (
  select c.id, min(m.created_at) filter (where m.direction = 'in') as first_in
  from app.conversations c join app.messages m on m.conversation_id = c.id
  where c.channel = 'email' and c.automation_key = 'inbox_triage'
  group by c.id
)
select f.id, f.first_in,
       (select min(o.created_at) from app.messages o where o.conversation_id = f.id and o.direction = 'out'
          and o.created_at > f.first_in) as first_out
from firsts f where f.first_in >= :a and f.first_in < :b
"""


def _median_minutes(rows) -> float | None:
    mins = [(r.first_out - r.first_in).total_seconds() / 60 for r in rows if r.first_out]
    return round(statistics.median(mins), 1) if mins else None


async def response_times(conn: AsyncConnection, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_start = (this_start - timedelta(days=1)).replace(day=1)
    this = (await conn.execute(text(FIRST_REPLY_SQL), {"a": this_start, "b": now})).all()
    last = (await conn.execute(text(FIRST_REPLY_SQL), {"a": last_start, "b": this_start})).all()
    baseline = (await conn.execute(text("""select (state->>'baseline_response_minutes')::numeric from app.connections
        where provider = 'gmail' and state ? 'baseline_response_minutes' order by created_at desc limit 1"""))).scalar()
    return {"this_month_minutes": _median_minutes(this), "last_month_minutes": _median_minutes(last),
            "before_agentry_minutes": float(baseline) if baseline is not None else None,
            "answered": sum(1 for r in this if r.first_out), "unanswered": sum(1 for r in this if not r.first_out)}


async def draft_quality(conn: AsyncConnection, since: datetime) -> dict:
    rows = dict((await conn.execute(text("""select status, count(*) from app.approvals where kind = 'reply_draft'
        and automation_key = 'inbox_triage' and decided_at >= :a and status <> 'pending' and decided_by is not null
        group by status"""), {"a": since})).all())  # people's decisions only: auto-sent drafts aren't a quality signal
    as_is, edited, discarded = rows.get("approved", 0), rows.get("edited", 0), rows.get("rejected", 0)
    total = as_is + edited + discarded
    return {"sent_as_is": as_is, "edited": edited, "discarded": discarded, "total": total,
            "as_is_pct": round(100 * as_is / total) if total else None}


async def trusted_categories(conn: AsyncConnection, min_approved: int = 10) -> list[str]:
    """Categories whose drafts the team keeps sending unchanged (#13): at least `min_approved` sent as written in the
    last 60 days, and no more than 20 % edited or discarded."""
    rows = (await conn.execute(text("""select payload->>'category' as category,
          count(*) filter (where status = 'approved' and decided_by is not null) as as_is,
          count(*) filter (where status in ('edited', 'rejected')) as changed
        from app.approvals where kind = 'reply_draft' and automation_key = 'inbox_triage' and decided_at > now() - interval '60 days'
          and not coalesce((payload->>'nudge')::boolean, false)
        group by 1"""))).all()
    return sorted(r.category for r in rows if r.category and r.as_is >= min_approved and r.changed <= 0.2 * (r.as_is + r.changed))


async def insights(conn: AsyncConnection) -> dict:
    now = datetime.now(UTC)
    suspicious = (await conn.execute(text("""select count(*) from app.messages m join app.conversations c on c.id = m.conversation_id
        where c.automation_key = 'inbox_triage' and (m.metadata->'triage'->>'suspicious')::boolean and m.created_at >= :a"""),
        {"a": now - timedelta(days=30)})).scalar_one()
    cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'inbox_triage'"))).scalar() or {}
    trusted = await trusted_categories(conn, int(cfg.get("auto_send_min_approved", 10)))
    return {"response_time": await response_times(conn, now), "drafts_30_days": await draft_quality(conn, now - timedelta(days=30)),
            "suspicious_30_days": suspicious, "ready_for_auto_send": trusted,
            "auto_send_on": [c for c in cfg.get("auto_send_categories", []) if c in trusted]}


async def purge_old_email_text(now: datetime | None = None) -> int:
    """Daily: blank the text of inbound emails older than each client's keep_email_text_days (default 30).
    Emails with a card still waiting in Needs you are kept until it is decided."""
    async with system_session() as conn:
        orgs = (await conn.execute(text("select org_id, config from app.automation_instances where template_key = 'inbox_triage'"))).all()
        total = 0
        for o in orgs:
            days = int((o.config or {}).get("keep_email_text_days", 30))
            r = await conn.execute(text("""update app.messages m set body = '',
                  metadata = m.metadata || jsonb_build_object('body_deleted_at', cast(:now as text))
                from app.conversations c
                where c.id = m.conversation_id and m.org_id = :o and c.channel = 'email' and m.direction = 'in'
                  and m.body <> '' and m.created_at < cast(:now as timestamptz) - make_interval(days => :d)
                  and not exists (select 1 from app.approvals a where a.conversation_id = c.id and a.status = 'pending')"""),
                {"o": o.org_id, "d": days, "now": (now or datetime.now(UTC)).isoformat()})
            total += r.rowcount
    return total


def baseline_minutes(threads: list[dict], until_ms: int) -> float | None:
    """Median minutes from a client's email to the business's reply, from Gmail threads (format=metadata) before
    Agentry was connected. Each thread counts once: its first inbound message and the first SENT reply after it."""
    waits = []
    for t in threads:
        msgs = sorted(t.get("messages", []), key=lambda m: int(m.get("internalDate", 0)))
        first_in = next((m for m in msgs if "SENT" not in m.get("labelIds", []) and int(m.get("internalDate", 0)) < until_ms), None)
        if not first_in:
            continue
        reply = next((m for m in msgs if "SENT" in m.get("labelIds", [])
                      and int(m.get("internalDate", 0)) > int(first_in["internalDate"])), None)
        if reply:
            waits.append((int(reply["internalDate"]) - int(first_in["internalDate"])) / 60000)
    return round(statistics.median(waits), 1) if waits else None
