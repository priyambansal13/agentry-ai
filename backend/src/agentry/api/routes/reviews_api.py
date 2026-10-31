"""Reviews in the portal (9.2): the list with sentiment, topics and replies; check now; reply / skip; the month's numbers.

Conversation permission: owners, managers and front desk read and reply; finance and viewers don't.
"""
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, current_org
from agentry.automations import reviews as rv
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter(prefix="/org/reviews")


async def _ctx(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
    if not ctx.can("conversation", "read"):
        raise HTTPException(403, "reviews are for owners, managers and front desk")
    async with tenant_session(ctx.org_id) as conn:
        if "reviews" not in await enabled_automations(conn):
            raise HTTPException(404, "review management isn't switched on")
    return ctx


Reader = Annotated[OrgContext, Depends(_ctx)]


@router.get("")
async def list_reviews(ctx: Reader, filter: Literal["all", "unanswered", "low"] = "all", limit: Annotated[int, Query(ge=1, le=300)] = 100) -> dict:
    where = {"all": "true", "unanswered": "reply_status in ('none','drafted')", "low": "rating <= 2"}[filter]
    now = datetime.now(UTC)
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text(f"""select id::text, source, author, rating, body, reviewed_at, sentiment, topics, urgent, reply,
                reply_status, replied_at, approval_id::text from app.reviews where {where} order by reviewed_at desc limit :l"""), {"l": limit})).mappings().all()
        last30, prev30 = await rv.stats(conn, now - timedelta(days=30), now), await rv.stats(conn, now - timedelta(days=60), now - timedelta(days=30))
        all_time = (await conn.execute(text("select count(*), round(avg(rating)::numeric, 2) from app.reviews"))).one()
        asked = (await conn.execute(text("""select count(*) filter (where status in ('sent','recorded')) from app.review_requests
            where created_at > now() - interval '30 days'"""))).scalar_one()
        watcher = (await conn.execute(text("select last_checked_at, next_check_at, error from app.watchers where kind = 'reviews' limit 1"))).mappings().first()
        _st, cfg = await rv.settings_of(conn)
    return {"items": [dict(r) for r in rows], "last30": last30, "prev30": prev30, "total": all_time[0],
            "average": float(all_time[1]) if all_time[1] is not None else None, "asked_30d": asked, "watcher": dict(watcher) if watcher else None,
            "review_link": cfg.get("review_link"), "sample": rv.settings.reviews_source == "sample", "can_act": ctx.can("conversation", "act")}


@router.post("/sync")
async def sync_now(ctx: Reader) -> dict:
    if not ctx.can("conversation", "act"):
        raise HTTPException(403, "you can't do that")
    async with tenant_session(ctx.org_id) as conn:
        await rv.ensure_watcher(conn, ctx.org_id)
    return {"new": await rv.sync(ctx.org_id)}


class Reply(BaseModel):
    action: Literal["post", "skip"]
    body: Annotated[str | None, Field(max_length=4000)] = None


@router.put("/{rid}")
async def reply(rid: str, b: Reply, request: Request, ctx: Reader) -> dict:
    if not ctx.can("conversation", "act"):
        raise HTTPException(403, "you can't reply to reviews")
    async with tenant_session(ctx.org_id) as conn:
        row = (await conn.execute(text("select reply, reply_status, approval_id from app.reviews where id = cast(:i as uuid) for update"),
                                  {"i": rid})).mappings().first()
        if not row:
            raise HTTPException(404, "review not found")
        if row["reply_status"] == "posted":
            raise HTTPException(409, "a reply is already posted")
        if b.action == "post":
            body = (b.body or row["reply"] or "").strip()
            if not body:
                raise HTTPException(422, "write a reply first")
            await rv.post_reply(conn, ctx.org_id, rid, body, by=ctx.principal.user_id)
        else:
            await conn.execute(text("update app.reviews set reply_status = 'skipped' where id = cast(:i as uuid)"), {"i": rid})
        if row["approval_id"]:  # the Needs-you card for it is done
            await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
                where id = :a and status = 'pending'"""), {"u": ctx.principal.user_id, "a": row["approval_id"]})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action=f"review.{b.action}",
                           target_type="review", target_id=rid, ip=client_ip(request))
    return {"status": "posted" if b.action == "post" else "skipped"}
