"""The free website audit anyone can run on the website (apps/web /audit): "Is your business losing customers?"

    request   website + city + service (+ Cloudflare Turnstile token when AGENTRY_TURNSTILE_SECRET is set); limits:
              3 audits per visitor per day, the same website at most once a day (the earlier report is shown), and a
              daily budget across all visitors (audit_daily_budget_usd): over it, the audit waits and runs when there's
              room (an hourly job), and the visitor is told so
    run       up to 6 pages of the site (the Local SEO crawler, public addresses only) and a few customer questions to
              the AI assistants (ai_search.py, once each), then three parts and a score out of 100:
                assistants  40 points: how often ChatGPT / Gemini named the business; who they named instead
                reach       30 points: chat on the site, WhatsApp link, online booking, a phone number
                website     30 points: the Local SEO checks
    report    the score, the parts and the biggest problems show at once; the full report (every answer, every fix)
              opens after name + email, which also become a demo request in Agentry HQ (team alert, the prospect's
              email with the link, a lead in Agentry's own account)
"""
import asyncio
import hashlib
import json
import re
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from agentry import ai_search
from agentry.config import settings
from agentry.db import system_session

PER_VISITOR_PER_DAY = 3
EST_COST_USD = 0.15  # held against the daily budget while an audit runs


class AuditRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def ip_hash(ip: str | None) -> str:
    return hashlib.blake2b(f"{settings.widget_secret}|{ip or '?'}".encode(), digest_size=12).hexdigest()  # never the IP itself


def normalise(url: str) -> tuple[str, str]:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if not host or "." not in host:
        raise AuditRefused(422, "that doesn't look like a website address")
    return f"{urlparse(url).scheme}://{host}", host.removeprefix("www.")


async def verify_turnstile(token: str | None, ip: str | None) -> bool:
    if not settings.turnstile_secret:
        return True  # captcha not configured (local, tests): limits still apply
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                             data={"secret": settings.turnstile_secret, "response": token, **({"remoteip": ip} if ip else {})})
        return bool(r.json().get("success"))
    except (httpx.HTTPError, ValueError):
        return False


async def hit(conn, key: str, limit: int, window: str) -> bool:
    """Postgres-backed limit shared by every API process. True = allowed (and counted)."""
    n = (await conn.execute(text(f"select count(*) from app.public_hits where key = :k and at > now() - interval '{window}'"), {"k": key})).scalar_one()
    if n >= limit:
        return False
    await conn.execute(text("insert into app.public_hits (key) values (:k)"), {"k": key})
    if n == 0:  # tidy old rows now and then
        await conn.execute(text("delete from app.public_hits where at < now() - interval '2 days'"))
    return True


async def spent_today(conn) -> float:
    """Spend over the last 24 hours: finished audits' real cost, an estimate for the ones running or about to, instant demo chats
    and the agent pages' try-it boxes."""
    row = (await conn.execute(text("""select coalesce(sum(cost_usd) filter (where status = 'done' and finished_at > now() - interval '24 hours'), 0)
        + :est * count(*) filter (where status in ('queued','running') and error is distinct from 'waiting for budget')
        from app.site_audits where created_at > now() - interval '3 days'"""), {"est": EST_COST_USD})).scalar_one()
    chats = (await conn.execute(text("select coalesce(sum(cost_usd), 0) from app.instant_demos where created_at > now() - interval '24 hours'"))).scalar_one()
    tries = (await conn.execute(text("select coalesce(sum(cost_usd), 0) from app.public_tries where created_at > now() - interval '24 hours'"))).scalar_one()
    return float(row) + float(chats) + float(tries)


