"""AI visibility (MARKET-2026, PLAN-TRY-IT-AND-AI-VISIBILITY B): do ChatGPT, Gemini and Perplexity name the business when
customers ask, compared with its competitors, and what to fix.

    setup     what the business does as a customer would say it ("dentist"), city and area, other names, competitors
              ("Name — website"; taken from Competitor watch when empty) and 10-20 questions (suggested, editable)
    check     every question to every engine with web search on, each asked ai_visibility_repeats times (answers vary);
              the businesses named are read from each answer and matched to the business and its competitors
              (ai_search.py); monthly on the 1st and "Check now" (2 a month)
    score     named in N of M answers, per engine, average position, share against competitors, sites the assistants cite,
              businesses named instead, change since last month
    fixes     website (LocalBusiness / FAQ structured data, llms.txt; code ready to paste), listings on the sites the
              assistants cite, reviews when others are named for theirs, an answer page per question where the business
              is never named (written by Local SEO when the client has it)
The score is an estimate measured the same way each month: assistants' API answers are close to, not the same as, the apps.
"""
import asyncio
import json
import re
from datetime import UTC, datetime

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import ai_search
from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.worker.handlers import on

MANUAL_PER_MONTH = 2
DIRECTORIES = ("practo", "justdial", "sulekha", "google", "maps", "yelp", "tripadvisor", "indiamart", "lybrate", "zomato",
               "urbancompany", "housejoy", "facebook", "instagram", "linkedin", "clutch", "goodfirms", "quora", "reddit")


class VisConfig(BaseModel):
    service: str | None = Field(None, title="What you do, as a customer would say it", description="e.g. 'dentist', 'AC repair', 'CA firm'",
                                json_schema_extra={"editable_by": "client"})
    city: str | None = Field(None, title="City", json_schema_extra={"editable_by": "client"})
    area: str | None = Field(None, title="Area or neighbourhood (optional)", json_schema_extra={"editable_by": "client"})
    other_names: list[str] = Field(default_factory=list, title="Other names people use for you", json_schema_extra={"editable_by": "client"})
    competitors: list[str] = Field(default_factory=list, title="Competitors", description="One per line: 'Name — website' (website optional)",
                                   json_schema_extra={"editable_by": "client"})
    questions: list[str] = Field(default_factory=list, title="Questions customers ask", description="Empty = suggested from what you do and where",
                                 json_schema_extra={"editable_by": "client"})
    monthly: bool = Field(True, title="Check on the 1st of each month", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ai_visibility", name="AI visibility",
    description="Checks every month whether ChatGPT, Gemini and Perplexity recommend you when customers ask, against your competitors, and what to fix.",
    config_model=VisConfig, metrics=(),
))


