"""Local SEO (ROADMAP-V3 B1, v2 10.2): a website audit with a prioritised fix list, and articles for nearby searches.

    audit     up to 12 pages of the business's site (the same SSRF-safe fetch as the knowledge crawler): titles, meta
              descriptions, H1s, image alt text, thin pages, duplicate titles, mobile viewport, canonical, LocalBusiness
              structured data, phone number on the site, a Google Maps link, click-to-WhatsApp, HTTPS, robots.txt,
              sitemap.xml, slow or heavy pages, broken internal links -> a score and fixes ordered by impact
    articles  a topic + the city -> a 600-900 word article with FAQs, written only from the business's own facts
              (knowledge base and services); specific numbers, prices and claims not in those facts are flagged and
              rewritten once; FAQ structured data is included in the HTML export
    monthly   on the 1st: a fresh audit and N article drafts (settings) with a Needs-you card
Ranking checks need a search API key and aren't included yet.
"""
import json
import re
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from dbos import DBOS
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.db import system_session, tenant_session
from agentry.knowledge import UnsafeUrl, _check_public, _get_checked
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


class SeoConfig(BaseModel):
    city: str | None = Field(None, title="City or area to rank in", json_schema_extra={"editable_by": "client"})
    topics: list[str] = Field(default_factory=list, title="Article topics", description="e.g. 'AC service cost in Pune', 'When to change a water filter'",
                              json_schema_extra={"editable_by": "client"})
    articles_per_month: int = Field(2, ge=0, le=8, title="Article drafts a month", json_schema_extra={"editable_by": "client"})
    monthly_audit: bool = Field(True, title="Audit the website on the 1st of each month", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="local_seo", name="Local SEO",
    description="Audits your website for local search with a prioritised fix list, and writes articles for people nearby, from your own facts.",
    config_model=SeoConfig, metrics=(),
))

WEIGHT = {"high": 12, "medium": 6, "low": 2}
# a chat widget on the page (live chat or chatbot), and links to book online
CHAT_WIDGET = re.compile(r"tawk\.to|intercom|crisp\.chat|salesiq|zohopublic|freshchat|tidio|drift\.com|hs-scripts|livechatinc|"
                         r"wati\.io|interakt|aisensy|gallabox|chatwoot|botpress|landbot|manychat|/widget/v1|agentry-widget|elfsight", re.IGNORECASE)
BOOKING = re.compile(r"calendly\.com|book(ing)?|appointment|schedule|practo\.com|setmore|zcal|cal\.com", re.IGNORECASE)


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'local_seo'"))).first()
    return (row.status, SeoConfig(**(row.config or {})).model_dump()) if row else (None, SeoConfig().model_dump())


