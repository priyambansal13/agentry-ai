"""Inbox triage workflow: one durable DBOS workflow per incoming email.

email.received -> rules -> classify (fast tier; heuristic in mock mode or if every model fails) -> label ->
urgent? alert owner : (needs reply? draft into the thread + "Needs you" approval) -> emit events
(email.triaged for metrics, lead.created for new enquiries, invoice.reply for the invoice automation).
The AI never sends email: drafts wait for a human.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text

from agentry import audit
from agentry.automations.inbox_triage.config import TriageConfig
from agentry.automations.inbox_triage.escalation import follow_up_urgent, send_alert
from agentry.automations.inbox_triage.rules import fraud_signals, heuristic_triage, is_vip, rule_decision
from agentry.connectors.mailbox import mailbox_for
from agentry.db import tenant_session
from agentry.events import emit
from agentry.knowledge import format_hits, search
from agentry.leads import resolve_contact
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.runs import current, run
from agentry.worker.handlers import on


@DBOS.step()
async def load_email(org_id: str, message_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""
            select m.id as message_id, m.conversation_id, m.body, m.metadata as mmeta, c.subject, c.metadata as cmeta, m.created_at,
                   s.timezone, s.persona, a.config, a.status as automation_status,
                   o.name as business,
                   exists(select 1 from app.contacts k where lower(k.email) = lower(m.metadata->>'from')) as known_contact
            from app.messages m join app.conversations c on c.id = m.conversation_id
            join app.org_settings s on s.org_id = m.org_id
            left join app.automation_instances a on a.template_key = 'inbox_triage'
            join auth.organization o on o.id = m.org_id
            where m.id = :m"""), {"m": message_id})).mappings().one()
        sender = (row["mmeta"].get("from") or "").lower()
        domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
        known_domains = list((await conn.execute(text("""select distinct lower(split_part(email, '@', 2)) from app.contacts
            where email like '%@%' limit 500"""))).scalars())
        # what this business taught us: the latest correction for this sender, else for their domain (#8)
        learned = (await conn.execute(text("""select to_category, sender = :s as exact from app.label_corrections
            where sender = :s or sender_domain = :d order by (sender = :s) desc, created_at desc limit 5"""),
            {"s": sender, "d": domain})).all()
    return {
        "message_id": str(row["message_id"]), "conversation_id": str(row["conversation_id"]),
        "from": row["mmeta"].get("from", ""), "subject": row["subject"] or "",
        # what the models read: the email plus the text of its readable attachments (#14)
        "body": row["body"] + "".join(f"\n\n[Attachment: {a['filename']}]\n{a['text'][:3000]}"
                                      for a in row["mmeta"].get("attachments", []) if a.get("text")),
        "from_name": row["mmeta"].get("from_name") or (row["mmeta"].get("gmail") or {}).get("from_name") or "",
        "reply_to": row["mmeta"].get("reply_to") or "", "known_domains": known_domains,
        "learned": [{"category": r.to_category, "exact": r.exact} for r in learned],
        "timezone": row["timezone"], "persona": row["persona"], "business": row["business"],
        "config": TriageConfig(**(row["config"] or {})).model_dump(mode="json"),
        "automation_status": row["automation_status"], "known_contact": bool(row["known_contact"]),
        "received_at": row["created_at"].isoformat(),
    }


SCRIPTS = [("hi", 0x0900, 0x097F), ("bn", 0x0980, 0x09FF), ("pa", 0x0A00, 0x0A7F), ("gu", 0x0A80, 0x0AFF), ("or", 0x0B00, 0x0B7F),
           ("ta", 0x0B80, 0x0BFF), ("te", 0x0C00, 0x0C7F), ("kn", 0x0C80, 0x0CFF), ("ml", 0x0D00, 0x0D7F), ("ur", 0x0600, 0x06FF)]


def script_language(t: str) -> str:
    """The email's language from its script, when the model didn't say (mock mode, outages). Devanagari reads as Hindi
    (Marathi uses it too; the model tells them apart). Latin script, including Hinglish, reads as English."""
    counts = {code: sum(lo <= ord(ch) <= hi for ch in t) for code, lo, hi in SCRIPTS}
    code, n = max(counts.items(), key=lambda kv: kv[1])
    return code if n >= 3 else "en"


