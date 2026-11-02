"""Engagement loop (ROADMAP-V3 B5, v2 8.6): how published posts and videos did, and what the next ones learn from it.

    fetch     24 hours and 7 days after publishing: Instagram (likes, comments, reach, saves, shares through the Graph API,
              using the post's media id), YouTube (views, likes, comments). LinkedIn member posts need LinkedIn's
              restricted Community Management API, so they aren't measured yet; test-mode posts have nothing to measure
    score     likes + 2 x comments + 3 x shares + 2 x saves (+ views / 50 for videos): one comparable number per post
    learn     per business, from the 7-day numbers: the topics that do best and worst, the best platform and hour, the
              hooks of the top posts -> saved on the business's profile (content_learning)
    use       moment ranking gives a boost to moments on topics that worked (and a nudge down to ones that didn't); the AI
              video studio tries the best topics first; a post in the business's top 10% emits content.top_post
"""
import json
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.connectors.http import client
from agentry.connectors.store import get_connection, update_state
from agentry.db import system_session, tenant_session
from agentry.events import emit


def score(m: dict) -> float:
    return round((m.get("likes") or 0) + 2 * (m.get("comments") or 0) + 3 * (m.get("shares") or 0) + 2 * (m.get("saves") or 0)
                 + (m.get("views") or 0) / 50, 2)


async def instagram_metrics(org_id: str, media_id: str) -> dict | None:
    from agentry.connectors import instagram
    conn = await get_connection(org_id, "instagram")
    if not conn:
        return None
    token, refreshed = await instagram.fresh_token(conn["secret"])
    if refreshed:
        await update_state(org_id, conn["id"], secret=refreshed)
    async with client() as c:
        r = await c.get(instagram._graph(media_id), params={"fields": "like_count,comments_count", "access_token": token})
        if r.status_code >= 400:
            return None
        base = r.json()
        ins = await c.get(instagram._graph(f"{media_id}/insights"), params={"metric": "reach,saved,shares", "access_token": token})
    vals = {}
    if ins.status_code < 400:
        for x in ins.json().get("data", []):
            vals[x.get("name")] = ((x.get("values") or [{}])[0] or {}).get("value")
    return {"likes": base.get("like_count"), "comments": base.get("comments_count"), "reach": vals.get("reach"), "saves": vals.get("saved"),
            "shares": vals.get("shares")}


async def youtube_metrics(org_id: str, video_id: str) -> dict | None:
    from agentry.connectors.youtube import API, YouTube, YouTubeError
    conn = await get_connection(org_id, "youtube")
    if not conn:
        return None
    try:
        token = await YouTube(org_id, conn).token()
    except YouTubeError:
        return None
    async with client() as c:
        r = await c.get(f"{API}/videos", params={"part": "statistics", "id": video_id}, headers={"Authorization": f"Bearer {token}"})
    items = (r.json() if r.status_code < 400 else {}).get("items") or []
    if not items:
        return None
    s = items[0].get("statistics") or {}
    return {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0))}


async def due(conn: AsyncConnection, now: datetime) -> list[dict]:
    """Published posts / videos whose 24 h or 7 d numbers haven't been fetched yet (and are old enough)."""
    out = []
    for hours in (24, 168):
        cutoff, too_old = now - timedelta(hours=hours), now - timedelta(hours=hours + 72)
        posts = (await conn.execute(text("""select p.id::text, p.platform, p.publish_id from app.content_posts p
            where p.published_at between :old and :cut and p.publish_id is not null and p.platform = 'instagram'
            and not exists (select 1 from app.post_metrics m where m.kind = 'post' and m.ref_id = p.id and m.at_hours = :h)"""),
            {"old": too_old, "cut": cutoff, "h": hours})).mappings().all()
        out += [{"kind": "post", "id": p["id"], "platform": p["platform"], "ext": p["publish_id"], "hours": hours} for p in posts]
        vids = (await conn.execute(text("""select v.id::text, v.publish->>'id' as ext from app.ai_videos v where v.status = 'published'
            and (v.publish->>'at')::timestamptz between :old and :cut
            and not exists (select 1 from app.post_metrics m where m.kind = 'video' and m.ref_id = v.id and m.at_hours = :h)"""),
            {"old": too_old, "cut": cutoff, "h": hours})).mappings().all()
        out += [{"kind": "video", "id": v["id"], "platform": "youtube", "ext": v["ext"], "hours": hours} for v in vids]
    return out


