"""AgentSpec: one agent definition (persona, knowledge, qualification, tools, safety) used on any channel.

Built from the organisation's settings, so the website chat, receptionist and WhatsApp agents of a client share
one "brain" (docs/PLAN.md §2.3).
"""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from agentry.db import tenant_session


@dataclass
class AgentSpec:
    org_id: str
    business: str
    name: str
    tone: str
    greeting: str
    timezone: str
    qualification: list[dict]
    qualified_when: str
    safety: str | None
    services: list[dict]
    city: str | None = None

    def system_prompt(self, channel: str = "web_chat") -> str:
        now = datetime.now(ZoneInfo(self.timezone))
        questions = "\n".join(f"- {q['key']}: {q['question']}" for q in self.qualification)
        services = "\n".join(
            f"- {s['key']}: {s['name']}, {s['minutes']} min" + (f", price {s['price']:g}" if s.get("price") else "")
            for s in self.services) or "- (none listed)"
        where = {"web_chat": "website chat", "voice": "phone line", "whatsapp": "WhatsApp"}.get(channel, channel)
        style = ("This is a spoken phone call: reply in one or two short sentences (under 35 words), no lists, no symbols "
                 "or URLs; say times and prices the way a person would say them aloud; ask one question at a time. Call people by the name "
                 "they give, without adding titles like Mr or Ms."
                 if channel == "voice" else "Keep each reply under 70 words, plain text, no markdown headings.")
        return f"""You are {self.name}, the AI assistant on {self.business}'s {where}{f" ({self.city})" if self.city else ""}.
Tone: {self.tone}. {style}

Your goals, in order:
1. Help. Answer questions using the search_knowledge tool. Never invent prices, policies, offers or availability:
   if the knowledge doesn't cover it, say you'll have the team confirm.
2. Qualify, gently. Over the conversation, learn the answers to these (one question per message, skip anything
   already answered, never interrogate):
{questions}
   Record what you learn with save_lead as soon as you know the need, and update it as you learn more.
3. Book. A visitor is qualified when: {self.qualified_when}. Then offer to book: use check_availability, offer 2-3
   times, and before book_appointment confirm the service, time, their name and phone number.
4. Not a fit? Give a helpful answer with no hard sell.

Hand off with handoff_to_human when they ask for a person, are upset or complaining, or you cannot help.
{f"Safety: {self.safety}" if self.safety else ""}
If asked, say clearly that you are an AI assistant.

Services (use these keys with the tools):
{services}

Today is {now:%A %d %B %Y}, {now:%H:%M} ({self.timezone}). Interpret "tomorrow", "Saturday" etc. relative to this."""


async def load_spec(org_id: str) -> AgentSpec:
    async with tenant_session(org_id) as conn:
        s = (await conn.execute(text("""select s.timezone, s.persona, s.qualification, s.profile, o.name
            from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
        services = (await conn.execute(text("select key, name, minutes, price from app.services where active order by name"))).mappings().all()
    p, profile = s["persona"] or {}, s["profile"] or {}
    return AgentSpec(
        org_id=org_id, business=s["name"], name=p.get("name", "Assistant"), tone=p.get("tone", "friendly and helpful"),
        greeting=p.get("greeting") or f"Hi! I'm {s['name']}'s AI assistant. How can I help?",
        timezone=s["timezone"], qualification=s["qualification"] or [],
        qualified_when=profile.get("qualified_when") or "they need a service the business offers",
        safety=profile.get("safety"), city=profile.get("city"),
        services=[{**dict(x), "price": float(x["price"]) if x["price"] is not None else None} for x in services],
    )
