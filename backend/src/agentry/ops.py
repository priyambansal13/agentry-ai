"""Platform health checks for Agentry ops: run by the `agentry alerts` cron job and the API's /ready probe.

Alerts go to AGENTRY_OPS_EMAIL (and Telegram when AGENTRY_OPS_TELEGRAM_CHAT_ID is set). Each run looks only at the last
`minutes`, so a failure is reported once; a stuck outbox (the worker is down) is reported on every run until fixed.
"""
import httpx
from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session
from agentry.notify.email import send_email

LLM_ERROR_RATE = 0.25  # alert when more than a quarter of model calls fail (after fallbacks are tried, each attempt counts)
LLM_MIN_CALLS = 8
OUTBOX_LAG_MINUTES = 5
CALL_STUCK_MINUTES = 30  # a call with no end after this long: the voice worker died mid-call (or never saved it)
VOICE_SLOW_MS = 3500  # average brain time per turn above this feels broken on a phone call


async def check(minutes: int = 10) -> list[str]:
    problems: list[str] = []
    since_ms = f"(extract(epoch from now() - make_interval(mins => {int(minutes)})) * 1000)::bigint"
    async with system_session() as conn:
        failed = (await conn.execute(text(f"""select name, count(*) as n, coalesce(max(left(error, 200)), 'details in dbos.operation_outputs') as error from dbos.workflow_status
            where status in ('ERROR', 'MAX_RECOVERY_ATTEMPTS_EXCEEDED', 'RETRIES_EXCEEDED') and updated_at >= {since_ms}
            group by name order by n desc"""))).all()
        for f in failed:
            problems.append(f"{f.n} workflow run(s) of {f.name} failed in the last {minutes} min: {f.error}")
        lag = (await conn.execute(text("""select count(*) as n, extract(epoch from now() - min(occurred_at)) / 60 as oldest
            from app.events where dispatched_at is null"""))).one()
        if lag.n and lag.oldest and lag.oldest > OUTBOX_LAG_MINUTES:
            problems.append(f"{lag.n} events waiting, oldest {lag.oldest:.0f} min: is the worker running?")
        llm = (await conn.execute(text("""select count(*) as n, count(*) filter (where status = 'error') as errors,
            max(error) filter (where status = 'error') as sample
            from app.llm_calls where at >= now() - make_interval(mins => :m) and model not like 'mock/%'"""), {"m": minutes})).one()
        misconfigured = (await conn.execute(text("""select distinct model from app.llm_calls where at >= now() - make_interval(mins => :m)
            and status = 'error' and (error like '%NotFoundError%' or error like '%AuthenticationError%')"""), {"m": minutes})).scalars().all()
        for model in misconfigured:
            problems.append(f"model {model} is misconfigured (unknown model or bad key): check AGENTRY_MODEL_* and the provider key")
        if llm.n >= LLM_MIN_CALLS and llm.errors / llm.n > LLM_ERROR_RATE:
            problems.append(f"{llm.errors} of {llm.n} model calls failed in the last {minutes} min, e.g. {(llm.sample or '')[:200]}")
        # Connections carry no "errored at" time, so broken ones are summarised once an hour (the run in its first minutes).
        broken = (await conn.execute(text("""select o.name, c.provider, c.last_error from app.connections c
            join auth.organization o on o.id = c.org_id where c.status = 'error' and extract(minute from now()) < :m"""),
            {"m": minutes})).all()
        for b in broken:
            problems.append(f"{b.name}: {b.provider} connection not working ({(b.last_error or '')[:120]})")
        # Voice calls. Each check looks at one window, so a call is reported once.
        stuck = (await conn.execute(text("""select o.name, count(*) as n from app.conversations c join auth.organization o on o.id = c.org_id
            where c.channel = 'voice' and not c.metadata ? 'ended_at'
              and c.created_at <  now() - make_interval(mins => :s)
              and c.created_at >= now() - make_interval(mins => :s + :m) group by o.name"""), {"s": CALL_STUCK_MINUTES, "m": minutes})).all()
        for c in stuck:
            problems.append(f"{c.name}: {c.n} call(s) started over {CALL_STUCK_MINUTES} min ago never finished: is `agentry voice` running? (no recording or summary for them)")
        calls = (await conn.execute(text("""select o.name, c.id, (c.metadata->'latency_ms'->>'avg')::int as avg_ms,
              coalesce((c.metadata->>'failed_turns')::int, 0) as failed, coalesce((c.metadata->>'turns')::int, 0) as turns
            from app.conversations c join auth.organization o on o.id = c.org_id
            where c.channel = 'voice' and (c.metadata->>'ended_at')::timestamptz >= now() - make_interval(mins => :m)"""),
            {"m": minutes})).all()
        for c in calls:
            if c.failed:
                problems.append(f"{c.name}: the AI couldn't answer {c.failed} of {c.turns} turn(s) on a call (all models failed): "
                                f"{settings.dashboard_url}/conversations/{c.id}")
        slow = [c for c in calls if c.avg_ms and c.avg_ms > VOICE_SLOW_MS]
        if slow:
            problems.append(f"{len(slow)} call(s) in the last {minutes} min were slow: average reply {max(c.avg_ms for c in slow) / 1000:.1f} s "
                            f"(alert above {VOICE_SLOW_MS / 1000:.1f} s); check model latency or set AGENTRY_MODEL_VOICE")
    return problems


async def ready() -> bool:
    async with system_session() as conn:
        await conn.execute(text("select 1"))
    return True


def send(problems: list[str]) -> None:
    body = "Agentry health check found:\n\n" + "\n".join(f"- {p}" for p in problems)
    send_email(settings.ops_email, f"[Agentry {settings.env}] {len(problems)} problem(s)", body)
    if settings.telegram_bot_token and settings.ops_telegram_chat_id:
        httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                   json={"chat_id": settings.ops_telegram_chat_id, "text": body[:4000]}, timeout=10)
