"""Replies to cold email (Phase 5.5): understood, and each kind lands in the right place.

    interested     -> contact + lead (engaged) in the lead engine, a conversation with the whole thread, a Needs-you card
    not_now        -> sequence stops; the lead waits in nurture and comes back in ~75 days
    unsubscribe    -> do-not-contact on every channel, immediately
    out_of_office  -> the next email waits a week; nothing else changes
    referral       -> sequence stops; a card for a person to reach the name they gave
    wrong_person   -> sequence stops; a card, in case someone wants to find the right person
    bounce         -> address suppressed (bounce), mailbox health checked

A spam complaint (from the sending provider) suppresses the address and pauses the mailbox at once.
"""
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.cold_email.sending import check_mailbox, stop_prospect
from agentry.db import tenant_session
from agentry.events import emit
from agentry.leads import claim, normalize_email, opt_out, resolve_contact
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

KINDS = ("interested", "not_now", "unsubscribe", "out_of_office", "referral", "wrong_person", "bounce")
NURTURE_DAYS = 75
_RULES = [
    ("bounce", r"mailer-daemon|delivery status notification|address not found|undeliverable|recipient address rejected"),
    ("out_of_office", r"out of (the )?office|on leave|on holiday|on vacation|away until|auto(matic)?[- ]reply|limited access to email"),
    ("unsubscribe", r"\b(unsubscribe|remove me|stop (emailing|sending|contacting)|take me off|not interested|don'?t (email|contact))\b"),
    ("referral", r"\b(talk|speak|reach out|write|contact) to\b.*@|\bcc'?ing\b|\bforward(ed|ing)? (this )?to\b"),
    ("wrong_person", r"wrong person|not the right person|i don'?t handle|not my (area|department)"),
    ("not_now", r"\b(not now|maybe later|next (month|quarter|year)|busy (right now|this month)|circle back|later this year)\b"),
    ("interested", r"\?|\b(interested|tell me more|send (me )?(details|the video|more)|call|demo|price|pricing|cost|sounds good|let'?s talk)\b"),
]


def heuristic(reply: str) -> dict:
    t = reply.lower()
    kind = next((k for k, pat in _RULES if re.search(pat, t)), "not_now")
    ref = re.search(r"([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*(?:\(|<|at\s)?\s*([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", reply) if kind == "referral" else None
    return {"kind": kind, "summary": reply.strip().splitlines()[0][:140] if reply.strip() else "", "referral": f"{ref[1]} {ref[2]}" if ref else None}


async def classify(org_id: str, reply: str, pitch: str | None) -> dict:
    fallback = heuristic(reply)
    prompt = load("cold_email_reply_classifier")
    try:
        res = await complete(prompt.tier, prompt.render(pitch=pitch or "our service", reply=reply[:4000]), org_id=org_id,
                             prompt_key=prompt.key, prompt_version=prompt.version, json_output=True, mock_response=json.dumps(fallback))
        data = res.data if isinstance(res.data, dict) else {}
    except AllModelsFailed:
        data = {}
    if data.get("kind") not in KINDS:
        return fallback
    return {"kind": data["kind"], "summary": str(data.get("summary") or fallback["summary"])[:200], "referral": data.get("referral") or None}


async def _prospect_by_email(conn: AsyncConnection, email: str) -> dict | None:
    row = (await conn.execute(text("""select p.*, co.name as company, co.website from app.prospects p
        join app.prospect_companies co on co.id = p.company_id
        where p.email = :e and exists (select 1 from app.email_events ev where ev.prospect_id = p.id and ev.kind = 'sent')
        order by p.created_at desc limit 1"""), {"e": email})).mappings().first()
    return dict(row) if row else None


async def _event(conn: AsyncConnection, org_id: str, p: dict, kind: str, detail: dict) -> None:
    await conn.execute(text("""insert into app.email_events (org_id, campaign_id, prospect_id, mailbox_id, kind, detail)
        values (:o, :c, :p, :m, :k, cast(:d as jsonb))"""),
        {"o": org_id, "c": p["campaign_id"], "p": p["id"], "m": p["mailbox_id"], "k": kind, "d": json.dumps(detail)})


