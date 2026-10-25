"""Demo Studio: a prospect's website -> a sandboxed demo tenant with THEIR name (docs/GO-TO-MARKET.md §2).

The organisation itself is created by Agentry staff in the dashboard (Better Auth). This module fills it:
crawled pages -> knowledge base, brand (logo, colour) -> widget, industry pack -> persona/services/FAQs,
plus a sample inbox addressed to the business so triage can be shown. Demo tenants expire after 14 days and
never send real messages (status 'demo').
"""
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.db import system_session, tenant_session
from agentry.knowledge import Page, add_document, crawl
from agentry.packs import apply_pack, load_pack

DEMO_DAYS = 14

SAMPLE_INBOX = {
    "b2b-agency": [
        ("founder@newclient-example.com", "Need help with {topic}", "Hi {business} team, we're a growing D2C brand and need help with {topic}. Budget is around 1.5L a month. Can we talk this week?"),
        ("accounts@existing-client.example", "Invoice for last month", "Hi, could you resend last month's invoice? Our finance team will clear it by Friday."),
        ("deals@saas-tools.example", "50% off for agencies", "Upgrade now and save 50% on your annual plan. Limited time offer."),
    ],
    "dental-clinic": [
        ("priya.k@mail.example", "Appointment for cleaning", "Hello {business}, I'd like to book a teeth cleaning this Saturday morning if possible."),
        ("rahul.m@mail.example", "Severe tooth pain", "I have severe tooth pain since last night and my cheek is swelling. Can someone see me today? Urgent."),
        ("offers@dentalsupply.example", "Festive offer on supplies", "Flat 30% off on dental consumables this week only."),
    ],
    "home-services": [
        ("amit.s@mail.example", "Quote for {topic}", "Hi, I'm interested in {topic} for my 3BHK. Can someone visit this week for a quote?"),
        ("legal@society-office.example", "Notice regarding installation", "Please note the installation at Flat 402 must be completed by Monday as per society rules, failing which the permission lapses."),
        ("news@homeideas.example", "This week in home design", "Our weekly newsletter: 10 ideas for small balconies. Unsubscribe anytime."),
    ],
}


def business_name(pages: list[Page], fallback_url: str) -> str:
    home = pages[0] if pages else None
    for candidate in ((home.meta.get("og:site_name") if home else None), (home.title if home else None)):
        if candidate:
            name = re.split(r"\s+[|\-–—:]\s+", candidate.strip())[0].strip()
            if 2 <= len(name) <= 80:
                return name
    host = re.sub(r"^https?://(www\.)?", "", fallback_url).split("/")[0].split(".")[0]
    return host.replace("-", " ").title() or "Your Business"


def brand(pages: list[Page]) -> dict:
    meta = pages[0].meta if pages else {}
    colour = meta.get("theme-color")
    logo = meta.get("og:image") or meta.get("icon")
    return {k: v for k, v in {
        "color": colour if colour and re.fullmatch(r"#[0-9a-fA-F]{3,8}", colour) else None,
        "logo": logo if logo and logo.startswith("https://") else None,
        "description": meta.get("og:description") or meta.get("description"),
    }.items() if v}


async def preview(url: str) -> dict:
    pages = await crawl(url, max_pages=1)
    if not pages:
        raise ValueError("could not load that website")
    return {"name": business_name(pages, url), "brand": brand(pages), "url": pages[0].url}


async def build_demo(org_id: str, *, url: str, pack_key: str, created_by: str) -> dict:
    pack = load_pack(pack_key)
    async with system_session() as conn:
        org = (await conn.execute(text("select name, slug from auth.organization where id = :o"), {"o": org_id})).mappings().first()
        exists = (await conn.execute(text("select 1 from app.org_settings where org_id = :o"), {"o": org_id})).first()
    if not org:
        raise ValueError("organisation not found")
    if exists:
        raise ValueError("this organisation is already set up")
    pages = await crawl(url, max_pages=8)
    b = brand(pages)
    expires = datetime.now(UTC) + timedelta(days=DEMO_DAYS)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.org_settings (org_id, status, country, timezone, currency, website, brand, demo_expires_at, profile)
            values (:o, 'demo', 'IN', 'Asia/Kolkata', 'INR', :w, cast(:b as jsonb), :exp, cast(:p as jsonb))"""),
            {"o": org_id, "w": url, "b": json.dumps(b), "exp": expires,
             "p": json.dumps({"demo": {"created_by": created_by, "source_url": url, "pages": len(pages)}})})
    automations = {k: ("live" if k in ("website_chat", "inbox_triage") else "setup") for k in pack["featured"]}
    automations.setdefault("website_chat", "live")
    await apply_pack(org_id, pack_key, business=org["name"], currency="INR", automations=automations)
    for p in pages:
        if len(p.text) > 80:
            await add_document(org_id, source_type="url", title=p.title or p.url, content=p.text, source_ref=p.url)
    topic = (b.get("description") or pack["name"]).split(".")[0][:60].lower()
    for i, (sender, subject, body) in enumerate(SAMPLE_INBOX.get(pack_key, [])):
        await ingest_email(org_id, sender=sender, subject=subject.format(business=org["name"], topic=topic),
                           body=body.format(business=org["name"], topic=topic), thread_ref=f"demo-{i}")
    return {"org_id": org_id, "slug": org["slug"], "name": org["name"], "pages_learned": len(pages),
            "brand": b, "expires_at": expires.isoformat()}