async def request(url: str, city: str, service: str, *, ip: str | None, source: str | None = None) -> dict:
    from agentry.knowledge import UnsafeUrl, _check_public
    base, domain = normalise(url)
    try:
        _check_public(base)
    except UnsafeUrl as e:
        raise AuditRefused(422, "that isn't a public website") from e
    city, service = city.strip()[:80], service.strip()[:80]
    async with system_session() as conn:
        cached = (await conn.execute(text("""select id::text, status from app.site_audits where domain = :d and lower(city) = lower(:c)
            and lower(service) = lower(:s) and status in ('queued','running','done') and created_at > now() - interval '24 hours'
            order by created_at desc limit 1"""), {"d": domain, "c": city, "s": service})).first()
        if cached:
            return {"id": cached.id, "status": cached.status, "cached": True}
        if not await hit(conn, f"audit:{ip_hash(ip)}", PER_VISITOR_PER_DAY, "24 hours"):
            raise AuditRefused(429, f"{PER_VISITOR_PER_DAY} free audits a day per visitor: try again tomorrow, or ask us for a demo")
        waiting = await spent_today(conn) + EST_COST_USD > settings.audit_daily_budget_usd
        aid = str((await conn.execute(text("""insert into app.site_audits (url, domain, city, service, ip_hash, source, error)
            values (:u, :d, :c, :s, :ip, :src, :e) returning id"""), {"u": base, "d": domain, "c": city, "s": service, "ip": ip_hash(ip),
            "src": (source or "")[:300] or None, "e": "waiting for budget" if waiting else None})).scalar_one())
        if not waiting:
            from agentry.events import emit
            await emit(conn, None, "site_audit.requested", {"audit_id": aid})
    return {"id": aid, "status": "queued", "cached": False, "busy": waiting}


def reach_of(pages: list[dict]) -> dict:
    return {"chat": any(p.get("chat") for p in pages), "whatsapp": any(p.get("whatsapp") for p in pages),
            "booking": any(p.get("booking") for p in pages), "phone": any(p.get("phones") for p in pages)}


GENERIC_TITLE = re.compile(r"^(home|welcome|index)$|\b(best|top|near you|near me|no\.? ?1|#1|leading|affordable)\b", re.IGNORECASE)


def name_of(pages: list[dict], domain: str) -> str:
    """The business name: the site's own og:site_name, else the title when it's a name (not "Best dentists near you"),
    else the domain."""
    for p in pages[:1]:
        for cand in (p.get("site_name") or "", re.split(r"\s+[|\-–—:]\s+", (p.get("title") or "").strip())[0].strip()):
            cand = cand.strip()
            if 2 <= len(cand) <= 60 and not GENERIC_TITLE.search(cand):
                return cand
        for part in re.split(r"\s+[|\-–—:]\s+", (p.get("title") or "").strip())[1:]:  # "Best dentists | Clove Dental"
            if 2 <= len(part.strip()) <= 40 and not GENERIC_TITLE.search(part):
                return part.strip()
    return domain.split(".")[0].replace("-", " ").title()


def problems(ai: dict, reach: dict, issues: list[dict], name: str) -> list[dict]:
    out = []
    if ai.get("asked") and ai["rate"] < 50:
        others = ", ".join(n["name"] for n in ai["named_instead"][:3])
        out.append({"severity": "high", "title": f"AI assistants named you in {ai['named']} of {ai['asked']} answers",
                    "detail": f"When people asked for a recommendation, they were told about {others or 'other businesses'} instead."})
    if not reach["chat"] and not reach["whatsapp"]:
        out.append({"severity": "high", "title": "Visitors can't ask you anything outside office hours",
                    "detail": "No chat and no WhatsApp link on your website: an evening visitor with a question leaves."})
    elif not reach["chat"]:
        out.append({"severity": "medium", "title": "No instant answers on your website",
                    "detail": "There's a WhatsApp link, but nobody answers it at night. A chat assistant replies in seconds, any time."})
    if not reach["booking"]:
        out.append({"severity": "medium", "title": "No way to book online", "detail": "Visitors who are ready to book have to call during office hours."})
    for i in [i for i in issues if i["severity"] == "high"][:2]:
        out.append({"severity": "medium", "title": i["issue"], "detail": i["fix"]})
    return out[:5]