async def _thread(conn: AsyncConnection, org_id: str, p: dict, reply: str, contact_id: str) -> str:
    """A conversation holding what we sent and what they replied, so the team can pick it up in the portal."""
    conv = (await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, contact_id, subject, external_ref, metadata)
        values (:o, 'email', 'cold_email', cast(:k as uuid), :s, :r, cast(:m as jsonb))
        on conflict (org_id, channel, external_ref) do update set last_message_at = now() returning id"""),
        {"o": org_id, "k": contact_id, "s": f"Cold email: {p['company']}", "r": f"cold:{p['id']}",
         "m": json.dumps({"source": "cold_email", "prospect_id": str(p["id"]), "campaign_id": str(p["campaign_id"])})})).scalar_one()
    have = (await conn.execute(text("select count(*) from app.messages where conversation_id = :c"), {"c": conv})).scalar_one()
    if not have:
        sent = (await conn.execute(text("""select detail->>'body' as body, at from app.email_events where prospect_id = :p and kind = 'sent'
            order by at"""), {"p": p["id"]})).all()
        for s in sent:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, created_at, metadata)
                values (:o, :c, 'out', 'agent', :b, :t, '{"sent_from": "cold_email"}')"""), {"o": org_id, "c": conv, "b": s.body, "t": s.at})
    await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
        values (:o, :c, 'in', 'contact', :b, '{"source": "cold_email"}')"""), {"o": org_id, "c": conv, "b": reply})
    return str(conv)


async def _lead(conn: AsyncConnection, org_id: str, p: dict, stage: str, conv: str | None) -> tuple[str, str]:
    contact = await resolve_contact(conn, org_id, name=p["name"], email=p["email"], company=p["company"], source="cold_email")
    lead = (await conn.execute(text("""select id from app.leads where contact_id = :c and stage not in ('won','lost','disqualified','opted_out')
        order by created_at desc limit 1"""), {"c": contact})).scalar_one_or_none()
    if lead:
        await conn.execute(text("update app.leads set stage = :s, conversation_id = coalesce(:v, conversation_id), updated_at = now() where id = :l"),
                           {"s": stage, "v": conv, "l": lead})
    else:
        lead = (await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage, conversation_id, qualification)
            values (:o, :c, 'cold_email', :s, :v, cast(:q as jsonb)) returning id"""),
            {"o": org_id, "c": contact, "s": stage, "v": conv,
             "q": json.dumps({"company": p["company"], "role": p["role"], "first_line": p["first_line"]})})).scalar_one()
    await claim(conn, str(lead), "cold_email", inbound=True)
    return str(contact), str(lead)


async def unsubscribe(conn: AsyncConnection, org_id: str, prospect_id: str, source: str) -> bool:
    p = (await conn.execute(text("select * from app.prospects where id = cast(:p as uuid)"), {"p": prospect_id})).mappings().first()
    if not p:
        return False
    p = dict(p)
    await conn.execute(text("""insert into app.suppressions (org_id, channel, address, reason) values (:o, 'email', :a, 'opt_out')
        on conflict do nothing"""), {"o": org_id, "a": p["email"]})
    contact = (await conn.execute(text("select id from app.contacts where email_norm = :e and merged_into is null limit 1"), {"e": p["email"]})).scalar_one_or_none()
    if contact:
        for ch in ("email", "whatsapp", "sms", "voice"):
            await opt_out(conn, org_id, str(contact), ch, source=source)
    await stop_prospect(conn, prospect_id, "unsubscribed")
    if not (await conn.execute(text("select 1 from app.email_events where prospect_id = :p and kind = 'unsubscribe'"), {"p": prospect_id})).first():
        await _event(conn, org_id, p, "unsubscribe", {"source": source})
    return True


