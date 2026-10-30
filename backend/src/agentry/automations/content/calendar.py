"""The content calendar and publishing (Phase 6.4-6.5).

Approved posts get slots in the business's timezone, starting tomorrow: LinkedIn once a day on weekdays at 09:30,
Instagram once a day at 12:30, X twice a day at 10:00 and 16:00. Two posts from the same moment never land on the same
day, so a week doesn't repeat itself. Every 5 minutes, posts whose time has come are published: recorded in test mode
("mock"), through the platform once its account is connected (6.5).
"""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.db import system_session, tenant_session

SLOTS = {"linkedin": [time(9, 30)], "instagram": [time(12, 30)], "x": [time(10, 0), time(16, 0)]}
WEEKDAYS_ONLY = {"linkedin"}
PLATFORM_ORDER = {"linkedin": 0, "instagram": 1, "x": 2}


async def schedule(conn: AsyncConnection, tz: str, source_id: str | None = None, start: date | None = None) -> int:
    """Give every approved, unscheduled post a slot. Returns how many were scheduled."""
    zone = ZoneInfo(tz or "Asia/Kolkata")
    start = start or (datetime.now(zone).date() + timedelta(days=1))
    taken = (await conn.execute(text("""select scheduled_at, platform, moment_id from app.content_posts
        where scheduled_at is not null and review = 'approved'"""))).all()
    per_slot: dict[tuple[date, str], int] = {}
    moment_days: set[tuple[date, str]] = set()
    for at, platform, mid in taken:
        d = at.astimezone(zone).date()
        per_slot[(d, platform)] = per_slot.get((d, platform), 0) + 1
        moment_days.add((d, str(mid)))
    rows = (await conn.execute(text("""select p.id, p.platform, p.moment_id, m.rank from app.content_posts p
        join app.content_moments m on m.id = p.moment_id
        where p.review = 'approved' and p.scheduled_at is null and p.published_at is null
          and (cast(:s as uuid) is null or p.source_id = cast(:s as uuid))"""), {"s": source_id})).all()
    done = 0
    for pid, platform, mid, _rank in sorted(rows, key=lambda r: (r.rank, PLATFORM_ORDER[r.platform])):
        d = start
        for _ in range(366):
            used = per_slot.get((d, platform), 0)
            ok_day = not (platform in WEEKDAYS_ONLY and d.weekday() >= 5)
            if ok_day and used < len(SLOTS[platform]) and (d, str(mid)) not in moment_days:
                at = datetime.combine(d, SLOTS[platform][used], tzinfo=zone).astimezone(UTC)
                await conn.execute(text("update app.content_posts set scheduled_at = :t, updated_at = now() where id = :i"), {"t": at, "i": pid})
                per_slot[(d, platform)] = used + 1
                moment_days.add((d, str(mid)))
                done += 1
                break
            d += timedelta(days=1)
    return done


async def publish_due(org_id: str, now: datetime | None = None) -> dict:
    """Publish approved posts whose slot has come."""
    now = now or datetime.now(UTC)
    published, failed = 0, 0
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select id, platform from app.content_posts where review = 'approved' and published_at is null
            and publish_error is null and scheduled_at <= :n order by scheduled_at"""), {"n": now})).all()
        for pid, platform in rows:
            if settings.content_publisher == "mock":
                await conn.execute(text("""update app.content_posts set published_at = :n, publish_ref = :r, updated_at = now() where id = :i"""),
                                   {"n": now, "r": f"test-mode:{platform}:{pid}", "i": pid})
                published += 1
            else:
                await conn.execute(text("update app.content_posts set publish_error = :e where id = :i"),
                                   {"e": f"{platform} isn't connected yet", "i": pid})
                failed += 1
    return {"published": published, "failed": failed}


@DBOS.step()
async def content_orgs_due() -> list[str]:
    async with system_session() as conn:
        return list((await conn.execute(text("""select distinct org_id from app.content_posts where review = 'approved'
            and published_at is null and publish_error is null and scheduled_at <= now()"""))).scalars())


@DBOS.step()
async def content_publish_step(org_id: str) -> dict:
    return await publish_due(org_id)


@DBOS.workflow()
async def publish_scheduled(scheduled_time: datetime, context) -> None:
    for org_id in await content_orgs_due():
        await content_publish_step(org_id)
