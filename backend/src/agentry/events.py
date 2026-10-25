"""Transactional outbox. Call emit() inside the same transaction as the change it describes."""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def emit(conn: AsyncConnection, org_id: str | None, type_: str, payload: dict[str, Any]) -> int:
    row = await conn.execute(
        text("insert into app.events (org_id, type, payload) values (:org, :type, cast(:payload as jsonb)) returning id"),
        {"org": org_id, "type": type_, "payload": json.dumps(payload, default=str)},
    )
    return row.scalar_one()
