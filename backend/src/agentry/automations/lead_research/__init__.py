"""Lead Research & Meeting Prep (ROADMAP-V2 9.4).

    lead.created     -> the lead's company website (from a work email or a website they gave) is read, and the `fast`
                        model writes a short note: what they do, size, decision maker, likely need, talking points,
                        questions. Facts must come from their pages: names and numbers the pages don't contain are dropped.
                        Personal addresses (gmail.com...) get a note from what they told us only.
    booking.created  -> 30 minutes (setting) before the meeting, a one-page brief: who, when, the research, what they said,
                        their history with the business. It goes to the team through the Notification Center
                        (event meeting.brief: Telegram / email / in-app, default rule "Meeting briefs").
"""
import json
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import runs
from agentry.automations import AutomationTemplate, register
from agentry.automations.cold_email.providers import SitePage, _domain
from agentry.automations.cold_email.research import DECIDES, _pages_text, people_by_pattern, snippets
from agentry.db import tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.worker.handlers import on

MAX_SLEEP = 86400
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "live.com", "icloud.com", "me.com",
             "rediffmail.com", "proton.me", "protonmail.com", "aol.com", "zoho.com", "ymail.com", "msn.com"}
NUMBER = re.compile(r"\d[\d,.]*")


class LeadResearchConfig(BaseModel):
    brief_minutes_before: int = Field(30, ge=5, le=240, title="Send the meeting brief (minutes before)", json_schema_extra={"editable_by": "client"})
    read_websites: bool = Field(True, title="Read the lead's company website", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="lead_research",
    name="Lead research & meeting prep",
    description="Researches every new lead's company within minutes and sends a one-page brief before each meeting.",
    config_model=LeadResearchConfig,
    metrics=("leads_researched",),
))


