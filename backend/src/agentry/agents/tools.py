"""Tools the conversational agent can call. Each runs under the organisation's row-level security."""
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from agentry import audit
from agentry.booking import BookingError, availability, book
from agentry.config import settings
from agentry.db import tenant_session
from agentry.events import emit
from agentry.knowledge import search
from agentry.leads import resolve_contact
from agentry.notify.alerts import send_owner_alert


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


TOOL_DEFS = [
    _fn("search_knowledge", "Search the business's knowledge (services, prices, policies, FAQs, hours).",
        {"query": {"type": "string"}}, ["query"]),
    _fn("check_availability", "List free appointment times for a service.",
        {"service_key": {"type": "string"},
         "date": {"type": "string", "description": "YYYY-MM-DD to start from (default: today)"},
         "part_of_day": {"type": "string", "enum": ["any", "morning", "afternoon", "evening"]}},
        ["service_key"]),
    _fn("book_appointment", "Book an appointment. Only after the visitor confirmed service, time, name and phone.",
        {"service_key": {"type": "string"}, "start": {"type": "string", "description": "ISO start time from check_availability"},
         "name": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"}},
        ["service_key", "start", "name", "phone"]),
    _fn("save_lead", "Record what you learned about the visitor. Call again to update.",
        {"need": {"type": "string"}, "budget": {"type": "string"}, "timeline": {"type": "string"},
         "urgency": {"type": "string"}, "location": {"type": "string"}, "name": {"type": "string"},
         "phone": {"type": "string"}, "email": {"type": "string"},
         "qualified": {"type": "boolean", "description": "true if they meet the qualification rule, false if clearly not a fit"},
         "notes": {"type": "string"}}, []),
    _fn("handoff_to_human", "Ask a human from the business to take over this conversation.",
        {"reason": {"type": "string"}}, ["reason"]),
]

PARTS = {"morning": (0, 12), "afternoon": (12, 16), "evening": (16, 24), "any": (0, 24)}


async def run_tool(name: str, args: dict[str, Any], *, org_id: str, conversation_id: str, source: str) -> dict:
    try:
        if name == "search_knowledge":
            hits = await search(org_id, str(args.get("query", "")), k=4)
            return {"results": [{"title": h.title, "content": h.content} for h in hits] or "nothing found"}
        if name == "check_availability":
            start = date.fromisoformat(args["date"]) if args.get("date") else None
            slots, tz, svc = await availability(org_id, args["service_key"], start, days=7, limit=200)
            lo, hi = PARTS.get(args.get("part_of_day") or "any", (0, 24))
            picked = [s for s in slots if lo <= s.start.astimezone(tz).hour < hi][:6]
            return {"service": svc["name"], "slots": [{"start": s.start.isoformat(), "label": s.label(tz)} for s in picked]
                    or "no free times in the next 7 days for that part of the day"}
        if name == "book_appointment":
            lead_id = await _lead_id(org_id, conversation_id)
            r = await book(org_id, service_key=args["service_key"], start=datetime.fromisoformat(args["start"]),
                           name=args["name"], phone=args.get("phone"), email=args.get("email"), source=source,
                           conversation_id=conversation_id, lead_id=lead_id)
            return {"booked": True, **{k: r[k] for k in ("service", "staff", "when", "booking_id")}}
        if name == "save_lead":
            return await _save_lead(org_id, conversation_id, args, source)
        if name == "handoff_to_human":
            return await _handoff(org_id, conversation_id, str(args.get("reason", "")), source)
        return {"error": f"unknown tool {name}"}
    except BookingError as e:
        return {"error": str(e), "alternatives": e.alternatives}
    except (KeyError, ValueError) as e:
        return {"error": f"bad arguments: {e}"}


async def _lead_id(org_id: str, conversation_id: str) -> str | None:
    async with tenant_session(org_id) as conn:
        lid = (await conn.execute(text("select id from app.leads where conversation_id = :c"), {"c": conversation_id})).scalar_one_or_none()
    return str(lid) if lid else None


async def _save_lead(org_id: str, conversation_id: str, args: dict, source: str) -> dict:
    contact = {k: args.get(k) for k in ("name", "phone", "email") if args.get(k)}
    qual = {k: v for k, v in args.items() if k not in ("name", "phone", "email", "qualified") and v}
    stage = "qualified" if args.get("qualified") is True else "disqualified" if args.get("qualified") is False else "engaged"
    async with tenant_session(org_id) as conn:
        conv = (await conn.execute(text("select contact_id from app.conversations where id = :c"), {"c": conversation_id})).scalar_one()
        if contact:
            found = await resolve_contact(conn, org_id, name=contact.get("name"), phone=contact.get("phone"),
                                          email=contact.get("email"), source=source)
            if conv and str(conv) != found:
                from agentry.leads import merge_contacts
                await merge_contacts(conn, found, str(conv))  # the visitor turned out to be a known person
            conv = found
            await conn.execute(text("update app.conversations set contact_id = :k where id = :c"), {"k": conv, "c": conversation_id})
        existing = (await conn.execute(text("select id, stage from app.leads where conversation_id = :c"), {"c": conversation_id})).first()
        if existing:
            keep = existing.stage if existing.stage == "booked" else stage
            await conn.execute(text("""update app.leads set qualification = qualification || cast(:q as jsonb), stage = :s,
                contact_id = coalesce(contact_id, :k), updated_at = now() where id = :id"""),
                {"q": json.dumps(qual), "s": keep, "k": conv, "id": existing.id})
            return {"saved": True, "stage": keep}
        lid = (await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage, qualification, conversation_id)
            values (:o, :k, :src, :s, cast(:q as jsonb), :c) returning id"""),
            {"o": org_id, "k": conv, "src": source, "s": stage, "q": json.dumps(qual), "c": conversation_id})).scalar_one()
        await emit(conn, org_id, "lead.created", {"lead_id": str(lid), "source": source})
    return {"saved": True, "stage": stage}


async def _handoff(org_id: str, conversation_id: str, reason: str, source: str = "web_chat") -> dict:
    whatsapp = source == "whatsapp"
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.conversations set status = 'handed_off' where id = :c"), {"c": conversation_id})
        if source == "voice":
            # Nobody can type into a phone call: when it ends, the summary step turns this into a "Call back" card
            # (voice/summary.py). Live transfer to a staff phone comes with phone numbers (PHASE-4-VOICE.md 4.4).
            await conn.execute(text("""update app.conversations set metadata = metadata || jsonb_build_object('handoff_reason', cast(:r as text))
                where id = :c"""), {"c": conversation_id, "r": reason})
            await audit.record(conn, org_id=org_id, actor_type="agent", action="conversation.handoff",
                               target_type="conversation", target_id=conversation_id, metadata={"reason": reason, "channel": source})
            return {"handed_off": True, "tell_visitor": "Tell the caller someone from the team will call them back soon, "
                                                        "and check you have their name and the best number to reach them."}
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body)
            values (:o, 'handoff', :a, :c, :t, :r)"""),
            {"o": org_id, "a": "whatsapp_assistant" if whatsapp else "website_chat", "c": conversation_id,
             "t": "WhatsApp customer asked for a person" if whatsapp else "Website visitor asked for a person", "r": reason})
        await audit.record(conn, org_id=org_id, actor_type="agent", action="conversation.handoff",
                           target_type="conversation", target_id=conversation_id, metadata={"reason": reason, "channel": source})
    await send_owner_alert(org_id, "A WhatsApp customer needs a person" if whatsapp else "A website visitor needs a person",
                           f"{reason}\n\nOpen: {settings.dashboard_url}/conversations/{conversation_id}")
    return {"handed_off": True, "tell_visitor": "A team member will reply here shortly."}
