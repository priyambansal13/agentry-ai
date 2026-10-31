"""After a call: a short AI summary on the conversation (what the caller wanted, what happened, what's next), and a
"Call back" card in Needs you when a person should follow up.

Runs in the worker on `call.completed`. The summary feeds the conversation page, the Conversations list and the
callback cards. Without a model (mock mode) or if every model fails, a plain summary is built from the transcript.
"""
import json

from dbos import DBOS
from sqlalchemy import text

from agentry.config import settings
from agentry.db import tenant_session
from agentry.leads import resolve_contact
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.notify.alerts import send_owner_alert
from agentry.runs import run
from agentry.worker.handlers import on

FIELDS = ("summary", "intent", "outcome", "follow_up", "follow_up_reason", "caller_name", "callback_number")
OUTCOMES = ("booked", "answered", "handed_off", "message_taken", "no_conversation")
PROMPT = """Summarise this phone call between a business's AI assistant and a caller, for the business owner.
Return JSON: {"summary": one or two short sentences, "intent": what the caller wanted (a few words),
"outcome": one of booked | answered | handed_off | message_taken | no_conversation, "follow_up": true if a person should
call back or act, else false, "follow_up_reason": short reason or null, "caller_name": the name the caller gave or null,
"callback_number": the phone number the caller gave, digits with country code if said (e.g. "+919876543210"), or null}.
Never invent details that aren't in the call. Write about the caller by name or as "the caller", with "they/their":
never "he", "she", "his" or "her" (a name doesn't tell you someone's gender)."""


def fallback(lines: list[tuple[str, str]], booked: bool, handed_off: bool) -> dict:
    said = [b for who, b in lines if who == "caller"]
    outcome = "booked" if booked else "handed_off" if handed_off else "answered" if said else "no_conversation"
    first = said[0][:140] if said else "The caller didn't say anything."
    return {"summary": f"Caller said: {first}" if said else first, "intent": None, "outcome": outcome,
            "follow_up": handed_off, "follow_up_reason": "asked for a person" if handed_off else None,
            "caller_name": None, "callback_number": None}


@DBOS.step()
async def summarise(org_id: str, conversation_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select direction, author, body, metadata from app.messages
            where conversation_id = cast(:c as uuid) order by created_at"""), {"c": conversation_id})).mappings().all()
        # the call has ended (status closed) by now: the hand-off is remembered in metadata (agents/tools._handoff)
        handed_off = (await conn.execute(text("""select status = 'handed_off' or metadata ? 'handoff_reason'
            from app.conversations where id = cast(:c as uuid)"""), {"c": conversation_id})).scalar_one()
    lines = [("caller" if r["direction"] == "in" else "assistant", r["body"]) for r in rows]
    booked = any((r["metadata"] or {}).get("booking") for r in rows)
    transcript = "\n".join(f"{who}: {body}" for who, body in lines)
    base = fallback(lines, booked, handed_off)
    try:
        res = await complete("fast", [{"role": "system", "content": PROMPT}, {"role": "user", "content": transcript[:12000]}],
                             org_id=org_id, prompt_key="call_summary", prompt_version="v1", json_output=True,
                             mock_response=json.dumps(base))
        data = res.data if isinstance(res.data, dict) and res.data.get("summary") else base
    except AllModelsFailed:
        data = base
    if data.get("outcome") not in OUTCOMES:
        data["outcome"] = base["outcome"]
    if booked:  # facts beat the model's reading of the call
        data["outcome"] = "booked"
    if handed_off:  # the caller asked for a person: always a callback
        data["follow_up"] = True
        data["follow_up_reason"] = data.get("follow_up_reason") or "asked for a person"
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.conversations set metadata = metadata || jsonb_build_object('call', cast(:d as jsonb)) where id = cast(:c as uuid)"),
                           {"d": json.dumps({k: data.get(k) for k in FIELDS}),
                            "c": conversation_id})
    return data


@DBOS.step()
async def create_callback(org_id: str, conversation_id: str, call: dict) -> str | None:
    """A "Call back" card for the front desk (once per call), and an urgent alert to the people who get them.
    A caller who gave a name or number on the call becomes (or is matched to) a contact, linked to the call."""
    async with tenant_session(org_id) as conn:
        if (await conn.execute(text("""select exists(select 1 from app.approvals where conversation_id = cast(:c as uuid)
                and kind = 'callback')"""), {"c": conversation_id})).scalar_one():
            return None
        if call.get("caller_name") or call.get("callback_number"):
            linked = (await conn.execute(text("select contact_id from app.conversations where id = cast(:c as uuid)"),
                                         {"c": conversation_id})).scalar_one_or_none()
            if not linked:
                cid = await resolve_contact(conn, org_id, name=call.get("caller_name"), phone=call.get("callback_number"), source="voice")
                await conn.execute(text("update app.conversations set contact_id = cast(:k as uuid) where id = cast(:c as uuid)"),
                                   {"k": cid, "c": conversation_id})
        c = (await conn.execute(text("""select c.metadata, k.name, coalesce(k.phone_e164, k.phone) as phone from app.conversations c
            left join app.contacts k on k.id = c.contact_id where c.id = cast(:c as uuid)"""), {"c": conversation_id})).mappings().first()
        if not c:
            return None
        who = c["name"] or c["phone"] or "A caller"
        title = ("Test call: " if (c["metadata"] or {}).get("test") else "") + f"Call back {who}: {call.get('follow_up_reason') or 'follow up'}"
        body = call.get("summary") or ""
        aid = str((await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
            values (:o, 'callback', 'ai_receptionist', cast(:c as uuid), :t, :b, cast(:p as jsonb)) returning id"""),
            {"o": org_id, "c": conversation_id, "t": title[:200], "b": body,
             "p": json.dumps({"phone": c["phone"], "caller": c["name"], "urgent": True})})).scalar_one())
    await send_owner_alert(org_id, f"Call back needed: {who}",
                           f"{body}\n\nNumber: {c['phone'] or 'not captured'}\nOpen: {settings.dashboard_url}/conversations/{conversation_id}")
    return aid


@on("call.completed")
@DBOS.workflow()
async def on_call_completed(event: dict) -> None:
    cid = event["payload"]["conversation_id"]
    async with run(event["org_id"], "ai_receptionist", "voice.summary", key=f"call_summary:{cid}", subject=("conversation", cid)):
        await _on_call_completed(event)


async def _on_call_completed(event: dict) -> None:
    org_id, conversation_id = event["org_id"], event["payload"]["conversation_id"]
    call = await summarise(org_id, conversation_id)
    if call.get("follow_up"):
        await create_callback(org_id, conversation_id, call)
