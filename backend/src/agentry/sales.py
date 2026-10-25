"""Agentry's own sales pipeline: demo requests from the website, worked in Agentry HQ.

new -> demo_built (Demo Studio) -> demo_sent (email with the demo link + video) -> in_talks (they replied) -> won / lost.
Every request is also a lead in Agentry's own organisation (slug 'agentry'), so Agentry's pipeline shows in its own
portal like any client's. After the demo email, follow-ups go out on days 2, 5 and 10 while the request is still
waiting on them (status demo_sent); any status change stops them.
"""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.leads import resolve_contact

STATUSES = ("new", "demo_built", "demo_sent", "in_talks", "won", "lost")
LEAD_STAGE = {"new": "new", "demo_built": "contacted", "demo_sent": "contacted", "in_talks": "engaged", "won": "won", "lost": "lost"}
FOLLOW_UP_DAYS = (2, 5, 10)  # after the demo email
NICHE_PACK = {"agency_or_firm": "b2b-agency", "clinic_or_appointments": "dental-clinic", "home_services": "home-services"}


class SalesError(ValueError):
    pass


async def agentry_org_id(conn: AsyncConnection) -> str | None:
    return (await conn.execute(text("select id from auth.organization where slug = 'agentry'"))).scalar_one_or_none()


async def get(demo_id: str) -> dict:
    async with system_session() as conn:
        row = (await conn.execute(text("select * from app.demo_requests where id = cast(:i as uuid)"), {"i": demo_id})).mappings().first()
    if not row:
        raise SalesError("demo request not found")
    return dict(row)


def first_name(d: dict) -> str:
    return (d.get("name") or "there").split()[0]


def public_link_problem() -> str | None:
    """Why demo links can't go to a prospect yet (they would point at this computer), or None when they can."""
    from urllib.parse import urlparse
    host = urlparse(settings.web_url).hostname or ""
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local"):
        return (f"Demo links point to {settings.web_url}, which only works on this computer. Put the website online "
                "(a tunnel or the real deployment) and set AGENTRY_WEB_URL to its public address before sending.")
    return None


def demo_link(d: dict) -> str | None:
    return f"{settings.web_url.rstrip('/')}/demo/{d['demo_slug']}" if d.get("demo_slug") else None


# ---------- emails (plain text, signed by a person: less likely to be filtered than a template) ----------

def confirmation_email(d: dict) -> tuple[str, str]:
    who = d.get("company") or "your business"
    body = (f"Hi {first_name(d)},\n\n"
            f"Thanks for asking for a demo. we're building one for {who} now: an AI assistant that already knows your "
            f"services, so you can try it as your own customers would.\n\n"
            f"You'll get a link and a 2-minute walkthrough video within one working day. If there's anything you'd like "
            f"the agents to handle first, just reply to this email.\n\n"
            f"{settings.sales_signature}")
    return f"Your Agentry demo for {who}", body


def demo_email(d: dict, video_url: str | None, note: str | None) -> tuple[str, str]:
    who = d.get("company") or "your business"
    body = f"Hi {first_name(d)},\n\nYour demo for {who} is ready:\n{demo_link(d)}\n\n"
    body += "Ask it anything your customers ask. It answers from your own website and can book appointments.\n\n"
    if video_url:
        body += f"Here's a 2-minute walkthrough: {video_url}\n\n"
    if note:
        body += note.strip() + "\n\n"
    body += "Would a 15-minute call this week work to see how it would run for you? Just reply with a time.\n\n" + settings.sales_signature
    return f"Your Agentry demo for {who} is ready", body


def follow_up_email(d: dict, n: int) -> tuple[str, str]:
    who = d.get("company") or "your business"
    link = demo_link(d)
    bodies = [
        f"Hi {first_name(d)},\n\nDid you get a chance to try the demo for {who}? {link}\n\nWe're happy to walk you through it on a short call. Reply with a time that suits you.\n\n{settings.sales_signature}",
        f"Hi {first_name(d)},\n\nA quick thought: most businesses start with one agent (answering enquiries or chasing invoices) and add more once they see the results. Which would help {who} most?\n\nThe demo is still here: {link}\n\n{settings.sales_signature}",
        f"Hi {first_name(d)},\n\nThis is our last follow-up. If now isn't the right time, no problem: just reply whenever you'd like to pick it up, and the demo for {who} can be refreshed.\n\n{settings.sales_signature}",
    ]
    return f"Re: Your Agentry demo for {who} is ready", bodies[min(n, len(bodies) - 1)]


# ---------- pipeline ----------

