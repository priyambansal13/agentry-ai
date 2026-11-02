"""Ops dispatcher in the portal (ROADMAP-V3 C2). The team that works conversations (conversation:act) dispatches."""
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import dispatcher as dp
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/dispatch", dependencies=[Depends(require_page("jobs"))])
Reader = Annotated[OrgContext, Depends(require("conversation", "read"))]
Worker = Annotated[OrgContext, Depends(require("conversation", "act"))]


@router.get("")
async def board(ctx: Reader, day: date | None = None) -> dict:
    day = day or datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        jobs = (await conn.execute(text("""select j.id::text, j.number, j.customer, j.phone, j.address, j.area, j.service, j.description, j.day, j.slot, j.status,
            j.technician_id::text, t.name as technician, t.phone as technician_phone, j.amount, j.photos, j.invoice_id::text, j.source, j.created_at
            from app.service_jobs j left join app.technicians t on t.id = j.technician_id
            where j.day = :d or (j.status in ('new','assigned') and j.day < :d) order by j.status = 'done', j.slot, j.number"""), {"d": day})).mappings().all()
        techs = (await conn.execute(text("""select t.id::text, t.name, t.phone, t.skills, t.areas, t.max_per_day, t.active,
            (select count(*) from app.service_jobs j where j.technician_id = t.id and j.day = :d and j.status <> 'cancelled') as today
            from app.technicians t order by t.active desc, t.name"""), {"d": day})).mappings().all()
        _s, cfg = await dp.settings_of(conn)
    return {"day": day, "jobs": [dict(j) | {"amount": float(j["amount"]) if j["amount"] is not None else None, "tech_message": dp.tech_message(dict(j))} for j in jobs],
            "technicians": [dict(t) for t in techs], "services": cfg["services"], "can_work": ctx.can("conversation", "act")}


class JobIn(BaseModel):
    customer: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Annotated[str | None, Field(max_length=20)] = None
    address: Annotated[str | None, Field(max_length=300)] = None
    area: Annotated[str | None, Field(max_length=80)] = None
    service: Annotated[str, Field(min_length=2, max_length=80)]
    description: Annotated[str | None, Field(max_length=1000)] = None
    day: date
    slot: Literal["morning", "afternoon", "evening", "any"] = "any"


@router.post("/jobs", status_code=201)
async def create(body: JobIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await dp.create_job(conn, ctx.org_id, **body.model_dump(), user_id=ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e


class JobEdit(BaseModel):
    status: Literal["new", "assigned", "on_the_way", "in_progress", "done", "cancelled"] | None = None
    technician_id: str | None = None
    day: date | None = None
    slot: Literal["morning", "afternoon", "evening", "any"] | None = None
    amount: Annotated[float | None, Field(ge=0)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None


@router.patch("/jobs/{jid}")
async def edit(jid: str, body: JobEdit, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await dp.update(conn, ctx.org_id, jid, body.model_dump(exclude_unset=True), ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e


@router.post("/jobs/{jid}/photos", status_code=201)
async def photo(jid: str, ctx: Worker, file: Annotated[UploadFile, File()]) -> dict:
    try:
        return {"path": await dp.add_photo(ctx.org_id, jid, await file.read(), file.filename)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class TechIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    phone: Annotated[str | None, Field(max_length=20)] = None
    skills: Annotated[list[str], Field(max_length=20)] = []
    areas: Annotated[list[str], Field(max_length=30)] = []
    max_per_day: Annotated[int, Field(ge=1, le=30)] = 5
    active: bool = True


@router.post("/technicians", status_code=201)
async def add_tech(body: TechIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        tid = (await conn.execute(text("""insert into app.technicians (org_id, name, phone, skills, areas, max_per_day, active) values (:o, :n, :p, :s, :a, :m, :ac)
            returning id::text"""), {"o": ctx.org_id, "n": body.name, "p": body.phone, "s": body.skills, "a": body.areas, "m": body.max_per_day, "ac": body.active})).scalar_one()
    return {"id": tid}


@router.patch("/technicians/{tid}")
async def edit_tech(tid: str, body: TechIn, ctx: Worker) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""update app.technicians set name = :n, phone = :p, skills = :s, areas = :a, max_per_day = :m, active = :ac where id = cast(:i as uuid)"""),
                           {"n": body.name, "p": body.phone, "s": body.skills, "a": body.areas, "m": body.max_per_day, "ac": body.active, "i": tid})
    return {"id": tid}
