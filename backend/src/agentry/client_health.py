"""Client health (ROADMAP-V3 A7): which of Agentry's clients need attention before they cancel.

For every client (not demos), from data Agentry already has, a score out of 100 with the reasons:
    usage        messages and work done in the last 14 days vs the 14 before (a big drop is the strongest signal)
    logins       when anyone from the client last used the portal
    waiting      cards in Needs you older than 3 days (the client isn't keeping up, or the agents ask too much)
    connections  disconnected or failing Gmail / WhatsApp / ...
    failures     agent runs that failed in the last 7 days
    billing      statements issued and unpaid for more than 15 days
healthy >= 75, watch 50-74, at risk < 50. HQ page /hq/health; a Monday email to the Agentry team lists the at-risk ones.
"""
from datetime import UTC, datetime, timedelta

from dbos import DBOS
from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session


async def assess(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    a14, a28, a7, a3, a15 = (now - timedelta(days=d) for d in (14, 28, 7, 3, 15))
    async with system_session() as conn:
        rows = (await conn.execute(text("""
            select o.id, o.name, s.status, s.created_at,
              (select count(*) from app.automation_instances a where a.org_id = o.id) as agents,
              (select count(*) from app.events e where e.org_id = o.id and e.occurred_at >= :a14) as work_now,
              (select count(*) from app.events e where e.org_id = o.id and e.occurred_at >= :a28 and e.occurred_at < :a14) as work_before,
              (select max(x."updatedAt") from auth.session x join auth.member m on m."userId" = x."userId" where m."organizationId" = o.id) as last_login,
              (select count(*) from app.approvals p where p.org_id = o.id and p.status = 'pending' and p.created_at < :a3) as stale_cards,
              (select count(*) from app.connections c where c.org_id = o.id and (c.status <> 'connected' or c.last_error is not null)) as bad_connections,
              (select count(*) from app.agent_runs r where r.org_id = o.id and r.status = 'failed' and r.started_at >= :a7) as failed_runs,
              (select count(*) from app.statements t where t.org_id = o.id and t.status in ('issued','finalized') and t.issued_at < :a15) as unpaid
            from auth.organization o join app.org_settings s on s.org_id = o.id where s.status not in ('demo','churned') order by o.name"""),
            {"a14": a14, "a28": a28, "a7": a7, "a3": a3, "a15": a15})).mappings().all()
    out = []
    for r in rows:
        score, reasons = 100, []
        new = r["created_at"] and r["created_at"] > a28
        if r["work_before"] >= 20 and r["work_now"] < r["work_before"] * 0.5:
            score -= 30
            reasons.append(f"activity fell {100 - round(100 * r['work_now'] / r['work_before'])}% in the last two weeks")
        elif r["work_now"] == 0 and not new:
            score -= 25
            reasons.append("no activity in two weeks")
        if not r["last_login"] or r["last_login"].replace(tzinfo=UTC) < now - timedelta(days=21):
            score -= 20
            reasons.append("nobody has opened the portal in 3 weeks" if r["last_login"] else "nobody has signed in yet")
        elif r["last_login"].replace(tzinfo=UTC) < now - timedelta(days=10):
            score -= 8
            reasons.append("no portal visit in 10 days")
        if r["stale_cards"] >= 5:
            score -= 15
            reasons.append(f"{r['stale_cards']} cards waiting more than 3 days")
        elif r["stale_cards"]:
            score -= 5
            reasons.append(f"{r['stale_cards']} card(s) waiting more than 3 days")
        if r["bad_connections"]:
            score -= 15
            reasons.append(f"{r['bad_connections']} connection(s) disconnected or failing")
        if r["failed_runs"] >= 5:
            score -= 10
            reasons.append(f"{r['failed_runs']} agent runs failed this week")
        if r["unpaid"]:
            score -= 15
            reasons.append(f"{r['unpaid']} statement(s) unpaid for over 15 days")
        if r["status"] == "paused":
            score -= 20
            reasons.append("the client is paused")
        score = max(0, score)
        out.append({"org_id": r["id"], "name": r["name"], "status": r["status"], "agents": r["agents"], "score": score,
                    "level": "healthy" if score >= 75 else "watch" if score >= 50 else "at_risk", "reasons": reasons,
                    "work_14d": r["work_now"], "work_prev_14d": r["work_before"], "last_login": r["last_login"]})
    return sorted(out, key=lambda x: x["score"])


async def weekly_email(now: datetime | None = None) -> int:
    from agentry.notify.email import send_email
    rows = [r for r in await assess(now) if r["level"] != "healthy"]
    if not rows or not settings.ops_email:
        return 0
    body = "Clients that need attention this week:\n\n" + "\n".join(
        f"- {r['name']}: {r['score']}/100 ({r['level'].replace('_', ' ')}). " + "; ".join(r["reasons"]) for r in rows) + \
        f"\n\nAll clients: {settings.dashboard_url}/hq/health"
    import asyncio
    await asyncio.to_thread(send_email, settings.ops_email, f"Client health: {sum(r['level'] == 'at_risk' for r in rows)} at risk", body)
    return len(rows)


@DBOS.step()
async def health_step() -> int:
    return await weekly_email()


@DBOS.workflow()
async def client_health_weekly(scheduled_time: datetime, context) -> None:
    await health_step()
