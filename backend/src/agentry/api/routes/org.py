"""Endpoints scoped to one client organisation. Every query runs inside tenant_session (row-level security)."""
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, current_org, require
from agentry.db import tenant_session
from agentry.events import emit
from agentry.features import org_features
from agentry.metrics import registry

router = APIRouter(prefix="/org", tags=["organisation"])


@router.get("")
async def get_org(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        settings = (await conn.execute(text("select * from app.org_settings"))).mappings().first()
        automations = (await conn.execute(
            text("select id, template_key, status, created_at from app.automation_instances order by template_key")
        )).mappings().all()
        rows = {r["step_key"]: dict(r) for r in (await conn.execute(
            text("select step_key, status, done_by, blocker, eta from app.onboarding_progress")
        )).mappings().all()}
        steps = (await org_features(conn))["steps"]  # only the steps this client's automations need, in order
        onboarding = [rows.get(k, {"step_key": k, "status": "todo", "done_by": None, "blocker": None, "eta": None}) for k in steps]
    return {
        "org_id": ctx.org_id,
        "role": ctx.role,
        "settings": dict(settings) if settings else None,
        "automations": [dict(a) for a in automations],
        "onboarding": onboarding,
    }


@router.get("/features")
async def features(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    """What this client can see: portal sections, connection cards and onboarding steps follow their automations."""
    async with tenant_session(ctx.org_id) as conn:
        return await org_features(conn)


@router.get("/overview")
async def overview(
    ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict:
    """KPI tiles: this period vs the previous one, plus a daily series. Reads the rollups, never raw events."""
    today = date.today()
    start, prev_start = today - timedelta(days=days - 1), today - timedelta(days=2 * days - 1)
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(
            text("select metric_key, day, value from app.metrics_daily where day >= :prev order by day"),
            {"prev": prev_start},
        )).all()
        currency = (await conn.execute(text("select currency from app.org_settings"))).scalar_one_or_none()
    by_metric: dict[str, list] = {}
    for r in rows:
        by_metric.setdefault(r.metric_key, []).append(r)
    tiles = []
    for m in registry():
        series = by_metric.get(m["key"])
        if not series:
            continue  # only show what this organisation actually has
        cur = sum(float(r.value) for r in series if r.day >= start)
        prev = sum(float(r.value) for r in series if r.day < start)
        daily = {r.day: float(r.value) for r in series if r.day >= start}
        tiles.append({
            "key": m["key"], "name": m["name"], "unit": m["unit"],
            "higher_is_better": m.get("higher_is_better", True),
            "value": cur, "previous": prev, "delta": (cur - prev) / prev if prev else None,
            "series": [{"day": (start + timedelta(days=i)).isoformat(), "value": daily.get(start + timedelta(days=i), 0)}
                       for i in range(days)],
        })
    return {"days": days, "currency": currency, "tiles": tiles}


@router.get("/contacts")
async def contacts(
    ctx: Annotated[OrgContext, Depends(require("conversation", "read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(
            text("select id, name, email, phone, company, source, created_at from app.contacts order by created_at desc, name limit :l"),
            {"l": limit},
        )).mappings().all()
        total = (await conn.execute(text("select count(*) from app.contacts"))).scalar_one()
    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/audit")
async def audit_log(
    ctx: Annotated[OrgContext, Depends(require("audit", "read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(
            text("""select a.id, a.at, a.actor_type, a.action, a.target_type, a.target_id, a.metadata, a.ip,
                           u.name as actor_name, u.email as actor_email
                    from app.audit_log a left join auth."user" u on u.id = a.actor_user_id
                    order by a.at desc limit :l"""),
            {"l": limit},
        )).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/automations/{template_key}/{action}")
async def set_automation_state(
    template_key: str,
    action: Literal["pause", "resume", "automatic", "approval"],
    request: Request,
    ctx: Annotated[OrgContext, Depends(require("automation", "pause"))],
) -> dict:
    """pause / resume (to live), or switch between approval mode and automatic (live)."""
    if action in ("automatic", "approval") and not ctx.can("automation", "configure"):
        raise HTTPException(403, "missing permission automation:configure")
    new_status = {"pause": "paused", "resume": "live", "automatic": "live", "approval": "approval_mode"}[action]
    async with tenant_session(ctx.org_id) as conn:
        row = await conn.execute(
            text("""update app.automation_instances set status = :s
                    where template_key = :k and status <> 'setup' returning id"""),
            {"s": new_status, "k": template_key},
        )
        instance_id = row.scalar_one_or_none()
        if instance_id is None:
            raise HTTPException(404, "automation not found or not set up yet")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"automation.{action}", target_type="automation", target_id=template_key,
                           ip=client_ip(request))
        await emit(conn, ctx.org_id, f"automation.{new_status}", {"template_key": template_key, "by": ctx.principal.user_id})
    return {"template_key": template_key, "status": new_status}


class TeamEvent(BaseModel):
    action: Literal["member.invited", "member.added", "member.role_changed", "member.removed", "invitation.canceled"]
    email: Annotated[str, Field(max_length=320)]
    role: Annotated[str | None, Field(max_length=60)] = None


_TEAM_PERMISSION = {"member.invited": ("invitation", "create"), "member.added": ("invitation", "create"),
                    "member.role_changed": ("member", "update"), "member.removed": ("member", "delete"),
                    "invitation.canceled": ("invitation", "cancel")}


@router.post("/team/events", status_code=201)
async def team_event(body: TeamEvent, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """The dashboard changes the team (Better Auth's tables) and records it here, in the client's audit log.
    Only someone allowed to make that change can record it."""
    if not ctx.can(*_TEAM_PERMISSION[body.action]):
        raise HTTPException(403, f"missing permission {':'.join(_TEAM_PERMISSION[body.action])}")
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=body.action, target_type="member", target_id=body.email, ip=client_ip(request),
                           metadata={"role": body.role} if body.role else {})
    return {"ok": True}
