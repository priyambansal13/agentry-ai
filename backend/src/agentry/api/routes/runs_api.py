"""Agent runs in the portal (what each agent did, step by step) and in HQ (cost per agent per client)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from agentry.auth import OrgContext, Principal, current_org, require_staff
from agentry.db import tenant_session

router = APIRouter()


@router.get("/org/runs")
async def recent_runs(ctx: Annotated[OrgContext, Depends(current_org)], agent: str | None = None,
                      limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
    """Recent runs. Costs are Agentry's business: only Agentry staff see them."""
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id, agent, kind, subject_type, subject_id, status, steps, error, model_calls, cost_usd,
                started_at, ended_at, extract(epoch from coalesce(ended_at, now()) - started_at) as seconds
            from app.agent_runs where (cast(:a as text) is null or agent = :a) order by started_at desc limit :l"""),
            {"a": agent, "l": limit})).mappings().all()
    staff = ctx.principal.is_staff
    return {"items": [{k: v for k, v in dict(r).items() if staff or k not in ("cost_usd", "model_calls")} for r in rows]}


@router.get("/hq/orgs/{org_id}/agent-costs")
async def agent_costs(org_id: str, _: Annotated[Principal, Depends(require_staff)], days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select agent, count(*) as runs, count(*) filter (where status = 'failed') as failed,
                round(avg(extract(epoch from ended_at - started_at))::numeric, 1) as avg_seconds, sum(cost_usd) as cost_usd,
                sum(input_tokens + output_tokens) as tokens
            from app.agent_runs where started_at > now() - make_interval(days => :d) group by agent order by sum(cost_usd) desc"""),
            {"d": days})).mappings().all()
        loose = (await conn.execute(text("""select coalesce(sum(cost_usd), 0) from app.llm_calls where run_id is null
            and at > now() - make_interval(days => :d)"""), {"d": days})).scalar_one()
    return {"days": days, "agents": [dict(r) | {"cost_usd": float(r["cost_usd"] or 0), "cost_per_run": round(float(r["cost_usd"] or 0) / r["runs"], 5)}
                                     for r in rows], "outside_runs_usd": float(loose)}