def page_facts(html: str, url: str, ms: int) -> dict:
    t = HTMLParser(html)
    meta = {(m.attributes.get("name") or m.attributes.get("property") or "").lower(): m.attributes.get("content") or "" for m in t.css("meta")}
    title = t.css_first("title").text(strip=True) if t.css_first("title") else ""
    jsonld = []
    for s in t.css('script[type="application/ld+json"]'):
        try:
            d = json.loads(s.text() or "{}")
            for x in d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []:
                if isinstance(x, dict) and x.get("@type"):
                    jsonld += x["@type"] if isinstance(x["@type"], list) else [x["@type"]]
        except ValueError:
            continue
    links = [a.attributes.get("href") or "" for a in t.css("a[href]")]
    host = urlparse(url).hostname
    scripts = " ".join((s.attributes.get("src") or "") + " " + (s.text() or "")[:2000] for s in t.css("script")).lower()
    for n in t.css("script,style,noscript"):
        n.decompose()
    body = re.sub(r"\s+", " ", t.body.text(separator=" ") if t.body else "")
    return {"url": url, "ms": ms, "bytes": len(html), "title": title, "description": meta.get("description", ""), "site_name": meta.get("og:site_name", ""),
            "h1": [h.text(strip=True) for h in t.css("h1")], "images": len(t.css("img")), "no_alt": sum(1 for i in t.css("img") if not (i.attributes.get("alt") or "").strip()),
            "words": len(body.split()), "viewport": "viewport" in meta, "canonical": bool(t.css_first('link[rel="canonical"]')), "jsonld": jsonld,
            "phones": sorted({re.sub(r"\D", "", p)[-10:] for p in re.findall(r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}", body + " " + " ".join(links))}),
            "maps": any(re.search(r"google\.[a-z.]+/maps|maps\.app\.goo\.gl|g\.page/", h) for h in links),
            "whatsapp": any(re.search(r"wa\.me/|api\.whatsapp\.com|whatsapp://", h) for h in links),
            "chat": bool(CHAT_WIDGET.search(scripts)),
            "booking": any(BOOKING.search(h) for h in links),
            "internal": sorted({urljoin(url, h).split("#")[0] for h in links if urlparse(urljoin(url, h)).hostname == host})[:80]}


async def crawl(start: str, max_pages: int = 12) -> tuple[list[dict], dict]:
    if not re.match(r"^https?://", start, re.IGNORECASE):
        start = "https://" + start
    _check_public(start)
    root = f"{urlparse(start).scheme}://{urlparse(start).hostname}"
    pages, seen, queue, broken = [], set(), [start], []
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={"User-Agent": "AgentryBot/0.1 (+site audit)"}) as c:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            t0 = time.perf_counter()
            try:
                r = await _get_checked(c, url)
            except (httpx.HTTPError, UnsafeUrl):
                broken.append(url)
                continue
            if r.status_code >= 400:
                broken.append(url)
                continue
            if "text/html" not in r.headers.get("content-type", ""):
                continue
            p = page_facts(r.text[:3_000_000], str(r.url), int((time.perf_counter() - t0) * 1000))
            pages.append(p)
            queue += [u for u in p["internal"] if u not in seen and not re.search(r"\.(pdf|jpe?g|png|webp|gif|zip|mp4)$", u, re.IGNORECASE)][:40]
        site = {"https": start.lower().startswith("https://") and (not pages or pages[0]["url"].startswith("https://")), "broken": broken[:20]}
        for name in ("robots.txt", "sitemap.xml"):
            try:
                r = await _get_checked(c, f"{root}/{name}")
                site[name] = r.status_code == 200
            except (httpx.HTTPError, UnsafeUrl):
                site[name] = False
    return pages, site


def issues(pages: list[dict], site: dict, phone: str | None) -> list[dict]:
    out: list[dict] = []

    def add(sev: str, what: str, fix: str, affected: list[str] | None = None) -> None:
        out.append({"severity": sev, "issue": what, "fix": fix, "pages": (affected or [])[:10]})
    if not pages:
        add("high", "The website couldn't be read", "Check the address, and that the site loads without a login")
        return out
    if not site.get("https"):
        add("high", "The site isn't on HTTPS", "Turn on HTTPS (free with most hosts); browsers warn visitors and Google ranks it lower")
    if p := [x["url"] for x in pages if not x["title"]]:
        add("high", "Pages without a title", "Give every page a title of 50-60 characters with the service and the city", p)
    if p := [x["url"] for x in pages if x["title"] and not 25 <= len(x["title"]) <= 65]:
        add("medium", "Titles too short or too long", "Keep titles 30-60 characters: service + city + business name", p)
    dup = [t for t, n in Counter(x["title"] for x in pages if x["title"]).items() if n > 1]
    if dup:
        add("medium", f"{len(dup)} title(s) used on more than one page", "Each page needs its own title", [x["url"] for x in pages if x["title"] in dup])
    if p := [x["url"] for x in pages if not x["description"]]:
        add("medium", "Pages without a meta description", "Write a 140-155 character summary per page; it's the text under the link in Google", p)
    if p := [x["url"] for x in pages if len(x["h1"]) != 1]:
        add("medium", "Pages without exactly one H1 heading", "One main heading per page that says what the page is about", p)
    if not pages[0]["viewport"]:
        add("high", "No mobile viewport", "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">: most visitors are on phones")
    if not any(t in ("LocalBusiness", "Organization", "Dentist", "MedicalBusiness", "Store", "Restaurant", "ProfessionalService", "HomeAndConstructionBusiness")
               or t.endswith("Business") for x in pages for t in x["jsonld"]):
        add("high", "No LocalBusiness structured data", "Add LocalBusiness JSON-LD (name, address, phone, hours, map link) to the home page")
    phones = {ph for x in pages for ph in x["phones"]}
    want = re.sub(r"\D", "", phone or "")[-10:]
    if not phones:
        add("high", "No phone number on the site", "Show the phone number on every page (header or footer), as a tap-to-call link")
    elif want and want not in phones:
        add("medium", "The phone on the site differs from the one in your profile", "Use one number everywhere (site, Google profile, directories)")
    if not any(x["maps"] for x in pages):
        add("medium", "No Google Maps link", "Link your Google Business Profile / Maps location from the contact page")
    if not any(x["whatsapp"] for x in pages):
        add("low", "No click-to-WhatsApp link", "Add a wa.me link: in India many customers prefer WhatsApp to a form")
    if p := [x["url"] for x in pages if x["no_alt"]]:
        add("low", f"{sum(x['no_alt'] for x in pages)} images without alt text", "Describe each image in a few words (helps Google Images and screen readers)", p)
    if p := [x["url"] for x in pages[1:] if x["words"] < 250]:
        add("medium", "Thin pages (under 250 words)", "Service pages need 300+ words: what it is, who it's for, price range, area served, FAQs", p)
    if p := [x["url"] for x in pages if x["ms"] > 2500 or x["bytes"] > 1_500_000]:
        add("medium", "Slow or heavy pages", "Compress images, remove unused scripts; aim for under 2.5 s", p)
    if not site.get("sitemap.xml"):
        add("medium", "No sitemap.xml", "Most site builders create one: turn it on and submit it in Google Search Console")
    if not site.get("robots.txt"):
        add("low", "No robots.txt", "Add one that points to the sitemap")
    if site.get("broken"):
        add("high", f"{len(site['broken'])} broken link(s)", "Fix or remove links that return errors", site["broken"])
    if p := [x["url"] for x in pages if not x["canonical"]]:
        add("low", "Pages without a canonical link", "Add <link rel=\"canonical\"> to avoid duplicate-content confusion", p)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda i: order[i["severity"]])


async def run_audit(org_id: str, url: str | None = None) -> dict:
    async with tenant_session(org_id) as conn:
        s = (await conn.execute(text("select website, profile from app.org_settings"))).mappings().first() or {}
        phone = (s.get("profile") or {}).get("phone")
    url = url or s.get("website")
    if not url:
        raise ValueError("add the website address in the business profile first")
    try:
        pages, site = await crawl(url)
    except UnsafeUrl as e:
        raise ValueError("that isn't a public web address") from e
    found = issues(pages, site, phone)
    score = max(0, 100 - sum(WEIGHT[i["severity"]] for i in found))
    result = {"pages": [{k: p[k] for k in ("url", "title", "description", "h1", "words", "ms", "no_alt", "jsonld")} for p in pages], "site": site, "issues": found}
    async with tenant_session(org_id) as conn:
        aid = str((await conn.execute(text("insert into app.seo_audits (org_id, url, score, result) values (:o, :u, :s, cast(:r as jsonb)) returning id"),
                                      {"o": org_id, "u": url, "s": score, "r": json.dumps(result)})).scalar_one())
    return {"id": aid, "url": url, "score": score, **result}


# ---------- articles ----------

NUMBER = re.compile(r"(₹|rs\.?|inr)\s?[\d,]+|\b\d+(\.\d+)?\s?%|\b\d{2,}\s?(years|yrs|customers|clients|patients|homes|reviews)\b", re.IGNORECASE)
RISKY = re.compile(r"\b(guarantee[sd]?|100\s?%|best in|#1|no\.? ?1|cheapest|lowest price|cure[sd]?|risk[- ]free)\b", re.IGNORECASE)


def article_problems(a: dict, facts: str) -> list[str]:
    out = []
    if not a.get("title") or not a.get("body") or len((a.get("body") or "").split()) < 300:
        out.append("the article is missing or too short")
    words = f"{a.get('title', '')} {a.get('body', '')} " + " ".join(f"{f.get('q', '')} {f.get('a', '')}" for f in a.get("faqs") or [] if isinstance(f, dict))
    if m := RISKY.search(words):
        out.append(f"risky wording: \"{m.group(0)}\"")
    low = facts.lower()
    for m in NUMBER.finditer(words):
        digits = re.sub(r"[^\d.]", "", m.group(0))
        if digits and digits not in re.sub(r"[,\s]", "", low):
            out.append(f"\"{m.group(0)}\" isn't in the business's facts")
            break
    return out


async def write_article(org_id: str, topic: str) -> dict:
    from agentry.knowledge import search
    async with tenant_session(org_id) as conn:
        _st, cfg = await settings_of(conn)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        services = ", ".join((await conn.execute(text("select name from app.services where active order by name limit 20"))).scalars()) or "(not listed)"
    try:
        hits = await search(org_id, topic, k=6)
    except Exception:  # noqa: BLE001 - knowledge search is a nice-to-have here
        hits = []
    facts = "\n".join(f"- {h.title}: {h.content[:400]}" for h in hits) or "(no facts in the knowledge base: keep it general)"
    city = cfg["city"] or "your area"
    mock = {"title": f"{topic} in {city}"[:60], "meta_description": f"A practical guide to {topic.lower()} in {city}, from {business}."[:155],
            "slug": re.sub(r"[^a-z0-9]+", "-", f"{topic} {city}".lower()).strip("-")[:60],
            "body": f"# {topic} in {city}\n\n" + ("This guide explains what to know, what to ask and how to choose well. " * 40) +
                    f"\n\n## Talk to {business}\n\nMessage us to ask anything.",
            "faqs": [{"q": f"How do I start with {topic.lower()}?", "a": "Start by noting what you need and when; then ask for a visit or a call."},
                     {"q": "How long does it take?", "a": "It depends on the job; we'll tell you before we start."},
                     {"q": "Do you cover my area?", "a": f"We work across {city}. Message us with your area to check."}]}
    prompt = load("seo_article")
    a, probs, feedback = {}, [], ""
    for _ in range(2):
        try:
            r = await complete(prompt.tier, prompt.render(business=business, city=city, services=services, topic=topic, facts=facts, feedback=feedback),
                               org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True, mock_response=json.dumps(mock), temperature=0.5)
            a = r.data if isinstance(r.data, dict) else {}
        except AllModelsFailed as e:
            raise ValueError("the writing models are busy: try again in a few minutes") from e
        probs = article_problems(a, facts)
        if not probs:
            break
        feedback = "Your previous draft had these problems; fix them:\n- " + "\n- ".join(probs)
    slug = re.sub(r"[^a-z0-9-]+", "-", (a.get("slug") or a.get("title") or topic).lower()).strip("-")[:80] or "article"
    async with tenant_session(org_id) as conn:
        aid = str((await conn.execute(text("""insert into app.seo_articles (org_id, topic, city, title, meta, slug, body, faqs, checks, status)
            values (:o, :t, :c, :ti, :m, :s, :b, cast(:f as jsonb), cast(:ch as jsonb), :st) returning id"""),
            {"o": org_id, "t": topic, "c": cfg["city"], "ti": (a.get("title") or topic)[:120], "m": (a.get("meta_description") or "")[:200], "s": slug,
             "b": a.get("body") or "", "f": json.dumps([f for f in a.get("faqs") or [] if isinstance(f, dict)][:6]), "ch": json.dumps(probs),
             "st": "needs_attention" if probs else "draft"})).scalar_one())
    return {"id": aid, "status": "needs_attention" if probs else "draft", "problems": probs}


def article_html(a: dict, business: str) -> str:
    from html import escape
    body = []
    for block in re.split(r"\n{2,}", a["body"].strip()):
        b = block.strip()
        if b.startswith("### "):
            body.append(f"<h3>{escape(b[4:])}</h3>")
        elif b.startswith("## "):
            body.append(f"<h2>{escape(b[3:])}</h2>")
        elif b.startswith("# "):
            continue
        elif all(ln.strip().startswith(("- ", "* ")) for ln in b.splitlines()):
            body.append("<ul>" + "".join(f"<li>{escape(ln.strip()[2:])}</li>" for ln in b.splitlines()) + "</ul>")
        else:
            body.append(f"<p>{escape(b)}</p>")
    faqs = a["faqs"] or []
    faq_html = "".join(f"<h3>{escape(f['q'])}</h3><p>{escape(f['a'])}</p>" for f in faqs)
    ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]})
    return (f"<article><h1>{escape(a['title'])}</h1>{''.join(body)}" + (f"<h2>Frequently asked questions</h2>{faq_html}" if faqs else "") +
            f"</article>\n<script type=\"application/ld+json\">{ld}</script>\n<!-- meta description: {escape(a.get('meta') or '')} · {escape(business)} -->")