def learned_category(email: dict) -> str | None:
    """A category the business taught us for this sender (one correction is enough) or domain (two that agree)."""
    learned = email.get("learned") or []
    exact = [x["category"] for x in learned if x["exact"]]
    if exact:
        return exact[0]
    domain = [x["category"] for x in learned]
    return domain[0] if len(domain) >= 2 and domain[0] == domain[1] else None


@DBOS.step()
async def classify(org_id: str, email: dict) -> dict:
    risk = fraud_signals(email, email.get("known_domains"))
    if (d := rule_decision(email)) is not None:
        return d | {"source": "rules", "suspicious": bool(risk) or d.get("flag") == "phishing", "risk": risk}
    vip = is_vip(email["from"], email["config"]["vip_senders"])
    prompt = load("inbox_triage_classifier")
    heuristic = heuristic_triage(email, known_contact=email["known_contact"])
    custom = email["config"].get("custom_categories") or []
    allowed = set(email["config"]["categories"]) | set(custom)
    custom_text = ("This business also uses its own categories; use one when it fits better than the list above:\n"
                   + "\n".join(f"- {c}" for c in custom)) if custom else ""
    learned = learned_category(email)
    corrections = (f"This business has filed emails like this one under \"{learned}\": prefer it unless it clearly doesn't fit."
                   if learned else "")
    try:
        res = await complete(
            "fast",
            prompt.render(business=email["business"], known_contact="yes" if email["known_contact"] else "no",
                          vip="yes" if vip else "no", from_name=email.get("from_name") or "",
                          reply_to=email.get("reply_to") or "(same as sender)", custom_categories=custom_text,
                          corrections=corrections, today=datetime.now(ZoneInfo(email["timezone"])).date().isoformat(),
                          **{k: email[k] for k in ("from", "subject", "body")}),
            org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
            mock_response=json.dumps(heuristic),
        )
        decision = res.data if isinstance(res.data, dict) and res.data.get("category") else heuristic
        source = "mock" if res.mock else ("llm" if decision is res.data else "heuristic")
        model = res.model
    except AllModelsFailed:
        decision, source, model = heuristic, "heuristic", None
    if decision.get("category") not in allowed:
        decision["category"] = heuristic["category"]
    if learned and learned in allowed and decision.get("category") != learned:
        decision["category"], source = learned, "learned"  # the business corrected this sender before (#8)
    if vip and decision.get("category") not in ("Spam", "Promotion", "Newsletter"):
        decision["urgent"] = True
        decision.setdefault("urgent_reason", "VIP sender")
    if decision.get("suspicious") and decision.get("suspicious_reason"):
        risk.append(decision["suspicious_reason"])
    decision["language"] = decision.get("language") or script_language(f"{email['subject']} {email['body'][:2000]}")
    decision["suspicious"] = bool(risk)
    decision["risk"] = list(dict.fromkeys(risk))
    if risk and decision["category"] == "Invoice/Payment" and not decision.get("urgent"):
        decision["urgent"] = True  # a payment request that looks like fraud must be seen before anyone pays
        decision["urgent_reason"] = f"Possible payment fraud: {risk[0]}"
    return decision | {"source": source, "model": model}


@DBOS.step()
async def save_triage(org_id: str, email: dict, triage: dict) -> None:
    labels = list(dict.fromkeys([f"Agentry/{triage['category']}"] + (["Agentry/Urgent"] if triage.get("urgent") else [])
                                + (["Agentry/Suspicious"] if triage.get("suspicious") else [])))
    async with tenant_session(org_id) as conn:
        await conn.execute(
            text("update app.messages set metadata = metadata || jsonb_build_object('triage', cast(:t as jsonb)) where id = :m"),
            {"t": json.dumps(triage), "m": email["message_id"]},
        )
        await audit.record(conn, org_id=org_id, actor_type="agent", action="email.triaged",
                           target_type="conversation", target_id=email["conversation_id"],
                           metadata={"category": triage["category"], "urgent": bool(triage.get("urgent")),
                                     "source": triage.get("source")})
    archive = email["config"]["archive_promotions"] and triage["category"] in ("Promotion", "Spam")
    await (await mailbox_for(org_id, email["conversation_id"])).apply_labels(org_id, email["conversation_id"], labels, archive)


def _in_quiet_hours(tz: str, quiet: list[str]) -> bool:
    now = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
    start, end = quiet
    return (start <= now or now < end) if start > end else (start <= now < end)