def parse_competitor(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    url = re.search(r"(https?://\S+|\b[\w-]+(\.[\w-]+)+\.?[a-z]{2,}\S*)", line)
    name = re.split(r"\s+[—–-]\s+|\s*\|\s*|\s*,\s*", line)[0].strip()
    if url and name == url.group(0):
        name = ai_search.domain_root(url.group(0)).replace("-", " ").title()
    return {"name": name[:120], "website": url.group(0) if url else None}


async def setup_of(conn: AsyncConnection, org_id: str) -> dict:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'ai_visibility'"))).first()
    cfg = VisConfig(**((row.config or {}) if row else {})).model_dump()
    name = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    s = (await conn.execute(text("select website, profile from app.org_settings"))).mappings().first() or {}
    profile = s.get("profile") or {}
    comps = [c for c in (parse_competitor(x) for x in cfg["competitors"]) if c]
    if not comps:  # Competitor watch's list, if the client has it
        rows = (await conn.execute(text("select distinct on (name) name, url from app.watchers where kind in ('page','price') order by name, created_at"))).all()
        comps = [{"name": r.name, "website": r.url} for r in rows][:8]
    city = cfg["city"] or profile.get("city")
    service = cfg["service"]
    questions = [q.strip() for q in cfg["questions"] if q.strip()][:20]
    if not questions and service and city:
        questions = ai_search.questions_for(service, city, cfg["area"])
    return {"status": row.status if row else None, "config": cfg, "business": name, "website": s.get("website"),
            "phone": profile.get("phone"), "address": profile.get("address"), "city": city, "service": service,
            "me": {"name": name, "aliases": cfg["other_names"], "website": s.get("website")},
            "competitors": comps[:8], "questions": questions}


def missing_setup(setup: dict) -> str | None:
    if not setup["questions"]:
        return "add what you do and your city (or your own questions) in settings first"
    return None


async def start_check(org_id: str, *, trigger: str = "manual", created_by: str | None = None) -> str:
    """Queue a check. Raises ValueError when it can't run (setup missing, one already running, monthly manual limit)."""
    async with tenant_session(org_id) as conn:
        setup = await setup_of(conn, org_id)
        if why := missing_setup(setup):
            raise ValueError(why)
        busy = (await conn.execute(text("select count(*) from app.ai_vis_runs where status in ('queued','running') and created_at > now() - interval '1 hour'"))).scalar_one()
        if busy:
            raise ValueError("a check is already running")
        if trigger == "manual":
            month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            n = (await conn.execute(text("select count(*) from app.ai_vis_runs where trigger = 'manual' and created_at >= :m"), {"m": month})).scalar_one()
            if n >= MANUAL_PER_MONTH:
                raise ValueError(f"{MANUAL_PER_MONTH} extra checks a month are included; the next one runs on the 1st")
        engines, mock = ai_search.active()
        record = {k: setup[k] for k in ("business", "website", "city", "service", "competitors", "questions", "me")} | {"engines": engines}
        rid = str((await conn.execute(text("""insert into app.ai_vis_runs (org_id, trigger, setup, mock, created_by)
            values (:o, :t, cast(:s as jsonb), :m, :b) returning id"""), {"o": org_id, "t": trigger, "s": json.dumps(record), "m": mock, "b": created_by})).scalar_one())
        from agentry.events import emit
        await emit(conn, org_id, "ai_visibility.check", {"run_id": rid})
    return rid


async def _one(sem: asyncio.Semaphore, org_id: str, engine: str, model: str, q: str, rep: int, setup: dict) -> dict:
    async with sem:
        a = await ai_search.ask(engine, model, q, city=setup.get("city"), org_id=org_id, prompt_key="ai_visibility", repeat=rep,
                                mock_names=[setup["me"]["name"], *[c["name"] for c in setup["competitors"]]])
        named = ai_search.mark(await ai_search.extract(a, org_id=org_id), setup["me"], setup["competitors"]) if not a.error else []
    return {"engine": engine, "question": q, "repeat": rep, "answer": a.text, "citations": a.citations, "named": named,
            "error": a.error, "cost": a.cost_usd}


async def run_check(org_id: str, run_id: str) -> dict:
    async with tenant_session(org_id) as conn:
        run = (await conn.execute(text("select * from app.ai_vis_runs where id = cast(:i as uuid)"), {"i": run_id})).mappings().first()
        if not run or run["status"] not in ("queued", "running"):
            return {"status": run["status"] if run else "missing"}
        await conn.execute(text("update app.ai_vis_runs set status = 'running' where id = cast(:i as uuid)"), {"i": run_id})
    setup = dict(run["setup"])
    sem = asyncio.Semaphore(4)
    reps = max(1, settings.ai_visibility_repeats)
    jobs = [_one(sem, org_id, e, m, q, r, setup) for q in setup["questions"] for e, m in setup["engines"].items() for r in range(reps)]
    try:
        answers = await asyncio.gather(*jobs)
    except Exception as e:  # noqa: BLE001 - recorded on the run; the next month tries again
        async with tenant_session(org_id) as conn:
            await conn.execute(text("update app.ai_vis_runs set status = 'failed', error = :e, finished_at = now() where id = cast(:i as uuid)"),
                               {"e": f"{type(e).__name__}: {e}"[:400], "i": run_id})
        return {"status": "failed"}
    sc = ai_search.score(answers, setup["competitors"])
    async with tenant_session(org_id) as conn:
        prev = (await conn.execute(text("""select score from app.ai_vis_runs where status = 'done' and id <> cast(:i as uuid)
            order by created_at desc limit 1"""), {"i": run_id})).scalar_one_or_none()
        sc["previous_rate"] = prev.get("rate") if prev else None
        sc["questions"] = per_question(answers)
        sc["fixes"] = await fixes(conn, org_id, setup, answers, sc)
        for a in answers:
            me = next((n["position"] for n in a["named"] if n["who"] == "me"), None)
            await conn.execute(text("""insert into app.ai_vis_answers (org_id, run_id, engine, question, repeat, answer, citations, named, me_position, error)
                values (:o, cast(:r as uuid), :e, :q, :rep, :a, cast(:c as jsonb), cast(:n as jsonb), :mp, :err)"""),
                {"o": org_id, "r": run_id, "e": a["engine"], "q": a["question"], "rep": a["repeat"], "a": a["answer"][:20000],
                 "c": json.dumps(a["citations"][:30]), "n": json.dumps(a["named"]), "mp": me, "err": a["error"]})
        cost = round(sum(a["cost"] for a in answers), 4)
        failed_all = sc["asked"] == 0
        await conn.execute(text("""update app.ai_vis_runs set status = :s, score = cast(:sc as jsonb), cost_usd = :c, finished_at = now(),
            error = :e where id = cast(:i as uuid)"""), {"s": "failed" if failed_all else "done", "sc": json.dumps(sc), "c": cost, "i": run_id,
            "e": "every assistant failed to answer: try again later" if failed_all else None})
        if run["trigger"] == "monthly" and not failed_all:
            change = f" ({'up' if sc['rate'] >= sc['previous_rate'] else 'down'} from {sc['previous_rate']}%)" if sc["previous_rate"] is not None else ""
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body) values (:o, 'escalation', 'ai_visibility', :t, :b)"""),
                               {"o": org_id, "t": "This month's AI visibility check is ready",
                                "b": f"AI assistants named you in {sc['named']} of {sc['asked']} answers: {sc['rate']}%{change}. {len(sc['fixes'])} fix(es) to look at."})
    return {"status": "failed" if failed_all else "done", "score": sc}


def per_question(answers: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for a in answers:
        if a["error"]:
            continue
        q = out.setdefault(a["question"], {"question": a["question"], "asked": 0, "named": 0, "best_position": None, "others": {}})
        q["asked"] += 1
        me = next((n["position"] for n in a["named"] if n["who"] == "me"), None)
        if me:
            q["named"] += 1
            q["best_position"] = min(q["best_position"] or me, me)
        for n in a["named"]:
            if n["who"] != "me":
                q["others"][n["name"]] = q["others"].get(n["name"], 0) + 1
    return [{**q, "others": [k for k, _ in sorted(q["others"].items(), key=lambda kv: -kv[1])[:4]]} for q in out.values()]


def local_business_jsonld(setup: dict) -> str:
    d = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": setup["business"], "url": setup.get("website") or None,
         "telephone": setup.get("phone") or None, "areaServed": setup.get("city") or None,
         "address": {"@type": "PostalAddress", "streetAddress": setup.get("address"), "addressLocality": setup.get("city"), "addressCountry": "IN"}
         if setup.get("address") or setup.get("city") else None,
         "sameAs": []}
    d = {k: v for k, v in d.items() if v not in (None, "")}
    return f'<script type="application/ld+json">\n{json.dumps(d, indent=2, ensure_ascii=False)}\n</script>'


def llms_txt(setup: dict, services: list[str]) -> str:
    lines = [f"# {setup['business']}", "", f"> {setup.get('service') or 'Business'} in {setup.get('city') or 'India'}.", ""]
    if services:
        lines += ["## Services", *[f"- {s}" for s in services[:20]], ""]
    lines += ["## Contact", *([f"- Phone: {setup['phone']}"] if setup.get("phone") else []), *([f"- Address: {setup['address']}"] if setup.get("address") else []),
              *([f"- Website: {setup['website']}"] if setup.get("website") else [])]
    return "\n".join(lines)


async def site_schema(website: str | None) -> set[str] | None:
    """Structured data types on the home page, or None when it can't be read."""
    if not website:
        return None
    from agentry.automations.local_seo import crawl
    try:
        pages, _site = await crawl(website, 2)
    except Exception:  # noqa: BLE001 - a site we can't read just gets the general advice
        return None
    return {t for p in pages for t in p["jsonld"]} if pages else None


