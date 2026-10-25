"""Approving a draft on Agentry's own authority: auto-send for trusted categories (inbox triage #13). It goes through
exactly the path a person's approval takes (message recorded, approval.decided -> delivery), and says who sent it."""
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.events import emit


async def approve_as_agent(conn: AsyncConnection, org_id: str, approval_id: str, reason: str) -> str:
    a = (await conn.execute(text("select conversation_id, body, kind from app.approvals where id = cast(:a as uuid) and status = 'pending'"),
                            {"a": approval_id})).mappings().first()
    if not a:
        raise ValueError("approval is not pending")
    await conn.execute(text("update app.approvals set status = 'approved', decided_at = now() where id = cast(:a as uuid)"), {"a": approval_id})
    mid = str((await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
        values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb)) returning id"""),
        {"o": org_id, "c": a["conversation_id"], "b": a["body"],
         "m": json.dumps({"approval_id": approval_id, "auto_sent": True, "sent_by": {"user_id": None, "name": "Sent automatically by Agentry"}})})).scalar_one())
    await conn.execute(text("update app.conversations set last_message_at = now() where id = :c"), {"c": a["conversation_id"]})
    await audit.record(conn, org_id=org_id, actor_type="agent", action="approval.auto_sent", target_type="approval",
                       target_id=approval_id, metadata={"reason": reason})
    await emit(conn, org_id, "approval.decided", {"approval_id": approval_id, "status": "approved", "kind": a["kind"], "auto": True})
    return mid
