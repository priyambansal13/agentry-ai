"""Instant alerts to the business owner (urgent emails now; escalations later).

Channels: Telegram (bot token in AGENTRY_TELEGRAM_BOT_TOKEN + the client's chat id), WhatsApp (Phase 2, via the
WhatsApp channel), and email to the organisation's owners as the always-available fallback.
"""
import asyncio

import httpx
from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session
from agentry.notify.email import send_email
from agentry.permissions import can

# Alert kinds, who may receive them (a permission, from config/roles.json) and who gets them unless they opt out.
# Everyone else with the permission can opt in on "Notifications & data". Email is the per-person channel today;
# Telegram goes to the organisation's chat when configured.
NOTIFY_KINDS: dict[str, dict] = {
    "urgent": {"permission": ("conversation", "act"), "default_roles": ("owner", "manager"),
               "automations": ("inbox_triage", "website_chat", "whatsapp_assistant", "telegram_assistant")},
    # every new Needs-you card, with Approve / Edit / Discard buttons: Telegram only (agentry/telegram_team.py)
    "cards": {"permission": ("dashboard", "read"), "default_roles": ("owner", "manager", "staff", "finance"), "automations": None,
              "telegram_only": True},
    # a second alert when an urgent email is still unanswered (inbox triage: escalate_after_minutes)
    "escalation": {"permission": ("conversation", "act"), "default_roles": ("owner",), "automations": ("inbox_triage",)},
    "digest": {"permission": ("conversation", "read"), "default_roles": ("owner", "manager"), "automations": ("inbox_triage",)},
    # Monday-morning summary of the week (#19): emails sorted, urgent caught, time saved
    "weekly": {"permission": ("dashboard", "read"), "default_roles": ("owner",), "automations": ("inbox_triage",)},
    "billing": {"permission": ("billing", "read"), "default_roles": ("owner", "finance"), "automations": None},
    "reports": {"permission": ("dashboard", "read"), "default_roles": ("owner", "manager"), "automations": None},
}


def kinds_for(role: str | None, automations: list[str], is_staff: bool = False) -> dict[str, list[str]]:
    """The alert kinds this person may choose from, with their default channels."""
    out = {}
    for kind, k in NOTIFY_KINDS.items():
        if k["automations"] is not None and not set(k["automations"]) & set(automations):
            continue
        if not (is_staff or can(role, *k["permission"])):
            continue
        default_on = bool(role) and any(r.strip() in k["default_roles"] for r in role.split(","))
        out[kind] = (["telegram"] if k.get("telegram_only") else ["email"]) if default_on else []
    return out


async def recipient_emails(org_id: str, kind: str, exclude_roles: tuple[str, ...] = ()) -> list[str]:
    """Members who may receive this kind of alert and want it by email (their choice, else their role's default).
    exclude_roles leaves some roles out (e.g. owners, when they only want to hear about unanswered urgent emails)."""
    k = NOTIFY_KINDS[kind]
    async with system_session() as conn:
        rows = (await conn.execute(
            text("""select u.email, m.role, p.prefs from auth.member m join auth."user" u on u.id = m."userId"
                    left join app.notification_preferences p on p.user_id = u.id and p.org_id = m."organizationId"
                    where m."organizationId" = :o"""), {"o": org_id})).all()
    out = []
    for r in rows:
        if not can(r.role, *k["permission"]) or any(x.strip() in exclude_roles for x in r.role.split(",")):
            continue
        prefs = r.prefs or {}
        wants = "email" in prefs[kind] if kind in prefs else any(x.strip() in k["default_roles"] for x in r.role.split(","))
        if wants:
            out.append(r.email)
    return out


async def recipients(org_id: str, kind: str, exclude_roles: tuple[str, ...] = ()) -> list[dict]:
    """Like recipient_emails, with each person's channels ("email", "whatsapp") and WhatsApp number (#3)."""
    k = NOTIFY_KINDS[kind]
    async with system_session() as conn:
        rows = (await conn.execute(
            text("""select u.email, m.role, p.prefs, t.chat_id from auth.member m join auth."user" u on u.id = m."userId"
                    left join app.notification_preferences p on p.user_id = u.id and p.org_id = m."organizationId"
                    left join app.telegram_links t on t.user_id = u.id and t.org_id = m."organizationId"
                    where m."organizationId" = :o"""), {"o": org_id})).all()
    out = []
    for r in rows:
        if not can(r.role, *k["permission"]) or any(x.strip() in exclude_roles for x in r.role.split(",")):
            continue
        prefs = r.prefs or {}
        channels = prefs[kind] if kind in prefs else (["email"] if any(x.strip() in k["default_roles"] for x in r.role.split(",")) else [])
        if channels:
            out.append({"email": r.email, "whatsapp_to": prefs.get("whatsapp_to"), "telegram_chat": r.chat_id, "channels": channels})
    return out


async def whatsapp_alerts(org_id: str) -> dict | None:
    """The client's WhatsApp number can carry alerts when it is connected and Agentry set an approved alert template
    (two body variables: title, details)."""
    async with system_session() as conn:
        row = (await conn.execute(text("""select state->>'alert_template' as template, coalesce(state->>'alert_template_language', 'en') as lang
            from app.connections where org_id = :o and provider = 'whatsapp' and status = 'connected' and state ? 'alert_template'
            order by created_at desc limit 1"""), {"o": org_id})).mappings().first()
    return dict(row) if row else None


async def send_owner_alert(org_id: str, subject: str, body: str, *, channel: str = "email",
                           telegram_chat_id: str | None = None, kind: str = "urgent", exclude_roles: tuple[str, ...] = ()) -> str:
    """Send an alert; returns the channel actually used."""
    if channel == "telegram" and settings.telegram_bot_token and telegram_chat_id:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                                  json={"chat_id": telegram_chat_id, "text": f"{subject}\n\n{body}"})
            if r.status_code == 200:
                return "telegram"
    people = await recipients(org_id, kind, exclude_roles)
    wa = await whatsapp_alerts(org_id) if any("whatsapp" in p["channels"] for p in people) else None
    used = set()
    for p in people:
        sent_wa = sent_tg = False
        if "telegram" in p["channels"] and p["telegram_chat"]:
            from agentry import telegram_team
            sent_tg = telegram_team.enabled() and await telegram_team.send_alert(p["telegram_chat"], subject, body)
            if sent_tg:
                used.add("telegram")
        if "whatsapp" in p["channels"] and wa and p["whatsapp_to"]:
            from agentry.connectors.whatsapp import WhatsAppError, send_template
            try:
                await send_template(org_id, p["whatsapp_to"], wa["template"], wa["lang"], [subject[:200], body[:900]])
                sent_wa = True
                used.add("whatsapp")
            except WhatsAppError:
                pass  # falls back to email below
        fell_back = ("whatsapp" in p["channels"] and not sent_wa) or ("telegram" in p["channels"] and not sent_tg and len(p["channels"]) == 1)
        if "email" in p["channels"] or fell_back:
            await asyncio.to_thread(send_email, p["email"], subject, body)
            used.add("email")
    return "+".join(sorted(used)) or "none"
