"""Turn an incoming email into a conversation + message + email.received event (one transaction).

`external_id` (e.g. "gmail:<message id>") makes ingestion idempotent: the same provider message is stored once.
"""
import json

from sqlalchemy import text

from agentry.db import tenant_session
from agentry.events import emit


async def ingest_email(org_id: str, *, sender: str, subject: str, body: str, thread_ref: str,
                       received_at: str | None = None, external_id: str | None = None,
                       extra: dict | None = None) -> str | None:
    """Returns the new message id, or None if this provider message was already ingested."""
    meta = {"from": sender, **(extra or {}), **({"external_id": external_id} if external_id else {})}
    source = thread_ref.split(":", 1)[0] if ":" in thread_ref else "local"
    async with tenant_session(org_id) as conn:
        conv_id = (await conn.execute(text("""
            insert into app.conversations (org_id, channel, automation_key, subject, external_ref, last_message_at, metadata)
            values (:o, 'email', 'inbox_triage', :s, :ref, coalesce(cast(:at as timestamptz), now()),
                    jsonb_strip_nulls(jsonb_build_object('source', cast(:src as text), 'mailbox', cast(:mb as text))))
            on conflict (org_id, channel, external_ref) do update set last_message_at = excluded.last_message_at
            returning id"""), {"o": org_id, "s": subject, "ref": thread_ref, "at": received_at, "src": source,
                                 "mb": (extra or {}).get("mailbox")})).scalar_one()
        msg_id = (await conn.execute(text("""
            insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
            values (:o, :c, 'in', 'contact', :b, cast(:m as jsonb), coalesce(cast(:at as timestamptz), now()))
            on conflict (org_id, (metadata->>'external_id')) where metadata ? 'external_id' do nothing
            returning id"""),
            {"o": org_id, "c": conv_id, "b": body, "m": json.dumps(meta), "at": received_at})).scalar_one_or_none()
        if msg_id is None:
            return None
        await emit(conn, org_id, "email.received", {"conversation_id": str(conv_id), "message_id": str(msg_id)})
    return str(msg_id)
