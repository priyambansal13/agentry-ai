"""What a client can see and do follows from the automations Agentry switched on for them.

One table drives the portal menu, the onboarding steps, the connection cards, the go-live checks and the API guards,
so an inbox-triage-only client never sees invoices, campaigns or chat-widget setup, and can't reach them by URL.
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.auth import OrgContext, current_org
from agentry.db import tenant_session


@dataclass(frozen=True)
class Feature:
    pages: tuple[str, ...]  # portal sections this automation brings (besides the always-on ones)
    connections: tuple[str, ...]  # connection cards to show
    steps: tuple[str, ...]  # onboarding steps it needs (besides the always-on ones)
    go_live: tuple[str, ...]  # checks that must pass before going live
    available: bool = True  # False = sold soon, can't be switched on yet


FEATURES: dict[str, Feature] = {
    "inbox_triage": Feature(pages=("needs-you", "conversations", "leads", "knowledge"), connections=("gmail", "outlook"),
                            steps=("connect", "knowledge", "settings", "persona"), go_live=("mailbox",)),
    "website_chat": Feature(pages=("needs-you", "conversations", "leads", "knowledge", "calendar"), connections=(),
                            steps=("connect", "knowledge", "persona", "test"), go_live=("knowledge", "test")),
    "whatsapp_assistant": Feature(pages=("needs-you", "conversations", "leads", "knowledge", "calendar"), connections=("whatsapp",),
                                  steps=("connect", "knowledge", "persona", "compliance"), go_live=("whatsapp",)),
    "invoice_follow_up": Feature(pages=("needs-you", "conversations", "invoices"), connections=("gmail", "whatsapp", "gateways"),
                                 steps=("connect", "import", "settings", "compliance"), go_live=("invoices", "channel")),
    "lead_reactivation": Feature(pages=("needs-you", "conversations", "leads", "campaigns", "calendar"), connections=("whatsapp", "gmail"),
                                 steps=("connect", "import", "settings", "persona", "compliance"), go_live=("channel",)),
    "speed_to_lead": Feature(pages=("needs-you", "conversations", "leads", "calendar", "lead_forms"), connections=("whatsapp", "gmail"),
                             steps=("connect", "settings", "persona", "compliance"), go_live=("channel",)),
    # goes live once Agentry assigns it a phone number (HQ -> client -> Phone number; PHASE-4-VOICE.md 4.3)
    "telegram_assistant": Feature(pages=("needs-you", "conversations", "leads", "knowledge", "calendar"), connections=("telegram",),
                                  steps=("connect", "knowledge", "persona"), go_live=("telegram",)),
    "ai_receptionist": Feature(pages=("needs-you", "conversations", "leads", "knowledge", "calendar"), connections=("phone",),
                               steps=("knowledge", "settings", "persona", "test"), go_live=("knowledge", "test", "phone")),
    # 9.3: reminders, confirm / reschedule by reply, waitlist, recalls; uses the bookings the other agents make
    "appointment_concierge": Feature(pages=("needs-you", "conversations", "calendar"), connections=("whatsapp", "telegram", "gmail"),
                                     steps=("connect", "settings", "compliance"), go_live=()),
    # 10.1: pages and prices checked by watchers; changes reported in plain words
    "competitor_watch": Feature(pages=("watch",), connections=(), steps=("settings",), go_live=()),
    # 9.2: reviews pulled by a watcher (sample source until Google Business Profile), replies approved, review requests
    "reviews": Feature(pages=("needs-you", "reviews"), connections=(), steps=("settings",), go_live=()),
    # 9.5: receipts and bills by photo (portal, WhatsApp, Telegram) -> Document AI -> checked -> Tally / CSV
    "bookkeeping": Feature(pages=("needs-you", "bookkeeping"), connections=("whatsapp", "telegram", "gmail", "google_sheets"), steps=("connect", "settings"), go_live=()),
    # 9.4: a research note on every new lead; a brief before each meeting (Notification Center)
    "lead_research": Feature(pages=("leads", "calendar"), connections=(), steps=("settings",), go_live=()),
    # 5.1-5.3: lists, research and reviewed first lines; nothing is sent until sending (5.4) is built
    "cold_email": Feature(pages=("cold-email",), connections=(), steps=("settings", "compliance"), go_live=()),
    # 6.1-6.4: uploads, moments, posts with quote cards, review and calendar; publishing is test mode until 6.5
    "content_repurposing": Feature(pages=("content",), connections=("linkedin", "instagram"), steps=("settings",), go_live=()),
    # Veo-made Shorts on a schedule, checked, reviewed, published to YouTube (docs/flows/agents/ai-video-studio.md)
    # tickets with SLA, order status from the order sheet, ratings (ROADMAP-V3 A2); works through the chat agents
    "support_desk": Feature(pages=("needs-you", "tickets", "conversations"), connections=(), steps=("settings",), go_live=()),
    # product questions from the catalogue, GST quotes as PDFs, follow-ups (ROADMAP-V3 A3); works through the chat agents
    "catalog_quotes": Feature(pages=("needs-you", "quotes", "conversations"), connections=(), steps=("settings",), go_live=()),
    # renewal reminders with payment links, win-backs, birthday wishes (ROADMAP-V3 A4)
    "renewals": Feature(pages=("renewals",), connections=("whatsapp", "gmail", "gateways"), steps=("connect", "import", "settings", "compliance"), go_live=()),
    # CVs scored with reasons quoted from the CV, shortlist, interviews, regrets (ROADMAP-V3 A5)
    "hiring": Feature(pages=("needs-you", "hiring"), connections=("whatsapp", "gmail"), steps=("settings",), go_live=()),
    "video_studio": Feature(pages=("needs-you", "videos"), connections=("youtube",), steps=("connect", "settings"), go_live=()),
}
# CA Firm pack (docs/PACKS.md): the firm's clients (ca-clients), the filing board (filings), the due-date calendar (compliance)
FEATURES |= {
    "ca_filing_tracker": Feature(pages=("needs-you", "filings", "ca-clients"), connections=("whatsapp",), steps=("connect", "settings"), go_live=()),
    "ca_document_chaser": Feature(pages=("needs-you", "filings", "ca-clients"), connections=("whatsapp", "gmail"),
                                  steps=("connect", "settings", "compliance"), go_live=()),
    "ca_tax_docs_reader": Feature(pages=("ca-clients",), connections=(), steps=("settings",), go_live=()),
    "ca_compliance_calendar": Feature(pages=("needs-you", "compliance", "ca-clients"), connections=("whatsapp", "gmail"),
                                      steps=("connect", "settings"), go_live=()),
}
FEATURES |= {  # agents that work on one client's documents live on the client's page; the Excel desk and recurring entries have their own
    k: Feature(pages=("ca-clients",), connections=(), steps=("settings",), go_live=())
    for k in ("ca_itr_prep", "ca_capital_gains", "ca_bank_classifier", "ca_gst_reconciliation", "ca_tds_returns", "ca_tax_audit")
}
FEATURES |= {
    "ca_notice_handler": Feature(pages=("needs-you", "ca-clients", "filings"), connections=(), steps=("settings",), go_live=()),
    "recurring_books": Feature(pages=("recurring",), connections=(), steps=("settings",), go_live=()),
    "excel_desk": Feature(pages=("excel",), connections=(), steps=(), go_live=()),
}
ALWAYS_PAGES = ("home", "ask", "automations", "reports", "team", "audit", "billing", "notifications")
ALWAYS_STEPS = ("profile", "plan", "team")
STEP_ORDER = ["profile", "plan", "team", "connect", "import", "knowledge", "settings", "persona", "compliance", "test", "go_live"]
GO_LIVE_LABELS = {
    "profile": "Business profile", "knowledge": "Knowledge & offers", "test": "Test your agent", "gmail": "Gmail connected",
    "whatsapp": "WhatsApp connected", "channel": "Gmail or WhatsApp connected", "invoices": "Invoices imported",
    "phone": "Phone number assigned", "mailbox": "Gmail or Outlook connected", "telegram": "Telegram bot connected",
}


def for_automations(keys: list[str]) -> dict:
    fs = [FEATURES[k] for k in keys if k in FEATURES]
    pages = list(ALWAYS_PAGES) + sorted({p for f in fs for p in f.pages})
    connections = sorted({c for f in fs for c in f.connections})
    if connections:
        pages.append("connections")
    wanted = set(ALWAYS_STEPS) | {s for f in fs for s in f.steps}
    return {"automations": keys, "pages": pages, "connections": connections,
            "steps": [s for s in STEP_ORDER if s in wanted] + ["go_live"],
            "go_live": ["profile"] + sorted({g for f in fs for g in f.go_live})}


async def enabled_automations(conn: AsyncConnection) -> list[str]:
    return list((await conn.execute(text("select template_key from app.automation_instances order by template_key"))).scalars())


async def org_features(conn: AsyncConnection) -> dict:
    return for_automations(await enabled_automations(conn))


async def go_live_checks(conn: AsyncConnection, required: list[str]) -> list[dict]:
    steps = dict((await conn.execute(text("select step_key, status from app.onboarding_progress"))).all())
    conns = set((await conn.execute(text("select provider from app.connections where status = 'connected'"))).scalars())
    invoices = (await conn.execute(text("select exists(select 1 from app.invoices)"))).scalar_one()
    done = {
        "profile": steps.get("profile") in ("done", "skipped"), "knowledge": steps.get("knowledge") in ("done", "skipped"),
        "test": steps.get("test") in ("done", "skipped"), "gmail": "gmail" in conns, "whatsapp": "whatsapp" in conns,
        "channel": bool(conns & {"gmail", "whatsapp"}), "invoices": bool(invoices), "phone": "phone" in conns, "mailbox": bool(conns & {"gmail", "outlook"}), "telegram": "telegram" in conns,
    }
    return [{"key": k, "label": GO_LIVE_LABELS[k], "done": done[k]} for k in required]


def require_page(page: str):
    """API guard: the organisation must have an automation that brings this section (Agentry staff included:
    a hidden section stays hidden for everyone, so what staff see is what the client sees)."""
    async def check(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
        async with tenant_session(ctx.org_id) as conn:
            f = await org_features(conn)
        if page not in f["pages"]:
            raise HTTPException(404, f"{page} is not part of this client's plan")
        return ctx
    return check


def require_connection(kind: str):
    """API guard for connecting an account the client's automations don't use (e.g. WhatsApp for inbox triage only)."""
    async def check(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
        async with tenant_session(ctx.org_id) as conn:
            f = await org_features(conn)
        if kind not in f["connections"]:
            raise HTTPException(404, f"{kind} is not used by this client's automations")
        return ctx
    return check
