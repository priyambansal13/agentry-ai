"""Append-only audit log. Every change made by a person, Agentry staff, an agent or the system is recorded."""
import json
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ActorType = Literal["user", "agentry_staff", "system", "agent"]


async def record(
    conn: AsyncConnection,
    *,
    org_id: str | None,
    actor_type: ActorType,
    action: str,
    actor_user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    await conn.execute(
        text("""insert into app.audit_log (org_id, actor_user_id, actor_type, action, target_type, target_id, metadata, ip)
                values (:org, :uid, :atype, :action, :ttype, :tid, cast(:meta as jsonb), :ip)"""),
        {"org": org_id, "uid": actor_user_id, "atype": actor_type, "action": action, "ttype": target_type,
         "tid": target_id, "meta": json.dumps(metadata or {}, default=str), "ip": ip},
    )
