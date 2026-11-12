"""Festival & seasonal campaigns (ROADMAP-V3 B3): plans ahead of Indian festivals, in the business's voice.

    calendar  the festivals (national, regional, religious, seasonal) with their dates for 2026 and 2027; lunar dates
              shift every year, so each business can correct a date in settings (festival_dates) and that's what counts
    plan      N days before a festival the business picked (settings): a theme, 3 posts, a WhatsApp message for opted-in
              customers, a greeting for the day and a timeline; the offer is only ever the business's own (settings, or
              none): an invented discount, number or price is flagged and rewritten once
    approve   the owner approves and copies the posts into Content / their apps; sending a WhatsApp broadcast needs an
              approved Meta template (campaigns), so nothing goes out from here by itself
"""
import json
import re
from datetime import UTC, date, datetime, timedelta

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

# key -> (name, {year: "MM-DD"}, tags). Lunar festivals are the best-known dates; correct them per business if needed.
FESTIVALS: dict[str, tuple[str, dict[int, str], tuple[str, ...]]] = {
    "new_year": ("New Year", {2026: "01-01", 2027: "01-01"}, ("national",)),
    "sankranti": ("Makar Sankranti / Pongal / Lohri", {2026: "01-14", 2027: "01-14"}, ("hindu", "regional")),
    "republic_day": ("Republic Day", {2026: "01-26", 2027: "01-26"}, ("national",)),
    "valentines": ("Valentine's Day", {2026: "02-14", 2027: "02-14"}, ("seasonal",)),
    "holi": ("Holi", {2026: "03-04", 2027: "03-22"}, ("hindu",)),
    "eid_ul_fitr": ("Eid ul-Fitr", {2026: "03-20", 2027: "03-10"}, ("muslim",)),
    "gudi_padwa_ugadi": ("Gudi Padwa / Ugadi", {2026: "03-19", 2027: "04-07"}, ("hindu", "regional")),
    "akshaya_tritiya": ("Akshaya Tritiya", {2026: "04-19", 2027: "05-09"}, ("hindu",)),
    "mothers_day": ("Mother's Day", {2026: "05-10", 2027: "05-09"}, ("seasonal",)),
    "independence_day": ("Independence Day", {2026: "08-15", 2027: "08-15"}, ("national",)),
    "raksha_bandhan": ("Raksha Bandhan", {2026: "08-28", 2027: "08-17"}, ("hindu",)),
    "onam": ("Onam", {2026: "08-26", 2027: "09-12"}, ("regional",)),
    "janmashtami": ("Janmashtami", {2026: "09-04", 2027: "08-25"}, ("hindu",)),
    "ganesh_chaturthi": ("Ganesh Chaturthi", {2026: "09-14", 2027: "09-04"}, ("hindu", "regional")),
    "navratri": ("Navratri begins", {2026: "10-11", 2027: "09-30"}, ("hindu",)),
    "dussehra": ("Dussehra", {2026: "10-20", 2027: "10-09"}, ("hindu",)),
    "karwa_chauth": ("Karwa Chauth", {2026: "10-29", 2027: "10-18"}, ("hindu", "regional")),
    "dhanteras": ("Dhanteras", {2026: "11-06", 2027: "10-27"}, ("hindu",)),
    "diwali": ("Diwali", {2026: "11-08", 2027: "10-29"}, ("hindu", "national")),
    "bhai_dooj": ("Bhai Dooj", {2026: "11-11", 2027: "10-31"}, ("hindu",)),
    "christmas": ("Christmas", {2026: "12-25", 2027: "12-25"}, ("christian", "seasonal")),
    "year_end_sale": ("Year-end", {2026: "12-28", 2027: "12-28"}, ("seasonal",)),
}
DEFAULT = ["new_year", "republic_day", "holi", "independence_day", "raksha_bandhan", "ganesh_chaturthi", "dussehra", "diwali", "christmas"]
# an offer-like claim ("free" only as an offer: "feel free to call" is fine)
NUMBERISH = re.compile(r"(₹|rs\.?)\s?[\d,]+|\b\d+\s?%|\bflat\s+\d+|\bbuy\s+\d+\s+get\s+\d+|"
                       r"\bfree\s+(gift|delivery|shipping|service|check[- ]?up|consult\w*|session|installation|sample|trial|visit|demo)\b", re.IGNORECASE)
RISKY = re.compile(r"\b(guarantee[sd]?|best in|#1|cheapest|lowest price|cure[sd]?)\b", re.IGNORECASE)


class FestivalConfig(BaseModel):
    festivals: list[str] = Field(default_factory=lambda: list(DEFAULT), title="Festivals to plan for", description=", ".join(FESTIVALS),
                                 json_schema_extra={"editable_by": "client"})
    lead_days: int = Field(21, ge=7, le=60, title="Plan this many days ahead", json_schema_extra={"editable_by": "client"})
    offers: dict[str, str] = Field(default_factory=dict, title="Your offer per festival (optional)", description="e.g. {\"diwali\": \"Free AC check-up with every service till 10 Nov\"}",
                                   json_schema_extra={"editable_by": "client"})
    festival_dates: dict[str, str] = Field(default_factory=dict, title="Correct a festival's date (YYYY-MM-DD)", json_schema_extra={"editable_by": "client"})
    language: str = Field("English", title="Language", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="festival_campaigns", name="Festival campaigns",
    description="Plans for Diwali, Holi, Eid, Christmas and more: posts, a WhatsApp message and a timeline, weeks ahead, with only your own offers.",
    config_model=FestivalConfig, metrics=(),
))


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'festival_campaigns'"))).first()
    return (row.status, FestivalConfig(**(row.config or {})).model_dump()) if row else (None, FestivalConfig().model_dump())


