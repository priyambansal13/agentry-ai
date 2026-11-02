"""AI video studio in the portal: the videos, making one now, fixing a plan, approving, publishing, the file.

Same people as content: front desk and up see them; owners and managers make, edit, approve and publish.
"""
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, require
from agentry.automations import video_studio as vs
from agentry.automations.video_studio import gen
from agentry.connectors.store import get_connection
from agentry.db import tenant_session
from agentry.events import emit
from agentry.features import require_page

router = APIRouter(prefix="/org/videos", dependencies=[Depends(require_page("videos"))])
Viewer = Annotated[OrgContext, Depends(require("conversation", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]
COLS = "id::text, status, trigger, slot, topic, plan, checks, ops, model, seconds, cost_usd, path is not null as has_file, publish, error, created_at, updated_at"


@router.get("")
async def videos(ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        status, cfg = await vs.settings_of(conn)
        rows = (await conn.execute(text(f"select {COLS} from app.ai_videos order by created_at desc limit 100"))).mappings().all()
        spent = await vs.spent_this_month(conn, datetime.now(UTC))
    yt = await get_connection(ctx.org_id, "youtube")
    return {"items": [dict(r) for r in rows], "status": status, "test_mode": gen.test_mode(cfg["provider"]), "youtube": (yt or {}).get("display_name"),
            "provider": cfg["provider"], "model": gen.model_name(cfg["provider"], cfg["quality"]),
            "spent": round(spent, 2), "budget": cfg["monthly_budget_usd"], "estimate": vs.estimate(cfg),
            "schedule": {"days": cfg["days"], "time": cfg["time"]}, "can_edit": ctx.can("automation", "configure")}


async def _video(conn, vid: str) -> dict:
    v = (await conn.execute(text(f"select {COLS} from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().first()
    if not v:
        raise HTTPException(404, "video not found")
    return dict(v)


@router.get("/{vid}")
async def video(vid: str, ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        return await _video(conn, vid)


class MakeIn(BaseModel):
    topic: Annotated[str | None, Field(max_length=200)] = None


@router.post("", status_code=202)
async def make(body: MakeIn, ctx: Editor) -> dict:
    if not vs.available():
        raise HTTPException(503, "ffmpeg isn't installed on the server")
    async with tenant_session(ctx.org_id) as conn:
        busy = (await conn.execute(text("select count(*) from app.ai_videos where status in ('planning','generating','composing')"))).scalar_one()
        if busy >= 3:
            raise HTTPException(429, "three videos are already being made: wait for one to finish")
        vid = await vs.request(conn, ctx.org_id, topic=body.topic, user_id=ctx.principal.user_id)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="video.requested",
                           target_type="ai_video", target_id=vid, metadata={"topic": body.topic})
    return {"id": vid}


class PlanEdit(BaseModel):
    title: Annotated[str, Field(min_length=3, max_length=100)]
    description: Annotated[str, Field(max_length=4500)] = ""
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    hook: Annotated[str, Field(max_length=80)] = ""
    scenes: Annotated[list[dict], Field(min_length=1, max_length=4)] | None = None


@router.patch("/{vid}")
async def edit(vid: str, body: PlanEdit, ctx: Editor) -> dict:
    """Edit the title, description, hashtags and hook (any time before publishing); the scenes only before generating."""
    async with tenant_session(ctx.org_id) as conn:
        v = await _video(conn, vid)
        if v["status"] in ("published", "publishing"):
            raise HTTPException(409, "already published")
        plan = dict(v["plan"] or {})
        plan.update(title=body.title, description=body.description, hook=body.hook,
                    hashtags=["#Shorts"] + [h if h.startswith("#") else f"#{h}" for h in body.hashtags if h.strip("#").lower() != "shorts"][:5])
        if body.scenes is not None:
            if v["status"] != "needs_attention":
                raise HTTPException(409, "the scenes can only change before the video is generated")
            plan["scenes"] = [{"prompt": str(s.get("prompt", ""))[:1500], "caption": str(s.get("caption", ""))[:80]} for s in body.scenes]
        await conn.execute(text("update app.ai_videos set plan = cast(:p as jsonb), updated_at = now() where id = cast(:i as uuid)"),
                           {"p": json.dumps(plan), "i": vid})
    return {"id": vid, "plan": plan}


@router.post("/{vid}/generate", status_code=202)
async def generate(vid: str, ctx: Editor) -> dict:
    """A plan that needed attention, accepted (after editing) by a person: generate it now."""
    async with tenant_session(ctx.org_id) as conn:
        _s, cfg = await vs.settings_of(conn)
        v = await _video(conn, vid)
        if v["status"] != "needs_attention":
            raise HTTPException(409, "only a plan that needs attention can be generated this way")
        if len(v["plan"].get("scenes") or []) < 1:
            raise HTTPException(422, "the plan has no scenes")
        cost = 0 if gen.test_mode(cfg["provider"]) else round(len(v["plan"]["scenes"]) * vs.SCENE_S * gen.rate(cfg), 2)
        await conn.execute(text("""update app.ai_videos set status = 'generating', error = null, cost_usd = :c, seconds = :s, model = :m
            where id = cast(:i as uuid)"""), {"c": cost, "s": len(v["plan"]["scenes"]) * vs.SCENE_S, "m": gen.model_name(cfg["provider"], cfg["quality"]), "i": vid})
        await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
            where kind = 'video_review' and status = 'pending' and payload->>'video_id' = :v"""), {"u": ctx.principal.user_id, "v": vid})
        await emit(conn, ctx.org_id, "video.plan_approved", {"video_id": vid})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="video.plan_approved",
                           target_type="ai_video", target_id=vid)
    return {"id": vid, "status": "generating"}


@router.post("/{vid}/replan", status_code=202)
async def replan(vid: str, ctx: Editor) -> dict:
    """Plan it again from scratch (the models were busy, or the plan wasn't good)."""
    async with tenant_session(ctx.org_id) as conn:
        v = await _video(conn, vid)
        if v["status"] not in ("needs_attention", "failed", "skipped"):
            raise HTTPException(409, f"a video that is {v['status'].replace('_', ' ')} can't be planned again")
        await conn.execute(text("""update app.ai_videos set status = 'planning', plan = '{}', checks = '[]', ops = '[]', path = null, error = null,
            cost_usd = 0 where id = cast(:i as uuid)"""), {"i": vid})
        await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
            where kind = 'video_review' and status = 'pending' and payload->>'video_id' = :v"""), {"u": ctx.principal.user_id, "v": vid})
        await emit(conn, ctx.org_id, "video.requested", {"video_id": vid, "trigger": "replan"})
    return {"id": vid, "status": "planning"}


@router.post("/{vid}/publish")
async def publish(vid: str, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        v = await _video(conn, vid)
        if v["status"] not in ("review",):
            raise HTTPException(409, f"a video that is {v['status'].replace('_', ' ')} can't be published")
        await conn.execute(text("update app.ai_videos set status = 'publishing' where id = cast(:i as uuid)"), {"i": vid})
        await conn.execute(text("""update app.approvals set status = 'approved', decided_by = :u, decided_at = now()
            where kind = 'video_review' and status = 'pending' and payload->>'video_id' = :v"""), {"u": ctx.principal.user_id, "v": vid})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="video.published",
                           target_type="ai_video", target_id=vid)
    r = await vs.publish(ctx.org_id, vid)
    if r.get("error"):
        raise HTTPException(409, r["error"])
    return r


@router.post("/{vid}/reject")
async def reject(vid: str, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        v = await _video(conn, vid)
        if v["status"] in ("published", "publishing"):
            raise HTTPException(409, "already published: delete it on YouTube")
        await conn.execute(text("update app.ai_videos set status = 'rejected' where id = cast(:i as uuid)"), {"i": vid})
        await conn.execute(text("""update app.approvals set status = 'rejected', decided_by = :u, decided_at = now()
            where kind = 'video_review' and status = 'pending' and payload->>'video_id' = :v"""), {"u": ctx.principal.user_id, "v": vid})
    return {"id": vid, "status": "rejected"}


@router.get("/{vid}/file")
async def file(vid: str, ctx: Viewer) -> FileResponse:
    async with tenant_session(ctx.org_id) as conn:
        rel = (await conn.execute(text("select path from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).scalar_one_or_none()
    p = vs.resolve(rel)
    if not p:
        raise HTTPException(404, "no video yet")
    return FileResponse(p, media_type="video/mp4", filename=f"video-{vid[:8]}.mp4", content_disposition_type="inline",
                        headers={"Cache-Control": "private, max-age=60"})
