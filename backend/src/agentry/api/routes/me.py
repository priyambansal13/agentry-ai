from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from agentry.auth import Principal, current_principal
from agentry.db import system_session
from agentry.permissions import role_label

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(principal: Annotated[Principal, Depends(current_principal)]) -> dict:
    """Who am I, and which organisations can I open (for the org switcher)."""
    async with system_session() as conn:
        rows = await conn.execute(
            text("""select o.id, o.name, o.slug, m.role, coalesce(s.status, 'pending_setup') as status
                    from auth.member m join auth.organization o on o.id = m."organizationId"
                    left join app.org_settings s on s.org_id = o.id
                    where m."userId" = :u order by o.name"""),
            {"u": principal.user_id},
        )
        orgs = [dict(r._mapping) | {"role_label": role_label(r.role)} for r in rows]
    return {
        "user": {"id": principal.user_id, "email": principal.email, "name": principal.name},
        "is_staff": principal.is_staff,
        "organizations": orgs,
    }
