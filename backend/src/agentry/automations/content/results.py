"""Content results (Phase 6.6): what came out of the recordings in a period, for Reports, the monthly email and billing.

    recordings        recordings that finished (shown to the client)
    videos            the billable ones: the same without the demo sample podcast
    generated         posts written
    approved          posts a person approved, and how many of those as written (the quality measure)
    published         posts that went out (test mode counts, marked)
    turnaround        upload -> drafts ready, median minutes
"""
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

VIDEOS_SQL = """select count(*) from app.content_sources where kind <> 'sample' and status = 'ready'
    and ready_at >= :a and ready_at < :b"""


async def summary(conn: AsyncConnection, start: datetime, end: datetime) -> dict:
    p = (await conn.execute(text("""select count(*) as generated,
            count(*) filter (where review = 'approved') as approved,
            count(*) filter (where review = 'approved' and not edited) as approved_as_written,
            count(*) filter (where review = 'needs_attention') as needs_attention
        from app.content_posts where created_at >= :a and created_at < :b"""), {"a": start, "b": end})).mappings().one()
    published = (await conn.execute(text("""select count(*) from app.content_posts where published_at >= :a and published_at < :b"""),
                                    {"a": start, "b": end})).scalar_one()
    videos = (await conn.execute(text(VIDEOS_SQL), {"a": start, "b": end})).scalar_one()
    recordings = (await conn.execute(text("select count(*) from app.content_sources where status = 'ready' and ready_at >= :a and ready_at < :b"),
                                     {"a": start, "b": end})).scalar_one()
    turnaround = (await conn.execute(text("""select percentile_cont(0.5) within group (order by extract(epoch from ready_at - created_at) / 60)
        from app.content_sources where ready_at >= :a and ready_at < :b"""), {"a": start, "b": end})).scalar_one()
    return {"recordings": recordings, "videos": videos, "generated": p["generated"], "approved": p["approved"], "approved_as_written": p["approved_as_written"],
            "approved_as_written_pct": round(100 * p["approved_as_written"] / p["approved"]) if p["approved"] else None,
            "needs_attention": p["needs_attention"], "published": published,
            "turnaround_minutes": round(float(turnaround), 1) if turnaround is not None else None}
