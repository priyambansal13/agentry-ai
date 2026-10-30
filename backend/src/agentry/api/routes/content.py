"""Content repurposing in the portal (Phase 6.1-6.4): uploads, the review board, brand kit, calendar, images.

Who can do what: owners and managers upload, approve, edit, schedule and change the brand kit (automation:configure);
front desk can look (conversation:read); finance and viewers don't see content.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, require
from agentry.automations.content import brand, calendar, pipeline, sources
from agentry.db import tenant_session
from agentry.events import emit
from agentry.features import require_page

router = APIRouter(prefix="/org/content", dependencies=[Depends(require_page("content"))])
Viewer = Annotated[OrgContext, Depends(require("conversation", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]
MAX_UPLOAD = 500 * 1024 * 1024


async def _record(conn, ctx: OrgContext, request: Request, action: str, target: str, **meta: object) -> None:
    await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action=f"content.{action}",
                       target_type="content", target_id=target, ip=client_ip(request), metadata=meta)


# ---------- sources ----------

@router.get("/sources")
async def list_sources(ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select s.id, s.title, s.kind, s.status, s.error, s.progress, s.created_at, s.ready_at,
                (s.transcript->>'duration_seconds')::int as duration_seconds,
                (select count(*) from app.content_posts p where p.source_id = s.id) as posts,
                (select count(*) from app.content_posts p where p.source_id = s.id and p.review in ('pending','needs_attention')) as to_review,
                (select count(*) from app.content_posts p where p.source_id = s.id and p.review = 'approved') as approved,
                (select count(*) from app.content_posts p where p.source_id = s.id and p.published_at is not null) as published
            from app.content_sources s order by s.created_at desc"""))).mappings().all()
    return {"items": [dict(r) for r in rows], "can_edit": ctx.can("automation", "configure")}


async def _new_source(conn, ctx: OrgContext, request: Request, title: str, kind: str, transcript: dict | None = None) -> str:
    sid = str((await conn.execute(text("""insert into app.content_sources (org_id, title, kind, transcript, created_by)
        values (:o, :t, :k, cast(:tr as jsonb), :u) returning id"""),
        {"o": ctx.org_id, "t": title, "k": kind, "tr": json.dumps(transcript) if transcript else None, "u": ctx.principal.user_id})).scalar_one())
    await _record(conn, ctx, request, "source_added", sid, title=title, kind=kind)
    return sid


@router.post("/sources", status_code=201)
async def upload(request: Request, ctx: Editor, file: Annotated[UploadFile, File()], title: Annotated[str, Form(min_length=2, max_length=200)],
                 owns_rights: Annotated[bool, Form()] = False) -> dict:
    """A video, audio file or transcript (SRT, VTT, TXT) the business owns."""
    if not owns_rights:
        raise HTTPException(422, "confirm the business owns this recording (or has the rights to post from it)")
    kind = sources.kind_of(file.filename or "")
    if not kind:
        raise HTTPException(422, "upload a video (MP4, MOV…), audio (MP3, M4A, WAV…) or transcript (SRT, VTT, TXT)")
    async with tenant_session(ctx.org_id) as conn:
        sid = await _new_source(conn, ctx, request, title, kind)
    path = sources.folder(ctx.org_id, sid) / f"source{Path(file.filename or '').suffix.lower()}"
    size = 0
    with path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                sources.remove_files(ctx.org_id, sid)
                async with tenant_session(ctx.org_id) as conn:
                    await conn.execute(text("delete from app.content_sources where id = cast(:i as uuid)"), {"i": sid})
                raise HTTPException(413, "file too large (max 500 MB)")
            out.write(chunk)
    transcript = None
    if kind == "transcript":
        try:
            transcript = sources.parse_transcript(path.read_text(errors="ignore"), file.filename or "")
        except sources.TranscribeError as e:
            raise HTTPException(422, str(e)) from e
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""update app.content_sources set file_path = :p, file_bytes = :b, transcript = cast(:t as jsonb)
            where id = cast(:i as uuid)"""), {"p": sources.relative(path), "b": size, "t": json.dumps(transcript) if transcript else None, "i": sid})
        await emit(conn, ctx.org_id, "content.source_added", {"source_id": sid})
    return {"id": sid, "kind": kind}


@router.post("/sources/sample", status_code=201)
async def sample(request: Request, ctx: Editor) -> dict:
    """Try it without an upload: a 45-minute clinic podcast (mock-data/content)."""
    t = sources.sample_transcript()
    async with tenant_session(ctx.org_id) as conn:
        sid = await _new_source(conn, ctx, request, t.pop("title"), "sample", t)
        await emit(conn, ctx.org_id, "content.source_added", {"source_id": sid})
    return {"id": sid, "kind": "sample"}


@router.post("/sources/{sid}/retry")
async def retry(sid: str, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.content_sources set status = 'uploaded', error = null,
            progress = progress || jsonb_build_object('attempt', coalesce((progress->>'attempt')::int, 0) + 1)
            where id = cast(:i as uuid) and status = 'failed' returning (progress->>'attempt')::int"""), {"i": sid})).scalar_one_or_none()
        if n is None:
            raise HTTPException(409, "only a failed upload can be retried")
        await emit(conn, ctx.org_id, "content.source_added", {"source_id": sid, "attempt": n})
        await _record(conn, ctx, request, "source_retried", sid)
    return {"id": sid, "status": "uploaded"}


