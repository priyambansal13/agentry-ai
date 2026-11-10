"""AI visibility in the portal. Owners and managers set it up and run checks (automation:configure); others read."""
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import ai_search
from agentry.auth import OrgContext, require
from agentry.automations import ai_visibility as vis
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/ai-visibility", dependencies=[Depends(require_page("ai-visibility"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]


@router.get("")
async def overview(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        setup = await vis.setup_of(conn, ctx.org_id)
        runs = (await conn.execute(text("""select id::text, trigger, status, score, cost_usd, mock, error, created_at, finished_at
            from app.ai_vis_runs order by created_at desc limit 13"""))).mappings().all()
        month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        manual = (await conn.execute(text("select count(*) from app.ai_vis_runs where trigger = 'manual' and created_at >= :m"), {"m": month})).scalar_one()
    engines, mock = ai_search.active()
    latest = next((dict(r) for r in runs if r["status"] == "done"), None)
    return {
        "setup": {k: setup[k] for k in ("config", "business", "website", "city", "service", "competitors", "questions")},
        "ready": vis.missing_setup(setup) is None, "missing": vis.missing_setup(setup),
        "engines": [{"key": k, "label": ai_search.LABEL.get(k, k)} for k in engines], "test_mode": mock,
        "latest": latest, "running": next((dict(r) for r in runs if r["status"] in ("queued", "running")), None),
        "history": [{"id": r["id"], "at": r["created_at"], "rate": (r["score"] or {}).get("rate"), "status": r["status"], "trigger": r["trigger"]}
                    for r in reversed(runs) if r["status"] in ("done", "failed")],
        "manual_left": max(0, vis.MANUAL_PER_MONTH - manual), "can_edit": ctx.can("automation", "configure"),
    }


class SetupIn(BaseModel):
    service: Annotated[str | None, Field(max_length=80)] = None
    city: Annotated[str | None, Field(max_length=80)] = None
    area: Annotated[str | None, Field(max_length=80)] = None
    other_names: Annotated[list[Annotated[str, Field(max_length=120)]] | None, Field(max_length=6)] = None
    competitors: Annotated[list[Annotated[str, Field(max_length=200)]] | None, Field(max_length=8)] = None
    questions: Annotated[list[Annotated[str, Field(max_length=200)]] | None, Field(max_length=20)] = None
    monthly: bool | None = None


@router.put("/setup")
async def save_setup(body: SetupIn, ctx: Editor) -> dict:
    new = body.model_dump(exclude_unset=True)
    for k in ("other_names", "competitors", "questions"):
        if k in new and new[k] is not None:
            new[k] = [x.strip() for x in new[k] if x and x.strip()]
    async with tenant_session(ctx.org_id) as conn:
        row = (await conn.execute(text("select id, config from app.automation_instances where template_key = 'ai_visibility'"))).first()
        if not row:
            raise HTTPException(404, "AI visibility isn't switched on for this business")
        cfg = vis.VisConfig(**{**(row.config or {}), **new}).model_dump()
        await conn.execute(text("update app.automation_instances set config = cast(:c as jsonb) where id = :i"),
                           {"c": json.dumps(cfg), "i": row.id})
        setup = await vis.setup_of(conn, ctx.org_id)
    return {"config": cfg, "questions": setup["questions"], "competitors": setup["competitors"], "missing": vis.missing_setup(setup)}


@router.post("/check", status_code=201)
async def check_now(ctx: Editor) -> dict:
    try:
        return {"run_id": await vis.start_check(ctx.org_id, trigger="manual", created_by=ctx.principal.user_id)}
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/runs/{rid}")
async def get_run(rid: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        run = (await conn.execute(text("select id::text, trigger, status, setup, score, cost_usd, mock, error, created_at, finished_at from app.ai_vis_runs where id = cast(:i as uuid)"),
                                  {"i": rid})).mappings().first()
        if not run:
            raise HTTPException(404, "check not found")
        answers = (await conn.execute(text("""select engine, question, repeat, answer, citations, named, me_position, error
            from app.ai_vis_answers where run_id = cast(:i as uuid) order by question, engine, repeat"""), {"i": rid})).mappings().all()
    return {**dict(run), "answers": [dict(a) for a in answers]}


class WriteIn(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=200)]


@router.post("/write-page", status_code=201)
async def write_page(body: WriteIn, ctx: Editor) -> dict:
    """An answer page for a question the business wasn't named for, drafted by Local SEO (when the client has it)."""
    async with tenant_session(ctx.org_id) as conn:
        has_seo = (await conn.execute(text("select count(*) from app.automation_instances where template_key = 'local_seo'"))).scalar_one()
    if not has_seo:
        raise HTTPException(409, "answer pages are written by Local SEO, which isn't switched on for this business")
    from agentry.automations import local_seo
    try:
        return await local_seo.write_article(ctx.org_id, body.question)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