async def mirror_lead(demo_id: str) -> str | None:
    """Create the request's lead in Agentry's own organisation (once)."""
    d = await get(demo_id)
    if d["lead_id"]:
        return str(d["lead_id"])
    async with system_session() as conn:
        org = await agentry_org_id(conn)
    if not org:
        return None
    async with tenant_session(org) as conn:
        cid = await resolve_contact(conn, org, name=d["name"], email=d["email"], phone=d["phone"], company=d["company"], source="demo_request")
        lid = str((await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage, qualification)
            values (:o, cast(:c as uuid), 'demo_request', 'new', cast(:q as jsonb)) returning id"""),
            {"o": org, "c": cid, "q": json.dumps({k: d[k] for k in ("company", "website", "niche", "message") if d.get(k)})})).scalar_one())
    async with system_session() as conn:
        await conn.execute(text("update app.demo_requests set lead_id = cast(:l as uuid) where id = cast(:i as uuid)"), {"l": lid, "i": demo_id})
    return lid


async def update(demo_id: str, *, status: str | None = None, notes: str | None = None, **fields) -> dict:
    """Change a request (status, notes, demo, video, client) and keep its lead's stage in step."""
    if status and status not in STATUSES:
        raise SalesError(f"unknown status {status}")
    sets, params = ["updated_at = now()"], {"i": demo_id}
    for k, v in {"status": status, "notes": notes, **fields}.items():
        if v is not None:
            sets.append(f"{k} = :{k}")
            params[k] = v
    async with system_session() as conn:
        row = (await conn.execute(text(f"update app.demo_requests set {', '.join(sets)} where id = cast(:i as uuid) returning *"), params)).mappings().first()
        if not row:
            raise SalesError("demo request not found")
        org = await agentry_org_id(conn)
    if status and row["lead_id"] and org:
        async with tenant_session(org) as conn:
            await conn.execute(text("update app.leads set stage = :s, updated_at = now() where id = :l"),
                               {"s": LEAD_STAGE[status], "l": row["lead_id"]})
    return dict(row)


def next_follow_up(d: dict, now: datetime | None = None) -> tuple[str, float]:
    """('send', 0) when a follow-up is due, ('wait', seconds) until the next one, ('done', 0) when finished."""
    if d["status"] != "demo_sent" or not d["demo_sent_at"] or d["followups_sent"] >= len(FOLLOW_UP_DAYS):
        return "done", 0
    due = d["demo_sent_at"] + timedelta(days=FOLLOW_UP_DAYS[d["followups_sent"]])
    wait = (due - (now or datetime.now(UTC))).total_seconds()
    return ("send", 0) if wait <= 0 else ("wait", wait)


# ---------- proposals ----------

def proposal_link(token: str) -> str:
    return f"{settings.web_url.rstrip('/')}/proposal/{token}"


def proposal_email(snapshot: dict, contact: str | None, url: str, note: str | None) -> tuple[str, str]:
    business = snapshot.get("business") or "your business"
    lines = "\n".join(f"- {i['label']}: {i['amount']}" for i in snapshot.get("investment", []))
    agents = ", ".join(snapshot.get("agents", []))
    body = f"Hi {(contact or 'there').split()[0]},\n\nHere is our proposal for {business}:\n{url}\n\n"
    if note:
        body += note.strip() + "\n\n"
    body += f"In short: {agents}.\n{lines}\n\n"
    body += "You can download it as a PDF from that page. Reply to this email with any questions, or to get started.\n\n"
    return f"Agentry proposal for {business}", body + settings.sales_signature


async def create_proposal(*, email: str, snapshot: dict, plan: dict | None, note: str | None, demo_request_id: str | None,
                          sent_by: str | None) -> dict:
    import secrets
    token = secrets.token_urlsafe(18)
    async with system_session() as conn:
        row = (await conn.execute(text("""insert into app.proposals (token, demo_request_id, email, business, snapshot, plan, note, sent_by)
            values (:t, cast(:d as uuid), :e, :b, cast(:s as jsonb), cast(:p as jsonb), :n, :by) returning id, token, sent_at"""),
            {"t": token, "d": demo_request_id, "e": email, "b": snapshot.get("business") or email, "s": json.dumps(snapshot),
             "p": json.dumps(plan) if plan else None, "n": note, "by": sent_by})).mappings().one()
    return dict(row) | {"url": proposal_link(token)}


async def view_proposal(token: str) -> tuple[dict | None, bool]:
    """The proposal for its private link, counting the view. Returns (proposal, first_view)."""
    async with system_session() as conn:
        row = (await conn.execute(text("""update app.proposals set views = views + 1,
              first_viewed_at = coalesce(first_viewed_at, now())
            where token = :t returning id, demo_request_id, email, business, snapshot, sent_at, views"""), {"t": token})).mappings().first()
    return (dict(row), row["views"] == 1) if row else (None, False)