async def fixes(conn: AsyncConnection, org_id: str, setup: dict, answers: list[dict], sc: dict) -> list[dict]:
    out = []
    types = await site_schema(setup.get("website"))
    services = list((await conn.execute(text("select name from app.services where active order by name limit 20"))).scalars())
    has_lb = types is not None and any(t.endswith("Business") or t in ("Dentist", "MedicalClinic", "Physician", "Organization", "ProfessionalService",
                                                                        "AccountingService", "HomeAndConstructionBusiness") for t in types)
    if not has_lb:
        out.append({"kind": "website", "title": "Tell assistants who you are: add business details to your website",
                    "detail": "Assistants and Google read structured data. Paste this into your home page's <head> (your web person can do it in minutes).",
                    "code": local_business_jsonld(setup)})
    missed = [q["question"] for q in sc.get("questions") or per_question(answers) if q["named"] == 0]
    if types is None or "FAQPage" not in types:
        out.append({"kind": "website", "title": "Answer the questions customers ask on your website",
                    "detail": "Add an FAQ page (with FAQ structured data) answering these, in your own words and with your area named.",
                    "questions": missed[:6] or setup["questions"][:6]})
    out.append({"kind": "website", "title": "Add an llms.txt file", "detail": "A short plain-text summary at yoursite/llms.txt that AI tools can read.",
                "code": llms_txt(setup, services)})
    own = ai_search.domain_root(setup.get("website"))
    sites = [s for s in sc["sources"] if ai_search.domain_root(s["site"]) != own]
    listed = [s for s in sites if any(d in s["site"] for d in DIRECTORIES)][:3] or sites[:3]
    if listed:
        out.append({"kind": "listings", "title": "Be listed where the assistants look",
                    "detail": "The assistants quoted these sites most. Make sure you are listed on each with the same name, address and phone as your website.",
                    "sites": listed})
    praised = [n["name"] for a in answers for n in a["named"] if n["who"] != "me" and re.search(r"review|rated|rating|stars?", n.get("said") or "", re.IGNORECASE)]
    if praised:
        out.append({"kind": "reviews", "title": "Get more reviews",
                    "detail": f"Others were recommended for their reviews ({', '.join(sorted(set(praised))[:3])}). Ask happy customers for a Google review."})
    if missed:
        has_seo = (await conn.execute(text("select count(*) from app.automation_instances where template_key = 'local_seo'"))).scalar_one() > 0
        out.append({"kind": "content", "title": f"You weren't named for {len(missed)} question(s)",
                    "detail": "A page on your website answering each one helps assistants find you for it." +
                              (" Local SEO can draft each page for you to approve." if has_seo else ""),
                    "questions": missed[:8], "can_write": has_seo})
    return out


# ---------- running it ----------

@on("ai_visibility.check")
@DBOS.workflow()
async def on_check(event: dict) -> None:
    await ai_vis_check_step(event["org_id"], event["payload"]["run_id"])


@DBOS.step()
async def ai_vis_check_step(org_id: str, run_id: str) -> str:
    return (await run_check(org_id, run_id))["status"]


async def monthly_jobs() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'ai_visibility'
            and status in ('live','approval_mode') and coalesce((config->>'monthly')::boolean, true)"""))).scalars())
    n = 0
    for o in orgs:
        try:
            await start_check(o, trigger="monthly")
            n += 1
        except ValueError:
            continue
    return n


@DBOS.step()
async def ai_vis_monthly_step() -> int:
    return await monthly_jobs()


@DBOS.workflow()
async def ai_visibility_monthly(scheduled_time: datetime, context) -> None:
    await ai_vis_monthly_step()