async def _status(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'lead_research'"))).first()
    return (row.status, LeadResearchConfig(**(row.config or {})).model_dump()) if row else (None, LeadResearchConfig().model_dump())


def company_domain(email: str | None, website: str | None) -> str | None:
    """The lead's company site: a website they gave, else their work email's domain (never gmail.com and friends)."""
    if website and (d := _domain(website if "://" in website else f"https://{website}")):
        return d
    d = (email or "").rsplit("@", 1)[-1].lower() if email and "@" in email else None
    return d if d and d not in FREE_MAIL else None


async def fetch_pages(domain: str) -> list[SitePage]:
    """The lead's website (a few pages). The sample businesses of the cold-email mock data are read from the sample; a
    real site is fetched (public addresses only, same checks as the knowledge crawler)."""
    from agentry.automations.cold_email.providers import MockProviders
    pages = await MockProviders().read_site(f"https://{domain}")
    if pages:
        return pages
    from agentry.knowledge import crawl
    try:
        return [SitePage(url=p.url, title=p.title, text=p.text) for p in await crawl(f"https://{domain}", max_pages=4, timeout=8.0)]
    except Exception:  # noqa: BLE001 - an unreachable or unsafe site just means no website facts
        return []


def ground(note: dict, pages: list[SitePage], said: str) -> dict:
    """Keep only what the sources support: a decision maker the pages name, numbers that appear in the sources."""
    source = (_pages_text(pages, limit=10**6) + "\n" + said).lower()
    numbers = {n.strip(".,") for n in NUMBER.findall(source)}

    def ok(s: object) -> bool:
        return isinstance(s, str) and bool(s.strip()) and all(n.strip(".,") in numbers for n in NUMBER.findall(s))

    out = {k: (note.get(k) if ok(note.get(k)) else None) for k in ("company", "what_they_do", "size", "likely_need")}
    dm = note.get("decision_maker")
    out["decision_maker"] = ({"name": dm["name"].strip(), "role": (dm.get("role") or "").strip() or None}
                             if isinstance(dm, dict) and isinstance(dm.get("name"), str) and dm["name"].strip()
                             and dm["name"].strip().lower() in source and DECIDES.search(dm.get("role") or "") else None)
    for k in ("talking_points", "questions"):
        out[k] = [s.strip() for s in (note.get(k) or []) if ok(s)][:3]
    return out


def heuristic_note(pages: list[SitePage], said: str) -> dict:
    """The mock / fallback note: built from the pages and the lead's words without a model."""
    people = [p for p in people_by_pattern(pages) if p.decides]
    snips = snippets(pages, limit=3)
    first = pages[0] if pages else None
    return {"company": first.title if first else None, "what_they_do": snips[0]["text"] if snips else None, "size": None,
            "decision_maker": {"name": people[0].name, "role": people[0].role} if people else None,
            "likely_need": said[:200] or None, "talking_points": [s["text"] for s in snips[1:3]],
            "questions": ["What made you get in touch now?", "Who else is involved in the decision?"]}


async def _lead(conn: AsyncConnection, lead_id: str) -> dict | None:
    row = (await conn.execute(text("""select l.id::text, l.source, l.qualification, l.conversation_id::text, l.research, k.id::text as contact_id,
            k.name, k.email, k.phone_e164, k.company, k.attributes->>'website' as website
        from app.leads l join app.contacts k on k.id = l.contact_id where l.id = cast(:i as uuid)"""), {"i": lead_id})).mappings().first()
    return dict(row) if row else None


async def _said(conn: AsyncConnection, lead: dict, limit: int = 4) -> str:
    q = lead.get("qualification") or {}
    bits = [f"{k.replace('_', ' ')}: {v}" for k, v in q.items() if isinstance(v, str) and v and k in ("need", "interest", "budget", "timeline", "notes", "message")]
    if lead.get("conversation_id"):
        msgs = (await conn.execute(text("""select body from app.messages where conversation_id = cast(:c as uuid) and direction = 'in'
            and body is not null order by created_at limit :n"""), {"c": lead["conversation_id"], "n": limit})).scalars().all()
        bits += [m[:400] for m in msgs]
    return "\n".join(bits)


async def research(org_id: str, lead_id: str) -> dict:
    """Research one lead now and store the note on it (leads.research). Safe to repeat."""
    async with runs.run(org_id, "lead_research", "research", key=f"research:{lead_id}", subject=("lead", lead_id)) as r:
        async with tenant_session(org_id) as conn:
            lead = await _lead(conn, lead_id)
            if not lead:
                return {"status": "missing"}
            _st, cfg = await _status(conn)
            said = await _said(conn, lead)
            us = (await conn.execute(text("""select o.name, s.profile from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().first()
            offer = ", ".join((await conn.execute(text("select name from app.services where active order by name limit 8"))).scalars()) \
                or ((us or {}).get("profile") or {}).get("description") or "our services"
        domain = company_domain(lead["email"], lead["website"])
        pages = await fetch_pages(domain) if domain and cfg["read_websites"] else []
        r.step("read_site", domain=domain, pages=len(pages))
        fallback = heuristic_note(pages, said)
        prompt = load("lead_research")
        try:
            res = await complete(prompt.tier, prompt.render(business=(us or {}).get("name") or "us", our_offer=offer,
                                                            lead=f"{lead['name'] or 'unknown'} <{lead['email'] or lead['phone_e164'] or ''}>",
                                                            said=said or "(nothing yet)", domain=domain or "none", pages=_pages_text(pages) or "(none)"),
                                 org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                                 mock_response=json.dumps(fallback))
            note = res.data if isinstance(res.data, dict) else fallback
        except AllModelsFailed:
            note = fallback
        note = ground(note, pages, said)
        note.update({"status": "done" if pages else ("no_site" if domain else "no_company"), "domain": domain,
                     "sources": [p.url for p in pages], "at": datetime.now(UTC).isoformat()})
        r.step("note", status=note["status"], decision_maker=bool(note["decision_maker"]))
        async with tenant_session(org_id) as conn:
            await conn.execute(text("update app.leads set research = cast(:r as jsonb) where id = cast(:i as uuid)"), {"r": json.dumps(note), "i": lead_id})
            if note["company"]:
                await conn.execute(text("update app.contacts set company = coalesce(company, :c) where id = cast(:k as uuid)"),
                                   {"c": note["company"][:200], "k": lead["contact_id"]})
            await emit(conn, org_id, "lead.researched", {"lead_id": lead_id, "status": note["status"], "company": note["company"]})
    return note


@DBOS.step()
async def research_step(org_id: str, lead_id: str) -> str:
    async with tenant_session(org_id) as conn:
        status, _cfg = await _status(conn)
    if status not in ("live", "approval_mode"):
        return "off"
    return (await research(org_id, lead_id)).get("status", "missing")


@on("lead.created")
@DBOS.workflow()
async def research_new_lead(event: dict) -> None:
    await research_step(event["org_id"], event["payload"]["lead_id"])


# ---------- the meeting brief ----------

def _lines(note: dict | None) -> list[str]:
    if not note:
        return []
    out = []
    if note.get("company"):
        out.append(f"Company: {note['company']}")
    if note.get("what_they_do"):
        out.append(f"What they do: {note['what_they_do']}")
    if note.get("size"):
        out.append(f"Size: {note['size']}")
    if dm := note.get("decision_maker"):
        out.append(f"Decision maker: {dm['name']}" + (f" ({dm['role']})" if dm.get("role") else ""))
    if note.get("likely_need"):
        out.append(f"Likely need: {note['likely_need']}")
    out += [f"• {t}" for t in note.get("talking_points") or []]
    if note.get("questions"):
        out.append("Ask: " + " / ".join(note["questions"]))
    return out


async def build_brief(org_id: str, booking_id: str) -> dict | None:
    """The one-page brief for an appointment: the lead's research (made now if missing), what they said, their history."""
    async with tenant_session(org_id) as conn:
        b = (await conn.execute(text("""select b.id::text, b.starts_at, b.status, b.lead_id::text, b.contact_id::text, s.name as service, st.name as staff,
                k.name, k.email, k.phone_e164, o.timezone
            from app.bookings b join app.services s on s.id = b.service_id join app.staff st on st.id = b.staff_id
            left join app.contacts k on k.id = b.contact_id join app.org_settings o on o.org_id = b.org_id where b.id = cast(:i as uuid)"""),
            {"i": booking_id})).mappings().first()
        if not b or b["status"] not in ("booked", "confirmed"):
            return None
        lead_id = b["lead_id"] or (await conn.execute(text("""select id::text from app.leads where contact_id = cast(:k as uuid)
            order by created_at desc limit 1"""), {"k": b["contact_id"]})).scalar_one_or_none()
        lead = await _lead(conn, lead_id) if lead_id else None
        said = await _said(conn, lead) if lead else ""
        history = (await conn.execute(text("""select count(*) filter (where status = 'showed') as visits, count(*) filter (where status = 'no_show') as missed,
                max(starts_at) filter (where status = 'showed') as last_visit
            from app.bookings where contact_id = cast(:k as uuid) and id <> cast(:i as uuid)"""), {"k": b["contact_id"], "i": booking_id})).mappings().one()
    note = (lead or {}).get("research")
    if lead and not note:
        note = await research(org_id, lead_id)
    tz = ZoneInfo(b["timezone"] or "Asia/Kolkata")
    at = b["starts_at"].astimezone(tz).strftime("%I:%M %p").lstrip("0")
    who = b["name"] or b["email"] or b["phone_e164"] or "a customer"
    lines = [f"{b['service']} with {b['staff']} at {at}. Contact: {' · '.join(x for x in (b['phone_e164'], b['email']) if x) or 'none on file'}."]
    lines += _lines(note)
    if said:
        lines.append("They said: " + said.replace("\n", " / ")[:500])
    lines.append(f"History: {history['visits']} earlier visit{'s' if history['visits'] != 1 else ''}"
                 + (f", last on {history['last_visit'].astimezone(tz).strftime('%d %b %Y')}" if history["last_visit"] else "")
                 + (f", {history['missed']} missed" if history["missed"] else "") + "." if history["visits"] or history["missed"] else "History: first visit.")
    return {"title": f"Brief: {who}, {b['service']} at {at}", "body": "\n".join(lines), "lead_id": lead_id}


@DBOS.step()
async def brief_plan(org_id: str, booking_id: str) -> str | None:
    async with tenant_session(org_id) as conn:
        status, cfg = await _status(conn)
        starts = (await conn.execute(text("select starts_at from app.bookings where id = cast(:i as uuid)"), {"i": booking_id})).scalar_one_or_none()
    if status not in ("live", "approval_mode") or not starts:
        return None
    at = starts - timedelta(minutes=cfg["brief_minutes_before"])
    return max(at, datetime.now(UTC)).isoformat() if starts > datetime.now(UTC) else None


@DBOS.step()
async def send_brief(org_id: str, booking_id: str) -> str:
    brief = await build_brief(org_id, booking_id)
    if not brief:
        return "skipped"
    async with tenant_session(org_id) as conn:
        if (await conn.execute(text("select brief ? 'sent_at' from app.bookings where id = cast(:i as uuid)"), {"i": booking_id})).scalar_one():
            return "already"
        eid = await emit(conn, org_id, "meeting.brief", {"booking_id": booking_id, "lead_id": brief["lead_id"], "title": brief["title"], "body": brief["body"]})
        await conn.execute(text("update app.bookings set brief = cast(:b as jsonb) where id = cast(:i as uuid)"),
                           {"b": json.dumps({**brief, "sent_at": datetime.now(UTC).isoformat(), "event_id": eid}), "i": booking_id})
    return "sent"


@on("booking.created")
@DBOS.workflow()
async def brief_before_meeting(event: dict) -> None:
    org_id, bid = event["org_id"], event["payload"]["booking_id"]
    when = await brief_plan(org_id, bid)
    if not when:
        return
    target = datetime.fromisoformat(when)
    while (left := (target - datetime.now(UTC)).total_seconds()) > 1:
        await DBOS.sleep_async(min(left, MAX_SLEEP))
    await send_brief(org_id, bid)
