"""Hiring assistant in the portal (ROADMAP-V3 A5). Owners and managers (automation:configure) run hiring."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import hiring as hr
from agentry.config import settings
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/hiring", dependencies=[Depends(require_page("hiring"))])
Hirer = Annotated[OrgContext, Depends(require("automation", "configure"))]


def _apply_link(token: str) -> str:
    return f"{settings.api_public_url.rstrip('/')}/public/jobs/{token}"


@router.get("/jobs")
async def jobs(ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select j.id::text, j.title, j.location, j.kind, j.status, j.token, j.created_at,
            count(c.id) as candidates, count(c.id) filter (where c.verdict = 'strong') as strong, count(c.id) filter (where c.status = 'new') as unseen
            from app.jobs j left join app.candidates c on c.job_id = j.id group by j.id order by j.status = 'closed', j.created_at desc"""))).mappings().all()
    return {"items": [{k: v for k, v in dict(r).items() if k != "token"} | {"apply_link": _apply_link(r["token"])} for r in rows]}


class JobIn(BaseModel):
    title: Annotated[str, Field(min_length=2, max_length=120)]
    description: Annotated[str, Field(min_length=20, max_length=5000)]
    must_have: Annotated[list[str], Field(max_length=12)] = []
    location: Annotated[str | None, Field(max_length=120)] = None
    kind: Literal["full_time", "part_time", "internship", "contract"] = "full_time"


@router.post("/jobs", status_code=201)
async def create_job(body: JobIn, ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        jid = await hr.create_job(conn, ctx.org_id, title=body.title, description=body.description, must_have=body.must_have, location=body.location,
                                  kind=body.kind, user_id=ctx.principal.user_id)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": ctx.org_id})).scalar_one_or_none() or ""
    post = await hr.write_post(ctx.org_id, body.model_dump(), business)
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.jobs set post = :p where id = cast(:i as uuid)"), {"p": post, "i": jid})
    return {"id": jid}


@router.get("/jobs/{jid}")
async def job(jid: str, ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        j = (await conn.execute(text("select * from app.jobs where id = cast(:i as uuid)"), {"i": jid})).mappings().first()
        if not j:
            raise HTTPException(404, "job not found")
        cands = (await conn.execute(text("""select id::text, name, email, phone, source, score, verdict, status, interview_at, assessment->>'summary' as summary,
            created_at from app.candidates where job_id = cast(:i as uuid) order by score desc nulls last, created_at"""), {"i": jid})).mappings().all()
    return {k: v for k, v in dict(j).items() if k not in ("org_id", "token")} | {"id": jid, "apply_link": _apply_link(j["token"]),
                                                                             "candidates": [dict(c) for c in cands]}


class JobStatus(BaseModel):
    status: Literal["open", "paused", "closed"]


@router.patch("/jobs/{jid}")
async def job_status(jid: str, body: JobStatus, ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.jobs set status = :s where id = cast(:i as uuid)"), {"s": body.status, "i": jid})
    return {"id": jid, "status": body.status}


@router.post("/jobs/{jid}/candidates", status_code=201)
async def upload(jid: str, ctx: Hirer, files: Annotated[list[UploadFile], File()]) -> dict:
    out, errors = [], []
    for f in files[:30]:
        data = await f.read()
        if len(data) > 5 * 1024 * 1024:
            errors.append(f"{f.filename}: over 5 MB")
            continue
        try:
            out.append(await hr.add_candidate(ctx.org_id, jid, data, f.filename or "cv.pdf"))
        except ValueError as e:
            errors.append(f"{f.filename}: {e}")
    return {"added": out, "errors": errors}


@router.get("/candidates/{cid}")
async def candidate(cid: str, ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("""select c.*, j.title as job_title, j.must_have from app.candidates c join app.jobs j on j.id = c.job_id
            where c.id = cast(:i as uuid)"""), {"i": cid})).mappings().first()
    if not c:
        raise HTTPException(404, "candidate not found")
    return {k: v for k, v in dict(c).items() if k not in ("org_id", "path", "cv_text")} | {"id": cid, "job_id": str(c["job_id"])}


@router.get("/candidates/{cid}/cv")
async def cv(cid: str, ctx: Hirer) -> FileResponse:
    from pathlib import Path
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select path, filename from app.candidates where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
    if not c or not c["path"]:
        raise HTTPException(404, "no CV")
    return FileResponse(Path(settings.documents_dir) / c["path"], filename=c["filename"])


class Stage(BaseModel):
    status: Literal["new", "shortlisted", "interview", "offered", "hired", "rejected"]
    interview_at: datetime | None = None


@router.post("/candidates/{cid}/stage")
async def stage(cid: str, body: Stage, ctx: Hirer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await hr.set_stage(conn, ctx.org_id, cid, body.status, interview_at=body.interview_at, user_id=ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