async def _card(conn: AsyncConnection, org_id: str, p: dict, title: str, body: str, conv: str) -> None:
    await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload)
        values (:o, 'handoff', 'cold_email', cast(:c as uuid), :t, :b, cast(:p as jsonb))"""),
        {"o": org_id, "c": conv, "t": title, "b": body, "p": json.dumps({"prospect_id": str(p["id"]), "source": "cold_email"})})


async def ingest_reply(org_id: str, from_email: str, reply: str) -> dict:
    """A reply arrived (provider webhook, or the simulator in mock mode). Returns what was done."""
    email = normalize_email(from_email) or from_email.lower()
    async with tenant_session(org_id) as conn:
        p = await _prospect_by_email(conn, email)
        if not p:
            return {"matched": False}
        cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'cold_email'"))).scalar_one_or_none() or {}
        c = await classify(org_id, reply, cfg.get("pitch"))
        kind = c["kind"]
        await _event(conn, org_id, p, "reply", {"text": reply[:4000], **c})
        await conn.execute(text("update app.prospects set reply_kind = :k, updated_at = now() where id = :p"), {"k": kind, "p": p["id"]})
        who = f"{p['name'] or p['email']} at {p['company']}"
        if kind == "bounce":
            await _event(conn, org_id, p, "bounce", {"text": reply[:500]})
            await conn.execute(text("""insert into app.suppressions (org_id, channel, address, reason) values (:o, 'email', :a, 'bounce')
                on conflict do nothing"""), {"o": org_id, "a": p["email"]})
            await stop_prospect(conn, str(p["id"]), "bounced")
            paused = await check_mailbox(conn, str(p["mailbox_id"])) if p["mailbox_id"] else None
            return {"matched": True, "kind": kind, "mailbox_paused": paused}
        if kind == "unsubscribe":
            await unsubscribe(conn, org_id, str(p["id"]), "cold_email_reply")
            return {"matched": True, "kind": kind}
        if kind == "out_of_office":
            await conn.execute(text("""update app.prospects set next_send_at = greatest(coalesce(next_send_at, now()), now()) + interval '7 days'
                where id = :p and status = 'active'"""), {"p": p["id"]})
            return {"matched": True, "kind": kind}
        await stop_prospect(conn, str(p["id"]), f"replied: {kind.replace('_', ' ')}")
        if kind == "not_now":
            contact, lead = await _lead(conn, org_id, p, "nurture", None)
            await conn.execute(text("update app.prospects set nurture_at = :t, lead_id = cast(:l as uuid) where id = :p"),
                               {"t": datetime.now(UTC) + timedelta(days=NURTURE_DAYS), "l": lead, "p": p["id"]})
            return {"matched": True, "kind": kind, "lead_id": lead}
        contact = await resolve_contact(conn, org_id, name=p["name"], email=p["email"], company=p["company"], source="cold_email")
        conv = await _thread(conn, org_id, p, reply, contact)
        if kind == "interested":
            _, lead = await _lead(conn, org_id, p, "engaged", conv)
            await conn.execute(text("update app.prospects set lead_id = cast(:l as uuid), conversation_id = cast(:c as uuid) where id = :p"),
                               {"l": lead, "c": conv, "p": p["id"]})
            await _card(conn, org_id, p, f"Interested: {who}", f"{c['summary']}\n\nReply and offer a time to talk.", conv)
            await emit(conn, org_id, "cold_email.interested", {"prospect_id": str(p["id"]), "lead_id": lead, "conversation_id": conv})
            return {"matched": True, "kind": kind, "lead_id": lead, "conversation_id": conv}
        await conn.execute(text("update app.prospects set conversation_id = cast(:c as uuid) where id = :p"), {"c": conv, "p": p["id"]})
        if kind == "referral":
            await _card(conn, org_id, p, f"Referral from {who}", f"They pointed to {c.get('referral') or 'someone else'}. {c['summary']}", conv)
        else:
            await _card(conn, org_id, p, f"Wrong person: {who}", f"{c['summary']}\n\nFind the right person, or close this.", conv)
        return {"matched": True, "kind": kind, "conversation_id": conv}


async def complaint(org_id: str, from_email: str) -> dict:
    email = normalize_email(from_email) or from_email.lower()
    async with tenant_session(org_id) as conn:
        p = await _prospect_by_email(conn, email)
        if not p:
            return {"matched": False}
        await _event(conn, org_id, p, "complaint", {})
        await conn.execute(text("""insert into app.suppressions (org_id, channel, address, reason) values (:o, 'email', :a, 'complaint')
            on conflict do nothing"""), {"o": org_id, "a": email})
        await stop_prospect(conn, str(p["id"]), "marked as spam")
        paused = await check_mailbox(conn, str(p["mailbox_id"])) if p["mailbox_id"] else None
        return {"matched": True, "mailbox_paused": paused}