async def monthly(org_id: str) -> dict:
    out = {"audit": None, "articles": 0}
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        used = set((await conn.execute(text("select lower(topic) from app.seo_articles"))).scalars())
    if status not in ("live", "approval_mode"):
        return out
    if cfg["monthly_audit"]:
        try:
            out["audit"] = (await run_audit(org_id))["score"]
        except ValueError:
            pass
    for t in [t for t in cfg["topics"] if t.lower() not in used][:cfg["articles_per_month"]]:
        try:
            await write_article(org_id, t)
            out["articles"] += 1
        except ValueError:
            break
    if out["articles"] or out["audit"] is not None:
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body) values (:o, 'escalation', 'local_seo', :t, :b)"""),
                               {"o": org_id, "t": "This month's local SEO is ready",
                                "b": (f"Website score: {out['audit']}/100. " if out["audit"] is not None else "") + f"{out['articles']} article draft(s) to review."})
    return out


async def seo_jobs() -> int:
    async with system_session() as conn:
        orgs = list((await conn.execute(text("""select org_id from app.automation_instances where template_key = 'local_seo'
            and status in ('live','approval_mode')"""))).scalars())
    for o in orgs:
        await monthly(o)
    return len(orgs)


@DBOS.step()
async def seo_step() -> int:
    return await seo_jobs()


@DBOS.workflow()
async def seo_monthly(scheduled_time: datetime, context) -> None:
    await seo_step()