async def recent_alert_count(org_id: str) -> int:
    async with tenant_session(org_id) as conn:
        return (await conn.execute(text("""select count(*) from app.audit_log
            where action = 'alert.sent' and at > now() - interval '1 hour'"""))).scalar_one()


@DBOS.step()
async def alert_hold(org_id: str, email: dict) -> str | None:
    """Why the first alert must wait (quiet hours, too many alerts this hour), or None to send it now."""
    cfg = email["config"]
    if _in_quiet_hours(email["timezone"], cfg["quiet_hours"]):
        return "deferred_quiet_hours"  # sent when quiet hours end (escalation.py), and listed in the digest
    if await recent_alert_count(org_id) >= cfg["max_alerts_per_hour"]:
        return "deferred_rate_limit"
    return None


LANGUAGES = {"en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam",
             "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "or": "Odia"}


def language_name(code: str | None) -> str:
    """The reply language (#15): the sender's own, English when unknown. Hinglish arrives as "en" or "hi" and the
    drafter mirrors the sender's mix."""
    return LANGUAGES.get((code or "en").lower()[:2], "the sender's language")


@DBOS.step()
async def draft_reply(org_id: str, email: dict, triage: dict) -> str:
    hits = await search(org_id, f"{email['subject']}\n{email['body']}", k=4, min_score=0.3)  # only clearly relevant facts
    persona = email["persona"] or {}
    sender = persona.get("signoff") or f"The {email['business']} team"
    first = (email["from"].split("@")[0].split(".")[0] or "there").capitalize()
    prompt = load("email_reply_drafter")
    fallback = (f"Hi {first},\n\nThanks for your email about \"{email['subject']}\". [Add your reply here.]\n\n"
                f"Best regards,\n{sender}")
    async with tenant_session(org_id) as conn:
        saved = (await conn.execute(text("select title, body from app.reply_templates order by updated_at desc limit 12"))).all()
        style = (await conn.execute(text("select profile->>'writing_style' from app.org_settings"))).scalar()
        thread = (await conn.execute(text("""select direction, left(body, 600) as body from app.messages
            where conversation_id = cast(:c as uuid) and id <> cast(:m as uuid) and body <> ''
            order by created_at desc limit 4"""), {"c": email["conversation_id"], "m": email["message_id"]})).all()
    try:
        res = await complete("writer", prompt.render(
            business=email["business"], sender_name=sender, tone=persona.get("tone", "warm and professional"),
            category=triage["category"], knowledge=format_hits(hits), language=language_name(triage.get("language")),
            style=style or "(not learned yet: write naturally)",
            saved_replies="\n\n".join(f"[{t.title}]\n{t.body[:800]}" for t in saved) or "(none)",
            thread="\n".join(f"{'They' if r.direction == 'in' else 'We'}: {r.body}" for r in reversed(thread)) or "(no earlier messages)",
            **{k: email[k] for k in ("from", "subject", "body")}),
            org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, mock_response=fallback)
        body = res.text.strip() or fallback
        ai_failed = not res.text.strip() and not res.mock
    except AllModelsFailed:
        body, ai_failed = fallback, True
    await (await mailbox_for(org_id, email["conversation_id"])).create_draft(org_id, email["conversation_id"], body)
    async with tenant_session(org_id) as conn:
        return str((await conn.execute(
            text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body, payload, assigned_to)
                    values (:o, 'reply_draft', 'inbox_triage', :c, :title, :body, cast(:p as jsonb),
                            (select k.state->>'assign_to' from app.connections k join app.conversations cv on cv.id = cast(:c as uuid)
                             where k.provider in ('gmail', 'outlook') and k.account_ref = cv.metadata->>'mailbox' and k.status <> 'revoked'))
                    returning id"""),
            {"o": org_id, "c": email["conversation_id"], "title": f"Reply to {email['from']}: {email['subject']}",
             "body": body, "p": json.dumps({"category": triage["category"], "urgent": bool(triage.get("urgent")),
                                            "kb_sources": [h.title for h in hits], "ai_failed": ai_failed,
                                            "draft": body, "suspicious": bool(triage.get("suspicious")),
                                            "risk": triage.get("risk") or [], "language": triage.get("language")})},
        )).scalar_one())


@DBOS.step()
async def maybe_auto_send(org_id: str, email: dict, triage: dict, approval_id: str) -> str | None:
    """Send the draft without waiting for a person (#13) only when every condition holds; otherwise None (it waits)."""
    cfg = email["config"]
    if (email["automation_status"] != "live" or triage["category"] not in cfg.get("auto_send_categories", [])
            or triage.get("urgent") or triage.get("suspicious") or float(triage.get("confidence") or 0) < 0.75):
        return None
    from agentry.approvals import approve_as_agent
    from agentry.automations.inbox_triage.insights import trusted_categories
    async with tenant_session(org_id) as conn:
        body, failed = (await conn.execute(text("""select body, coalesce((payload->>'ai_failed')::boolean, false) from app.approvals
            where id = cast(:a as uuid)"""), {"a": approval_id})).one()
        if failed or "[" in body or triage["category"] not in await trusted_categories(conn, int(cfg.get("auto_send_min_approved", 10))):
            return None
        await approve_as_agent(conn, org_id, approval_id, f"auto-send: {triage['category']}")
    return "auto_sent"


@DBOS.step()
async def emit_outcomes(org_id: str, email: dict, triage: dict, alert: str | None) -> None:
    async with tenant_session(org_id) as conn:
        await emit(conn, org_id, "email.triaged", {"conversation_id": email["conversation_id"],
                                                   "category": triage["category"], "urgent": bool(triage.get("urgent")),
                                                   "alert": alert})
        if triage["category"] == "Lead":
            contact_id = await resolve_contact(conn, org_id, email=email["from"], source="email",
                                               company=(triage.get("entities") or {}).get("company"))
            lead_id = (await conn.execute(
                text("""insert into app.leads (org_id, contact_id, source, stage, qualification, conversation_id)
                        values (:o, :c, 'inbox', 'new', cast(:q as jsonb), :conv) returning id"""),
                {"o": org_id, "c": contact_id, "conv": email["conversation_id"],
                 "q": json.dumps({k: v for k, v in (triage.get("entities") or {}).items() if v})},
            )).scalar_one()
            await emit(conn, org_id, "lead.created", {"lead_id": str(lead_id), "source": "inbox"})
        linked = (await conn.execute(text("""select metadata->>'subject_id' from app.conversations
            where id = :c and metadata->>'subject_type' = 'invoice'"""), {"c": email["conversation_id"]})).scalar_one_or_none()
        if linked or (triage["category"] == "Invoice/Payment" and triage.get("intent") != "payment_receipt"):
            await emit(conn, org_id, "invoice.reply", {"conversation_id": email["conversation_id"], "invoice_id": linked,
                                                       "entities": triage.get("entities") or {}, "text": email["body"][:4000]})


@on("email.received")
@DBOS.workflow()
async def triage_email(event: dict) -> None:
    mid = event["payload"]["message_id"]
    async with run(event["org_id"], "inbox_triage", "triage.email", key=f"triage:{mid}", subject=("message", mid)):
        await _triage_email(event)


async def _triage_email(event: dict) -> None:
    org_id = event["org_id"]
    email = await load_email(org_id, event["payload"]["message_id"])
    if email["automation_status"] not in ("live", "approval_mode"):
        return  # paused or not set up: leave the email untouched
    triage = await classify(org_id, email)
    await save_triage(org_id, email, triage)
    current().step("sorted", category=triage.get("category"), urgent=bool(triage.get("urgent")))
    alert = None
    if triage.get("urgent"):
        # what an alert needs, without the email body (workflow arguments are stored)
        brief = {k: email[k] for k in ("conversation_id", "message_id", "from", "subject", "config", "received_at")} | {
            "urgent_reason": triage.get("urgent_reason"), "summary": triage.get("summary")}
        alert = await alert_hold(org_id, email) or await send_alert(org_id, brief, escalation=False)
        if alert == "deferred_quiet_hours" or email["config"]["escalate_after_minutes"]:
            with SetWorkflowID(f"urgent-follow-up-{email['message_id']}"):
                await DBOS.start_workflow_async(follow_up_urgent, org_id, brief, alert)
    if triage.get("needs_reply") and email["config"]["draft_replies"]:
        approval_id = await draft_reply(org_id, email, triage)
        current().step("reply drafted")
        if await maybe_auto_send(org_id, email, triage, approval_id):
            current().step("sent automatically")
    await emit_outcomes(org_id, email, triage, alert)
