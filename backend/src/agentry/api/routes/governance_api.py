"""Autonomy & limits in the portal (owners decide, managers can look), and the audit-chain check for Agentry staff."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit, governance
from agentry.auth import OrgContext, Principal, client_ip, current_org, require_staff
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter()


def _can_view(ctx: OrgContext) -> bool:
    return ctx.can("automation", "configure")


def _can_change(ctx: OrgContext) -> bool:
    return ctx.principal.is_staff or ctx.can("organization", "update")  # the owner


@router.get("/org/governance")
async def get_governance(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not _can_view(ctx):
        raise HTTPException(403, "only owners and managers see autonomy settings")
    async with tenant_session(ctx.org_id) as conn:
        actions = await governance.overview(conn, await enabled_automations(conn))
    return {"actions": actions, "can_change": _can_change(ctx), "levels": list(governance.LEVELS)}


class Setting(BaseModel):
    level: str
    max_per_day: Annotated[int | None, Field(ge=0, le=10000)] = None
    quiet_hours: bool | None = None


@router.put("/org/governance/{action}")
async def put_governance(action: str, b: Setting, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not _can_change(ctx):
        raise HTTPException(403, "only the owner decides how much the agents may do on their own")
    if action not in governance.ACTIONS:
        raise HTTPException(404, "unknown action")
    limits = {k: v for k, v in {"max_per_day": b.max_per_day, "quiet_hours": b.quiet_hours}.items() if v is not None}
    async with tenant_session(ctx.org_id) as conn:
        if governance.ACTIONS[action].agent not in await enabled_automations(conn):
            raise HTTPException(404, "that agent isn't switched on here")
        try:
            await governance.set_level(conn, ctx.org_id, action, b.level, limits, ctx.principal.user_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="governance.changed",
                           target_type="action", target_id=action, ip=client_ip(request), metadata={"level": b.level, **limits})
    return {"action": action, "level": b.level, "limits": limits}


@router.get("/hq/orgs/{org_id}/audit-chain")
async def audit_chain(org_id: str, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Is this business's audit log intact? (Each row's hash covers the one before: an edit or deletion breaks it.)"""
    async with tenant_session(org_id) as conn:
        broken = (await conn.execute(text("select app.audit_chain_break(:o)"), {"o": org_id})).scalar_one()
        n = (await conn.execute(text("select count(*) from app.audit_log"))).scalar_one()
    return {"rows": n, "intact": broken is None, "first_broken_id": broken}