@router.delete("/sources/{sid}")
async def delete_source(sid: str, request: Request, ctx: Editor) -> dict:
    """The recording, its transcript, moments, posts and images are deleted (published posts stay on the platforms)."""
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("delete from app.content_sources where id = cast(:i as uuid)"), {"i": sid})).rowcount
        if not n:
            raise HTTPException(404, "not found")
        await _record(conn, ctx, request, "source_deleted", sid)
    sources.remove_files(ctx.org_id, sid)
    return {"deleted": True}


POST_SQL = """select p.id, p.platform, p.body, p.hashtags, p.critic, p.review, p.edited, p.scheduled_at, p.published_at, p.publish_ref,
    p.publish_error, p.moment_id, p.source_id, (p.image_path is not null) as has_image, m.rank, m.quote, m.speaker, m.hook, m.start_s, m.end_s,
    m.topic, s.title as source_title from app.content_posts p join app.content_moments m on m.id = p.moment_id
    join app.content_sources s on s.id = p.source_id"""


@router.get("/sources/{sid}")
async def get_source(sid: str, ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        s = (await conn.execute(text("""select id, title, kind, status, error, progress, created_at, ready_at, cost_usd,
            (transcript->>'duration_seconds')::int as duration_seconds, jsonb_array_length(coalesce(transcript->'segments', '[]')) as segments
            from app.content_sources where id = cast(:i as uuid)"""), {"i": sid})).mappings().first()
        if not s:
            raise HTTPException(404, "not found")
        ms = (await conn.execute(text("""select id, rank, start_s, end_s, quote, speaker, hook, insight, topic, score, dropped
            from app.content_moments where source_id = cast(:i as uuid) order by rank"""), {"i": sid})).mappings().all()
        posts = (await conn.execute(text(POST_SQL + " where p.source_id = cast(:i as uuid) order by m.rank, p.platform"), {"i": sid})).mappings().all()
        kit = await brand.get_kit(conn, ctx.org_id)
    return {**dict(s), "moments": [dict(m) for m in ms], "posts": [dict(p) for p in posts], "platforms": kit["platforms"],
            "can_edit": ctx.can("automation", "configure")}


# ---------- review ----------

class PostAction(BaseModel):
    action: Literal["approve", "drop", "reopen", "regenerate"]
    body: Annotated[str | None, Field(min_length=5, max_length=3000)] = None


@router.post("/posts/{pid}")
async def review_post(pid: str, b: PostAction, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        p = (await conn.execute(text("""select p.id, p.review, p.body, p.platform, p.moment_id, p.source_id, p.published_at, s.transcript
            from app.content_posts p join app.content_sources s on s.id = p.source_id where p.id = cast(:i as uuid) for update of p"""),
            {"i": pid})).mappings().first()
        if not p:
            raise HTTPException(404, "not found")
        if p["published_at"]:
            raise HTTPException(409, "already published")
        if b.action == "regenerate":
            kit = await brand.get_kit(conn, ctx.org_id)
            d = await pipeline.write_one(conn, ctx.org_id, str(p["moment_id"]), p["platform"], kit, p["transcript"])
            await _record(conn, ctx, request, "post_regenerated", pid)
            return {"id": pid, "review": "pending" if d["ok"] else "needs_attention"}
        body = (b.body or "").strip() or None
        edited = bool(body and body != p["body"].strip())
        if b.action == "approve" and p["review"] == "needs_attention" and not edited:
            raise HTTPException(409, "This draft didn't pass the checks: edit it before approving, or regenerate or drop it.")
        status = {"approve": "approved", "drop": "dropped", "reopen": "pending"}[b.action]
        await conn.execute(text("""update app.content_posts set review = :s, body = coalesce(:b, body), edited = edited or :e,
            critic = case when :e then critic || '{"ok": true, "edited_by_person": true}'::jsonb else critic end,
            scheduled_at = case when :s = 'approved' then scheduled_at else null end,
            reviewed_by = :u, reviewed_at = now(), updated_at = now() where id = cast(:i as uuid)"""),
            {"s": status, "b": body if edited else None, "e": edited, "u": ctx.principal.user_id, "i": pid})
        await _record(conn, ctx, request, f"post_{status}", pid, edited=edited)
    return {"id": pid, "review": status, "edited": edited}


@router.post("/sources/{sid}/approve-ready")
async def approve_ready(sid: str, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.content_posts set review = 'approved', reviewed_by = :u, reviewed_at = now(), updated_at = now()
            where source_id = cast(:i as uuid) and review = 'pending'"""), {"u": ctx.principal.user_id, "i": sid})).rowcount
        await _record(conn, ctx, request, "bulk_approved", sid, approved=n)
    return {"approved": n}


@router.post("/moments/{mid}/drop")
async def drop_moment(mid: str, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.content_moments set dropped = true where id = cast(:i as uuid)"), {"i": mid})
        n = (await conn.execute(text("""update app.content_posts set review = 'dropped', scheduled_at = null, updated_at = now()
            where moment_id = cast(:i as uuid) and published_at is null"""), {"i": mid})).rowcount
        await _record(conn, ctx, request, "moment_dropped", mid, posts=n)
    return {"dropped_posts": n}


@router.get("/posts/{pid}/image")
async def post_image(pid: str, ctx: Viewer) -> FileResponse:
    async with tenant_session(ctx.org_id) as conn:
        rel = (await conn.execute(text("select image_path from app.content_posts where id = cast(:i as uuid)"), {"i": pid})).scalar_one_or_none()
    path = sources.resolve(rel)
    if not path:
        raise HTTPException(404, "no image")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


# ---------- calendar ----------

class ScheduleReq(BaseModel):
    source_id: str | None = None


@router.post("/schedule")
async def schedule_posts(b: ScheduleReq, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none()
        n = await calendar.schedule(conn, tz, b.source_id)
        await _record(conn, ctx, request, "scheduled", b.source_id or "all", posts=n)
    return {"scheduled": n}


@router.get("/calendar")
async def get_calendar(ctx: Viewer, days: Annotated[int, Query(ge=1, le=120)] = 30) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
        rows = (await conn.execute(text(POST_SQL + """ where p.review = 'approved' and p.scheduled_at is not null
            and p.scheduled_at >= now() - interval '7 days' and p.scheduled_at < now() + make_interval(days => :d) order by p.scheduled_at"""),
            {"d": days})).mappings().all()
        waiting = (await conn.execute(text("select count(*) from app.content_posts where review = 'approved' and scheduled_at is null"))).scalar_one()
    return {"timezone": tz, "items": [dict(r) for r in rows], "approved_unscheduled": waiting, "can_edit": ctx.can("automation", "configure")}


class Slot(BaseModel):
    scheduled_at: datetime | None


@router.patch("/posts/{pid}/slot")
async def move_post(pid: str, b: Slot, request: Request, ctx: Editor) -> dict:
    if b.scheduled_at and b.scheduled_at < datetime.now(b.scheduled_at.tzinfo) - timedelta(minutes=1):
        raise HTTPException(422, "choose a time in the future")
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.content_posts set scheduled_at = :t, updated_at = now()
            where id = cast(:i as uuid) and review = 'approved' and published_at is null"""), {"t": b.scheduled_at, "i": pid})).rowcount
        if not n:
            raise HTTPException(409, "only approved posts that aren't published yet can be moved")
        await _record(conn, ctx, request, "post_moved", pid, to=b.scheduled_at.isoformat() if b.scheduled_at else None)
    return {"id": pid, "scheduled_at": b.scheduled_at}