async def collect(org_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        todo = await due(conn, now)
    n = 0
    for t in todo:
        m = await (instagram_metrics(org_id, t["ext"]) if t["platform"] == "instagram" else youtube_metrics(org_id, t["ext"]))
        if m is None:
            continue
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""insert into app.post_metrics (org_id, kind, ref_id, platform, at_hours, views, likes, comments, shares, saves, reach, score)
                values (:o, :k, cast(:r as uuid), :p, :h, :v, :l, :c, :s, :sv, :re, :sc) on conflict (org_id, kind, ref_id, at_hours) do nothing"""),
                {"o": org_id, "k": t["kind"], "r": t["id"], "p": t["platform"], "h": t["hours"], "v": m.get("views"), "l": m.get("likes"), "c": m.get("comments"),
                 "s": m.get("shares"), "sv": m.get("saves"), "re": m.get("reach"), "sc": score(m)})
        n += 1
    if n:
        await learn(org_id)
    return n


async def learn(org_id: str) -> dict:
    """What worked for this business, from the 7-day numbers (24 h when nothing is 7 days old yet)."""
    async with tenant_session(org_id) as conn:
        tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
        rows = (await conn.execute(text("""select m.kind, m.ref_id::text, m.platform, m.score, m.at_hours,
              coalesce(mo.topic, v.topic) as topic, coalesce(mo.hook, v.plan->>'hook') as hook,
              coalesce(p.published_at, (v.publish->>'at')::timestamptz) as published_at
            from app.post_metrics m
            left join app.content_posts p on m.kind = 'post' and p.id = m.ref_id
            left join app.content_moments mo on mo.id = p.moment_id
            left join app.ai_videos v on m.kind = 'video' and v.id = m.ref_id
            where m.at_hours = (select coalesce(max(at_hours), 24) from app.post_metrics x where x.ref_id = m.ref_id)"""))).mappings().all()
        if not rows:
            return {}
        by_topic: dict[str, list[float]] = {}
        by_platform: dict[str, list[float]] = {}
        by_hour: dict[int, list[float]] = {}
        for r in rows:
            sc = float(r["score"])
            if r["topic"]:
                by_topic.setdefault(r["topic"], []).append(sc)
            by_platform.setdefault(r["platform"], []).append(sc)
            if r["published_at"]:
                by_hour.setdefault(r["published_at"].astimezone(ZoneInfo(tz)).hour, []).append(sc)
        avg = {k: sum(v) / len(v) for k, v in by_topic.items()}
        ranked = sorted(avg, key=lambda k: -avg[k])
        overall = sum(float(r["score"]) for r in rows) / len(rows)
        top = sorted(rows, key=lambda r: -float(r["score"]))
        learning = {"posts_measured": len(rows), "average_score": round(overall, 1),
                    "top_topics": [t for t in ranked if avg[t] >= overall][:5], "weak_topics": [t for t in reversed(ranked) if avg[t] < overall * 0.5][:5],
                    "best_platform": max(by_platform, key=lambda k: sum(by_platform[k]) / len(by_platform[k])),
                    "best_hour": max(by_hour, key=lambda k: sum(by_hour[k]) / len(by_hour[k])) if by_hour else None,
                    "top_hooks": [r["hook"] for r in top[:3] if r["hook"]], "updated": datetime.now(UTC).isoformat()}
        await conn.execute(text("update app.org_settings set profile = profile || jsonb_build_object('content_learning', cast(:l as jsonb))"),
                           {"l": json.dumps(learning)})
        cut = sorted((float(r["score"]) for r in rows), reverse=True)[max(0, len(rows) // 10 - 1)] if len(rows) >= 10 else None
        for r in rows:
            if cut is not None and r["at_hours"] == 168 and float(r["score"]) >= cut:
                seen = (await conn.execute(text("select 1 from app.events where type = 'content.top_post' and payload->>'ref_id' = :r"), {"r": r["ref_id"]})).first()
                if not seen:
                    await emit(conn, org_id, "content.top_post", {"ref_id": r["ref_id"], "kind": r["kind"], "score": float(r["score"]), "topic": r["topic"]})
    return learning


def _overlap(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"[a-z0-9]+", (a or "").lower())), set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    return len(wa & wb) / max(1, len(wa | wb))


def boost(candidates: list[dict], learning: dict | None) -> list[dict]:
    """Moment ranking learns from results: +2 for a topic like the business's best, -1 for one like its weakest."""
    if not learning:
        return candidates
    for m in candidates:
        if any(_overlap(m.get("topic", ""), t) >= 0.5 for t in learning.get("top_topics") or []):
            m["score"] = float(m.get("score", 0)) + 2
            m["learned"] = "a topic that did well before"
        elif any(_overlap(m.get("topic", ""), t) >= 0.5 for t in learning.get("weak_topics") or []):
            m["score"] = float(m.get("score", 0)) - 1
    return candidates


async def learning_of(conn: AsyncConnection) -> dict | None:
    return (await conn.execute(text("select profile->'content_learning' from app.org_settings"))).scalar_one_or_none()


async def engagement_jobs() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select distinct org_id from app.automation_instances where template_key in ('content_repurposing','video_studio')
            and status in ('live','approval_mode')"""))).scalars())
    return sum([await collect(o) for o in orgs])


@DBOS.step()
async def engagement_step() -> int:
    return await engagement_jobs()


@DBOS.workflow()
async def engagement_schedule(scheduled_time: datetime, context) -> None:
    await engagement_step()