async def run(audit_id: str) -> dict:
    from agentry.automations import local_seo
    async with system_session() as conn:
        a = (await conn.execute(text("select * from app.site_audits where id = cast(:i as uuid)"), {"i": audit_id})).mappings().first()
        if not a or a["status"] not in ("queued", "running"):
            return {"status": a["status"] if a else "missing"}
        await conn.execute(text("update app.site_audits set status = 'running', error = null where id = cast(:i as uuid)"), {"i": audit_id})
    try:
        pages, site = await local_seo.crawl(a["url"], 6)
    except Exception:  # noqa: BLE001 - an unreachable site still gets the assistants' part
        pages, site = [], {"https": a["url"].startswith("https://"), "broken": [], "robots.txt": False, "sitemap.xml": False}
    issues = local_seo.issues(pages, site, None) if pages else []
    name = name_of(pages, a["domain"])
    me = {"name": name, "aliases": [], "website": a["url"]}
    engines, _mock = ai_search.active()
    questions = ai_search.questions_for(a["service"], a["city"], n=max(1, settings.audit_questions))
    sem = asyncio.Semaphore(4)

    async def one(engine: str, model: str, q: str) -> dict:
        async with sem:
            ans = await ai_search.ask(engine, model, q, city=a["city"], prompt_key="audit_search", mock_names=[name])
            named = ai_search.mark(await ai_search.extract(ans, prompt_key="audit_extract"), me, []) if not ans.error else []
        return {"engine": engine, "question": q, "answer": ans.text[:4000], "citations": ans.citations[:10], "named": named,
                "error": ans.error, "cost": ans.cost_usd}

    answers = await asyncio.gather(*[one(e, m, q) for q in questions for e, m in engines.items()])
    ai = ai_search.score(answers, [])
    reach = reach_of(pages)
    web_score = max(0, 100 - sum(local_seo.WEIGHT[i["severity"]] for i in issues)) if pages else 0
    ai_pts = round(40 * ai["rate"] / 100) if ai["asked"] else 0
    reach_pts = 12 * reach["chat"] + 8 * reach["whatsapp"] + 5 * reach["booking"] + 5 * reach["phone"]
    total = ai_pts + reach_pts + round(web_score * 0.3)
    result = {
        "name": name, "domain": a["domain"], "city": a["city"], "service": a["service"], "site_read": bool(pages),
        "parts": {"assistants": {"points": ai_pts, "of": 40, **{k: ai[k] for k in ("asked", "named", "rate", "engines", "named_instead", "sources")}},
                  "reach": {"points": reach_pts, "of": 30, **reach},
                  "website": {"points": round(web_score * 0.3), "of": 30, "score": web_score, "issues": issues}},
        "problems": problems(ai, reach, issues, name),
        "answers": [{k: x[k] for k in ("engine", "question", "answer", "named", "citations", "error")} for x in answers],
        "engines": [ai_search.LABEL.get(e, e) for e in engines if any(x["engine"] == e and not x["error"] for x in answers)],
    }
    cost = round(sum(x["cost"] for x in answers), 4)
    async with system_session() as conn:
        await conn.execute(text("""update app.site_audits set status = 'done', score = :s, result = cast(:r as jsonb), cost_usd = :c,
            finished_at = now() where id = cast(:i as uuid)"""), {"s": total, "r": json.dumps(result), "c": cost, "i": audit_id})
    return {"status": "done", "score": total, **result}


PUBLIC_KEYS = ("name", "domain", "city", "service", "site_read", "problems", "engines")


async def get(audit_id: str) -> dict | None:
    """What the audit page shows: everything once the visitor has left their details, the summary before."""
    async with system_session() as conn:
        a = (await conn.execute(text("""select id::text, url, domain, city, service, status, score, result, email is not null as unlocked,
            created_at, error from app.site_audits where id = cast(:i as uuid) and created_at > now() - interval '30 days'"""), {"i": audit_id})).mappings().first()
        if not a:
            return None
        ahead = 0
        if a["status"] == "queued":
            ahead = (await conn.execute(text("select count(*) from app.site_audits where status = 'queued' and created_at < :t"), {"t": a["created_at"]})).scalar_one()
    out = {"id": a["id"], "url": a["url"], "domain": a["domain"], "city": a["city"], "service": a["service"], "status": a["status"],
           "score": a["score"], "unlocked": a["unlocked"], "waiting": a["error"] == "waiting for budget", "ahead": ahead}
    r = a["result"] or {}
    if a["status"] == "done":
        parts = r.get("parts") or {}
        out |= {k: r.get(k) for k in PUBLIC_KEYS}
        out["parts"] = {
            "assistants": {k: parts.get("assistants", {}).get(k) for k in ("points", "of", "asked", "named", "rate")} |
                          {"named_instead": (parts.get("assistants", {}).get("named_instead") or [])[:3]},
            "reach": parts.get("reach"),
            "website": {k: parts.get("website", {}).get(k) for k in ("points", "of", "score")} | {"issues": len(parts.get("website", {}).get("issues") or [])},
        }
        if a["unlocked"]:
            out["parts"] = parts
            out["answers"] = r.get("answers")
    return out