# ---------- brand kit ----------

class Kit(BaseModel):
    primary_color: Annotated[str | None, Field(pattern=r"^#[0-9a-fA-F]{6}$")] = None
    accent_color: Annotated[str | None, Field(pattern=r"^#[0-9a-fA-F]{6}$")] = None
    template: Literal["bold", "light", "split"] | None = None
    handle: Annotated[str | None, Field(max_length=60)] = None
    platforms: list[Literal["linkedin", "instagram", "x"]] | None = None
    moments_per_source: Annotated[int | None, Field(ge=3, le=20)] = None


@router.get("/brand")
async def get_brand(ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        kit = await brand.get_kit(conn, ctx.org_id)
    return {**kit, "has_logo": bool(brand.logo_path(kit)), "can_edit": ctx.can("automation", "configure")}


@router.put("/brand")
async def put_brand(b: Kit, request: Request, ctx: Editor) -> dict:
    changes = b.model_dump(exclude_none=True)
    if "platforms" in changes and not changes["platforms"]:
        raise HTTPException(422, "keep at least one platform")
    async with tenant_session(ctx.org_id) as conn:
        await brand.get_kit(conn, ctx.org_id)
        if changes:
            await conn.execute(text("update app.brand_kits set " + ", ".join(f"{k} = :{k}" for k in changes) + ", updated_at = now()"), changes)
        redrawn = await brand.rerender_all(conn, ctx.org_id) if {"primary_color", "accent_color", "template", "handle"} & set(changes) else 0
        await _record(conn, ctx, request, "brand_changed", ctx.org_id, fields=sorted(changes))
    return {"saved": sorted(changes), "images_redrawn": redrawn}


@router.post("/brand/logo")
async def upload_logo(request: Request, ctx: Editor, file: Annotated[UploadFile, File()]) -> dict:
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "logo too large (max 2 MB)")
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(422, "upload a PNG or JPG image") from e
    img.thumbnail((800, 800))
    path = sources.folder(ctx.org_id, "brand") / "logo.png"
    img.save(path, "PNG")
    async with tenant_session(ctx.org_id) as conn:
        await brand.get_kit(conn, ctx.org_id)
        await conn.execute(text("update app.brand_kits set logo_path = :p, updated_at = now()"), {"p": sources.relative(path)})
        redrawn = await brand.rerender_all(conn, ctx.org_id)
        await _record(conn, ctx, request, "logo_uploaded", ctx.org_id)
    return {"saved": True, "images_redrawn": redrawn}


class VoiceIn(BaseModel):
    posts: Annotated[str, Field(min_length=50, max_length=60000)]


@router.post("/brand/voice")
async def learn_voice(b: VoiceIn, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await brand.get_kit(conn, ctx.org_id)
        r = await brand.learn_voice(conn, ctx.org_id, b.posts)
        await _record(conn, ctx, request, "voice_learned", ctx.org_id, samples=r["samples"])
    return r


@router.get("/brand/preview")
async def preview(ctx: Viewer, platform: Literal["linkedin", "instagram", "x"] = "instagram") -> Response:
    """A sample card with the current brand kit."""
    from agentry.automations.content import images
    async with tenant_session(ctx.org_id) as conn:
        kit = await brand.get_kit(conn, ctx.org_id)
    png = images.render(platform, "The best time to fix a small problem is before it becomes a big one.", "Your name here", kit, brand.logo_path(kit))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
