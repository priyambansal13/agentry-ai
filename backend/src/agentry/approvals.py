"""Deciding Needs-you cards. `decide` is the one path a person's decision takes, from the portal or from Telegram;
`approve_as_agent` is auto-send for trusted categories (inbox triage #13), through the same path, saying who sent it."""
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


class CardError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


MONEY_AGENTS = ("invoice_follow_up", "bookkeeping")  # their cards follow the invoice (money) permission, not conversation


def resource_for(automation_key: str | None) -> str:
    return "invoice" if automation_key in MONEY_AGENTS else "conversation"


async def decide(conn: AsyncConnection, org_id: str, approval_id: str, action: str, body: str | None, *, user_id: str | None,
                 name: str | None, is_staff: bool, actor_type: str, can_act, ip: str | None = None, via: str = "portal") -> str:
    """approve / reject / resolve one card. `can_act(resource)` says whether this person may act on that kind of card.
    Raises CardError(status, message). Returns the new status."""
    from agentry.outbound import channel_problem
    a = (await conn.execute(text("select * from app.approvals where id = cast(:id as uuid) for update"), {"id": approval_id})).mappings().first()
    if not a:
        raise CardError(404, "not found")
    if not can_act(resource_for(a["automation_key"])):
        raise CardError(403, f"missing permission {resource_for(a['automation_key'])}:act")
    if a["status"] != "pending":
        raise CardError(409, f"already {a['status']}")
    if action == "approve" and a["kind"] == "outbound_draft" and (why := await channel_problem(
            org_id, a["payload"].get("channel", ""), a["payload"].get("template"))):
        raise CardError(409, f"Not sent: {why}. Discard this card, or fix that in Settings → Connections and approve again.")
    edited = body is not None and body.strip() != (a["body"] or "").strip()
    status = {"approve": "edited" if edited else "approved", "reject": "rejected", "resolve": "resolved"}[action]
    await conn.execute(text("""update app.approvals set status = :s, body = coalesce(:b, body), decided_by = :u,
                               decided_at = now() where id = cast(:id as uuid)"""), {"s": status, "b": body, "u": user_id, "id": approval_id})
    if action == "approve" and a["kind"] == "reply_draft" and a["conversation_id"]:  # outbound drafts: recorded on delivery
        # Local mailbox: approving records the reply as sent by the human. Gmail/Outlook will send from the draft.
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
                                   values (:o, :c, 'out', 'human', :b, jsonb_build_object('approval_id', cast(:a as text),
                                   'sent_by', jsonb_build_object('user_id', cast(:u as text), 'name', cast(:n as text), 'staff', cast(:st as boolean))))"""),
                           {"o": org_id, "c": a["conversation_id"], "b": body or a["body"], "a": approval_id, "u": user_id, "n": name, "st": is_staff})
        await conn.execute(text("update app.conversations set last_message_at = now() where id = :c"), {"c": a["conversation_id"]})
    await audit.record(conn, org_id=org_id, actor_type=actor_type, actor_user_id=user_id, action=f"approval.{status}", target_type="approval",
                       target_id=approval_id, ip=ip, metadata={"kind": a["kind"], "via": via})
    await emit(conn, org_id, "approval.decided", {"approval_id": approval_id, "status": status, "kind": a["kind"]})
    return status
