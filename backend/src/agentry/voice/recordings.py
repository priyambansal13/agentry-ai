"""Call recordings on disk: where they are, deleting one on request, and the daily retention clean-up.

Each client keeps recordings for `org_settings.recording_retention_days` (default 90, PHASE-4-VOICE.md §5). Deleting
keeps the conversation, transcript and summary, and notes when and why the audio went.
"""
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.db import system_session


def path_for(rel: str | None) -> Path | None:
    """The recording file for a stored relative path, only if it is inside the recordings folder and exists."""
    if not rel:
        return None
    root = Path(settings.recordings_dir).resolve()
    path = (root / rel).resolve()
    return path if root in path.parents and path.is_file() else None


async def remove(conn: AsyncConnection, conversation_id: str, rel: str | None, reason: str) -> bool:
    """Delete the audio file and mark the conversation. Returns whether a file was deleted."""
    path = path_for(rel)
    if path:
        path.unlink(missing_ok=True)
    await conn.execute(text("""update app.conversations set metadata = (metadata - 'recording') || cast(:m as jsonb)
        where id = cast(:c as uuid)"""), {"c": conversation_id, "m": json.dumps(
            {"recording_deleted": {"at": datetime.now(UTC).isoformat(timespec="seconds"), "reason": reason}})})
    return path is not None


async def purge_expired() -> int:
    """Daily: delete recordings older than each client's retention period. Returns how many were deleted."""
    async with system_session() as conn:
        rows = (await conn.execute(text("""select c.id, c.metadata->>'recording' as rec from app.conversations c
            left join app.org_settings s on s.org_id = c.org_id
            where c.channel = 'voice' and c.metadata ? 'recording'
              and c.created_at < now() - make_interval(days => coalesce(s.recording_retention_days, 90))"""))).all()
        for r in rows:
            await remove(conn, str(r.id), r.rec, "retention")
    return len(rows)