FIXED = ("new_year", "republic_day", "valentines", "independence_day", "christmas", "year_end_sale")


def festival_on(key: str, year: int) -> date | None:
    """A festival's date: the same day every year for fixed ones; for lunar ones the date in force (official_rules:
    festival.<key>.<year>, so next year's dates arrive through the daily check of official sources once announced)."""
    from agentry import official_rules
    dates = FESTIVALS[key][1]
    if key in FIXED:
        mmdd = next(iter(dates.values()))
        return date.fromisoformat(f"{year}-{mmdd}")
    return official_rules.festival_date(key, year)


def upcoming(cfg: dict, today: date, days: int) -> list[dict]:
    out = []
    for key in cfg["festivals"]:
        if key not in FESTIVALS:
            continue
        name = FESTIVALS[key][0]
        for y in (today.year, today.year + 1):
            override = cfg["festival_dates"].get(key)
            try:
                d = date.fromisoformat(override) if override and override.startswith(str(y)) else festival_on(key, y)
            except ValueError:
                d = None
            if d and today <= d <= today + timedelta(days=days):
                out.append({"key": key, "name": name, "date": d, "lunar": key not in FIXED})
    return sorted(out, key=lambda f: f["date"])


def plan_problems(p: dict, offer: str | None) -> list[str]:
    out = []
    if not isinstance(p.get("posts"), list) or len(p["posts"]) < 2 or not p.get("whatsapp"):
        out.append("needs posts and a WhatsApp message")
    words = " ".join([p.get("theme") or "", p.get("whatsapp") or "", p.get("greeting") or "", *[x.get("text", "") for x in p.get("posts") or [] if isinstance(x, dict)]])
    if m := RISKY.search(words):
        out.append(f"risky wording: \"{m.group(0)}\"")
    for m in NUMBERISH.finditer(words):
        if not offer or m.group(0).lower() not in offer.lower():
            out.append(f"\"{m.group(0)}\" isn't part of your offer")
            break
    return out


async def make_plan(org_id: str, key: str, on: date) -> dict:
    from agentry.automations.video_studio import context
    async with tenant_session(org_id) as conn:
        _s, cfg = await settings_of(conn)
        ctx = await context(conn, org_id, {"topics": []})
    name = FESTIVALS[key][0]
    offer = cfg["offers"].get(key)
    mock = {"theme": f"Celebrating {name} with our customers",
            "posts": [{"platform": p, "text": f"Wishing you a joyful {name} from all of us at {ctx['business']}!{(' ' + offer) if offer else ''} #{key.replace('_', '')} #Festive #India"}
                      for p in ("instagram", "facebook", "linkedin")],
            "whatsapp": f"Happy {name} from {ctx['business']}!{(' ' + offer) if offer else ''} Reply here if we can help.",
            "greeting": f"Happy {name}! 🪔", "timeline": [{"when": "7 days before", "what": "Post 1 and the WhatsApp message"},
                                                             {"when": "2 days before", "what": "Post 2"}, {"when": "On the day", "what": "The greeting"}]}
    prompt = load("festival_campaign")
    p, probs = {}, []
    for _ in range(2):
        msgs = prompt.render(business=ctx["business"], about=ctx["about"], services=ctx["services"], festival=name, date=f"{on:%d %B %Y}",
                             offer=offer or "none", language=cfg["language"])
        if probs:
            msgs.append({"role": "user", "content": "Fix these problems: " + "; ".join(probs)})
        try:
            r = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                               mock_response=json.dumps(mock), temperature=0.7)
            p = r.data if isinstance(r.data, dict) else {}
        except AllModelsFailed as e:
            raise ValueError("the writing models are busy: try again in a few minutes") from e
        probs = plan_problems(p, offer)
        if not probs:
            break
    async with tenant_session(org_id) as conn:
        pid = (await conn.execute(text("""insert into app.festival_plans (org_id, festival, name, on_date, plan, checks, status)
            values (:o, :k, :n, :d, cast(:p as jsonb), cast(:c as jsonb), :s) on conflict (org_id, festival, on_date) do nothing returning id::text"""),
            {"o": org_id, "k": key, "n": name, "d": on, "p": json.dumps(p), "c": json.dumps(probs), "s": "needs_attention" if probs else "draft"})).scalar_one_or_none()
        if pid:
            await conn.execute(text("insert into app.approvals (org_id, kind, automation_key, title, body) values (:o, 'escalation', 'festival_campaigns', :t, :b)"),
                               {"o": org_id, "t": f"{name} campaign plan is ready ({on:%d %b})", "b": p.get("theme") or ""})
    return {"id": pid, "status": "needs_attention" if probs else "draft", "problems": probs}


async def daily(org_id: str, today: date | None = None) -> int:
    today = today or datetime.now(UTC).date()
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        have = {(r.festival, r.on_date) for r in (await conn.execute(text("select festival, on_date from app.festival_plans"))).all()}
    if status not in ("live", "approval_mode"):
        return 0
    n = 0
    for f in upcoming(cfg, today, cfg["lead_days"]):
        if (f["key"], f["date"]) not in have:
            try:
                await make_plan(org_id, f["key"], f["date"])
                n += 1
            except ValueError:
                break
    return n


async def festival_jobs() -> int:
    from agentry import official_rules
    await official_rules.fresh()  # next year's festival dates, once approved
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'festival_campaigns'
            and status in ('live','approval_mode')"""))).scalars())
    return sum([await daily(o) for o in orgs])


@DBOS.step()
async def festival_step() -> int:
    return await festival_jobs()


@DBOS.workflow()
async def festival_schedule(scheduled_time: datetime, context) -> None:
    await festival_step()
