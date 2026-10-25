"""Mailbox connectors: where triage reads email from and writes labels and drafts back to.

`local`: email arrives through the API (or the mock-data loader); labels/drafts are kept on the conversation.
`gmail`: connectors/gmail.py writes real labels and drafts. Outlook (Microsoft Graph) will implement the same protocol.
"""
import json
from datetime import datetime
from typing import Protocol

from sqlalchemy import text

from agentry.db import tenant_session


class Mailbox(Protocol):
    async def apply_labels(self, org_id: str, conversation_id: str, labels: list[str], archive: bool) -> None: ...
    async def create_draft(self, org_id: str, conversation_id: str, body: str) -> str: ...
    async def replied_since(self, org_id: str, conversation_id: str, since: datetime) -> bool: ...
    async def relabel(self, org_id: str, conversation_id: str, add: list[str], remove: list[str]) -> None: ...


async def reply_recorded(org_id: str, conversation_id: str, since: datetime) -> bool:
    """A reply sent through Agentry (approved draft or a person's reply) after `since`."""
    async with tenant_session(org_id) as conn:
        return (await conn.execute(text("""select exists(select 1 from app.messages where conversation_id = :c
            and direction = 'out' and created_at > :t)"""), {"c": conversation_id, "t": since})).scalar_one()


class LocalMailbox:
    async def apply_labels(self, org_id: str, conversation_id: str, labels: list[str], archive: bool) -> None:
        async with tenant_session(org_id) as conn:
            await conn.execute(
                text("""update app.conversations
                        set metadata = metadata || jsonb_build_object('labels', cast(:labels as jsonb), 'archived', :arch)
                        where id = :c"""),
                {"labels": json.dumps(labels), "arch": archive, "c": conversation_id},
            )

    async def create_draft(self, org_id: str, conversation_id: str, body: str) -> str:
        async with tenant_session(org_id) as conn:
            await conn.execute(
                text("update app.conversations set metadata = metadata || jsonb_build_object('draft', cast(:b as text)) where id = :c"),
                {"b": body, "c": conversation_id},
            )
        return f"local-draft-{conversation_id}"

    async def replied_since(self, org_id: str, conversation_id: str, since: datetime) -> bool:
        return await reply_recorded(org_id, conversation_id, since)

    async def relabel(self, org_id: str, conversation_id: str, add: list[str], remove: list[str]) -> None:
        async with tenant_session(org_id) as conn:
            cur = (await conn.execute(text("select coalesce(metadata->'labels', '[]') from app.conversations where id = :c"),
                                      {"c": conversation_id})).scalar_one()
            labels = [x for x in cur if x not in remove] + [x for x in add if x not in cur]
            await conn.execute(text("update app.conversations set metadata = metadata || jsonb_build_object('labels', cast(:l as jsonb)) where id = :c"),
                               {"l": json.dumps(labels), "c": conversation_id})


async def mailbox_for(org_id: str, conversation_id: str) -> Mailbox:
    """The mailbox a conversation came from: Gmail for gmail:* threads, otherwise the local mailbox."""
    async with tenant_session(org_id) as conn:
        source = (await conn.execute(text("select metadata->>'source' from app.conversations where id = :c"),
                                     {"c": conversation_id})).scalar_one_or_none()
    if source == "gmail":
        from agentry.connectors.gmail import GmailMailbox
        return GmailMailbox()
    if source == "outlook":
        from agentry.connectors.outlook import OutlookMailbox
        return OutlookMailbox()
    return LocalMailbox()


async def record_sent_reply(org_id: str, *, thread_ref: str, external_id: str, body: str, sent_at: datetime, sent_from: str) -> bool:
    """A reply the business sent from their own mail app, in a thread Agentry knows: stored as an outbound message
    (response times, "handled"). A reply approved in Agentry is already stored (its external_id is set once delivered);
    if delivery hasn't stamped it yet, it is adopted instead of stored twice. Threads Agentry doesn't know are ignored."""
    async with tenant_session(org_id) as c:
        conv = (await c.execute(text("select id from app.conversations where channel = 'email' and external_ref = :r"),
                                {"r": thread_ref})).scalar_one_or_none()
        if not conv:
            return False
        if (await c.execute(text("select exists(select 1 from app.messages where metadata->>'external_id' = :e)"), {"e": external_id})).scalar_one():
            return False
        pending = (await c.execute(text("""select id from app.messages where conversation_id = :c and direction = 'out'
            and metadata ? 'approval_id' and not metadata ? 'external_id' and created_at > :t - interval '10 minutes'
            order by created_at desc limit 1"""), {"c": conv, "t": sent_at})).scalar_one_or_none()
        if pending:
            await c.execute(text("update app.messages set metadata = metadata || jsonb_build_object('external_id', cast(:e as text)) where id = :m"),
                            {"e": external_id, "m": pending})
            return False
        await c.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
            values (:o, :c, 'out', 'human', :b, cast(:meta as jsonb), :at)
            on conflict (org_id, (metadata->>'external_id')) where metadata ? 'external_id' do nothing"""),
            {"o": org_id, "c": conv, "b": body[:100_000], "at": sent_at,
             "meta": json.dumps({"external_id": external_id, "sent_from": sent_from, "delivery": "sent",
                                 "sent_by": {"user_id": None, "name": f"Sent from {sent_from.capitalize()}"}})})
        await c.execute(text("update app.conversations set last_message_at = greatest(last_message_at, :t) where id = :c"),
                        {"t": sent_at, "c": conv})
    return True