async def unlock(audit_id: str, *, name: str, email: str, phone: str | None) -> dict:
    """Name + email -> the full report, and a demo request in Agentry HQ (team alert, email with the link, lead)."""
    async with system_session() as conn:
        a = (await conn.execute(text("select * from app.site_audits where id = cast(:i as uuid)"), {"i": audit_id})).mappings().first()
        if not a or a["status"] != "done":
            raise AuditRefused(409, "the audit isn't finished yet")
        if a["demo_request_id"]:
            await conn.execute(text("update app.site_audits set name = :n, email = :e, phone = coalesce(:p, phone) where id = cast(:i as uuid)"),
                               {"n": name, "e": email, "p": phone, "i": audit_id})
            return {"ok": True}
        r = a["result"] or {}
        link = f"{settings.web_url.rstrip('/')}/audit/r/{audit_id}"
        msg = (f"Free website audit: {a['score']}/100 for {a['service']} in {a['city']}. "
               f"AI assistants named them in {r['parts']['assistants']['named']} of {r['parts']['assistants']['asked']} answers. "
               f"Top problems: " + "; ".join(p["title"] for p in r.get("problems") or []) + f". Report: {link}" +
               (f" [source: {a['source']}]" if a["source"] else ""))
        did = str((await conn.execute(text("""insert into app.demo_requests (name, email, phone, company, website, niche, message)
            values (:n, :e, :p, :c, :w, :niche, :m) returning id"""), {"n": name, "e": email, "p": phone, "c": r.get("name"), "w": a["url"],
            "niche": niche_of(a["service"]), "m": msg[:2000]})).scalar_one())
        await conn.execute(text("update app.site_audits set name = :n, email = :e, phone = :p, demo_request_id = cast(:d as uuid) where id = cast(:i as uuid)"),
                           {"n": name, "e": email, "p": phone, "d": did, "i": audit_id})
        from agentry.events import emit
        await emit(conn, None, "site_audit.unlocked", {"audit_id": audit_id, "demo_request_id": did})
    return {"ok": True, "demo_request_id": did}


def niche_of(service: str) -> str:
    s = service.lower()
    if re.search(r"dent|clinic|doctor|physio|salon|spa|derma|hospital|diagnos|vet|gym|coach|tutor", s):
        return "clinic_or_appointments"
    if re.search(r"repair|plumb|electric|ac |a/c|clean|pest|paint|carpent|install|service", s):
        return "home_services"
    if re.search(r"\bca\b|chartered|account|law|legal|agency|consult|architect|firm", s):
        return "agency_or_firm"
    return "other"


def report_email(name: str, a: dict) -> tuple[str, str]:
    r = a["result"] or {}
    link = f"{settings.web_url.rstrip('/')}/audit/r/{a['id']}"
    probs = "\n".join(f"- {p['title']}" for p in r.get("problems") or []) or "- Nothing big: nice work."
    body = (f"Hi {name.split()[0] if name else 'there'},\n\n"
            f"Here is the full audit of {a['domain']} ({a['service']} in {a['city']}): {a['score']}/100.\n\n"
            f"The biggest problems:\n{probs}\n\n"
            f"Every AI answer, every website fix and what to do first: {link}\n"
            f"(The link works for 30 days.)\n\n"
            f"If you'd like, we'll set up an AI assistant trained on your own website so you can see it answer your customers. "
            f"Just reply to this email.\n\n{settings.sales_signature}")
    return f"Your website audit: {a['score']}/100 for {r.get('name') or a['domain']}", body


async def release_waiting() -> int:
    """Hourly: start audits that waited for the daily budget, oldest first, while there's room."""
    started = 0
    async with system_session() as conn:
        rows = (await conn.execute(text("""select id::text from app.site_audits where status = 'queued' and error = 'waiting for budget'
            order by created_at limit 50"""))).scalars().all()
        from agentry.events import emit
        for aid in rows:
            if await spent_today(conn) + EST_COST_USD > settings.audit_daily_budget_usd:
                break
            await conn.execute(text("update app.site_audits set error = null where id = cast(:i as uuid)"), {"i": aid})
            await emit(conn, None, "site_audit.requested", {"audit_id": aid})
            started += 1
    return started
