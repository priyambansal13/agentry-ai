"""The try-it boxes on the website's agent pages (apps/web /agents/{slug}): each runs the agent's real engine on the
visitor's input (or a sample), with nothing saved and nothing sent.

    calc   the CA pack's calculations (bank statements excepted: the AI tags what the rules don't), the compliance calendar, the document checklist and renewal reminders: the same
           functions the portal uses, on a table or form the visitor edits. No AI, no cost: 120 runs an hour per visitor.
    live   the AI agents (lead research, cold email first line, inbox triage, SOPs, festival posts, content, video
           scripts, CV scoring, tax notices, bills, shelf photos, Excel questions, old-lead emails): the same prompts and
           checks as the portal. Human check (Turnstile), 8 tries a day per visitor, and the cost counts against the
           website's daily budget (site_audit.spent_today, shared with the free audit and the instant demo).
Inputs are capped (rows, characters, photo size); websites are read with the knowledge crawler (public addresses only).
"""
import asyncio
import base64
import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from agentry import site_audit
from agentry.config import settings
from agentry.db import system_session
from agentry.llm import gateway
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

IST = ZoneInfo("Asia/Kolkata")
CALC_PER_HOUR = 120
LIVE_PER_DAY = 8
MAX_ROWS, MAX_COLS, MAX_CELL = 60, 16, 200
MAX_TEXT = 6000
MAX_IMAGE = 4 * 1024 * 1024
EST_COST = 0.02  # held against the budget before a live try runs


class TryRefused(site_audit.AuditRefused):
    pass


# ---------- input helpers ----------

def _s(v: object, n: int = 200) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", str(v or "")).strip()[:n]


def _long(v: object, n: int = MAX_TEXT) -> str:
    return str(v or "").replace("\x00", "").strip()[:n]


def _rows(v: object) -> list[list[str]]:
    if not isinstance(v, list) or not v:
        raise TryRefused(422, "add at least one row")
    rows = [[_s(c, MAX_CELL) for c in r[:MAX_COLS]] for r in v[:MAX_ROWS + 1] if isinstance(r, list)]
    if len(rows) < 2:
        raise TryRefused(422, "add at least one row under the headings")
    return rows


def _csv(path) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))) if any(c.strip() for c in r)]


def _from_header(rows: list[list[str]], must: tuple[str, ...]) -> list[list[str]]:
    from agentry.automations.ca import core
    return rows[core.header_row(rows, must, within=30):]


def _image(v: object) -> tuple[bytes, str]:
    m = re.match(r"^data:(image/(?:jpeg|png|webp)|application/pdf);base64,(.+)$", str(v or ""), re.DOTALL)
    if not m:
        raise TryRefused(422, "add a photo (JPG, PNG or WEBP) or a PDF")
    try:
        data = base64.b64decode(m.group(2), validate=False)
    except ValueError as e:
        raise TryRefused(422, "that file couldn't be read") from e
    if len(data) > MAX_IMAGE:
        raise TryRefused(413, "files can be up to 4 MB here")
    return data, m.group(1)


def _flag(p: dict, *keys: str) -> dict:
    return {k: bool(p.get(k)) for k in keys}


def today() -> date:
    return datetime.now(IST).date()


def _jsonable(x: object) -> object:
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple | set):
        return [_jsonable(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


async def _ask(prompt_key: str, mock: dict, **vars: object) -> dict:
    prompt = load(prompt_key)
    try:
        r = await complete(prompt.tier, prompt.render(**vars), prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                           mock_response=json.dumps(mock), temperature=0.4)
    except AllModelsFailed as e:
        raise TryRefused(503, "the AI is busy: try again in a minute") from e
    return r.data if isinstance(r.data, dict) else mock


# ---------- CA pack: calculations (no AI) ----------

def _ca_samples():
    from agentry.automations.ca.taxdocs import SAMPLES
    return SAMPLES


ITR_SAMPLE = {"age": "below60", "salary_gross": 1840000, "exempt_allowances": 120000, "professional_tax": 2400, "self_occupied_interest": 0,
              "interest_savings": 6842, "interest_deposit": 52310, "dividend": 8400, "ltcg_112a": 0, "stcg_111a": 0, "d_80c": 150000,
              "d_80ccd1b": 0, "d_80d": 25000, "tds": 241500}


def itr(p: dict) -> dict:
    from agentry.automations.ca import itr as m
    clean = {k: max(0.0, min(float(p.get(k) or 0), 1e9)) for k in m.FIELDS if k in p}
    clean["age"] = p.get("age") if p.get("age") in m.OLD_EXEMPT else "below60"
    return m.prepare(clean)


def capital_gains(p: dict) -> dict:
    from agentry.automations.ca import capgains as m
    rows = [m.classify(t) for t in m.parse(_rows(p.get("rows")))]
    return _jsonable({"summary": m.summarise(rows), "rows": rows})


def tds(p: dict) -> dict:
    from agentry.automations.ca import tds as m
    return _jsonable(m.check(m.parse(_rows(p.get("rows")))))


def audit_3cd(p: dict) -> dict:
    from agentry.automations.ca import audit3cd as m
    fy = int(p.get("fy_start") or 2025)
    return _jsonable(m.test(m.parse(_rows(p.get("rows"))), fy if 2018 <= fy <= 2030 else 2025))


def gst(p: dict) -> dict:
    from agentry.automations.ca import gst as m
    b2b = m.from_2b_json(json.loads((_ca_samples() / "gstr2b_sample.json").read_text()))
    result = m.reconcile(b2b, m.from_table(_rows(p.get("rows"))))
    return _jsonable({**result, "gstr2b": b2b, "messages": m.supplier_messages(result, "Mehta Traders", "27AAPFM4321Q1Z5", "October 2026")})


async def bank(p: dict) -> dict:
    """Rules first (free), then the AI for the lines no rule covers: the portal's classifier, without the client's learned rules."""
    from agentry.automations.ca import bank as m
    lines = await m.classify(None, m.parse(_rows(p.get("rows"))), [], use_model=True)
    return _jsonable({"lines": lines, "totals": m.totals(lines), "categories": m.CATEGORIES})


KINDS = ("individual", "huf", "firm", "llp", "company")


async def calendar(p: dict) -> dict:
    from agentry.automations.ca import calendar as m
    from agentry.automations.ca import core
    kind = p.get("client_kind") if p.get("client_kind") in KINDS else "individual"
    prof = _flag(p.get("profile") or {}, *core.PROFILE_FLAGS)
    start = today()
    async with system_session() as conn:
        updates = await m.active_updates(conn)
    dues = m.deadlines(kind, prof, start, start + timedelta(days=120), gstin=_s(p.get("gstin"), 15) or None, updates=updates)
    firm, name = _s(p.get("firm"), 80) or "Sharma & Associates", _s(p.get("name"), 80) or "Ramesh Gupta"
    return _jsonable({"deadlines": [{**d, "days_left": (d["due_on"] - start).days, "kind_label": core.KINDS.get(d["kind"], d["kind"]),
                                     "reminder": m.reminder(d["title"], d["due_on"], d["kind"], firm, name)} for d in dues], "from": start})


def chaser(p: dict) -> dict:
    from agentry.automations.ca import chaser as m
    kind = p.get("kind") if p.get("kind") in ("itr", "gstr3b", "tds_26q", "tax_audit", "advance_tax", "dir3_kyc") else "itr"
    client_kind = p.get("client_kind") if p.get("client_kind") in KINDS else "individual"
    prof = _flag(p.get("profile") or {}, "salaried", "rent_paid", "house_property", "capital_gains", "deductions", "business", "foreign", "audit")
    items = m.checklist_for(kind, prof, client_kind)
    titles = {"itr": "ITR for AY 2026-27", "gstr3b": "GSTR-3B for October 2026", "tds_26q": "TDS return (26Q) Q3", "tax_audit": "tax audit FY 2025-26",
              "advance_tax": "advance tax (December instalment)", "dir3_kyc": "director KYC"}
    name, firm = _s(p.get("name"), 80) or "Ramesh Gupta", _s(p.get("firm"), 80) or "Sharma & Associates"
    received = {str(k) for k in p.get("received") or []}
    left = [i["label"] for i in items if i["key"] not in received]
    every = 3
    plan = [{"day": n * every, "text": m.reminder_text(name, titles[kind], left, firm, n)} for n in range(3)] if left else []
    return {"checklist": [{**i, "status": "received" if i["key"] in received else "missing"} for i in items], "missing": left, "reminders": plan,
            "after": "After 5 reminders the client goes on the team's call list.", "title": titles[kind]}


def tax_docs(p: dict) -> dict:
    from agentry.automations.ca import taxdocs as m
    samples = m._samples()
    docs = []
    for name in ("form16_sample.txt", "ais_sample.txt"):
        e = json.loads(json.dumps(samples[name]))
        src = (m.SAMPLES / name).read_text()
        if name == "form16_sample.txt" and p.get("form16_tds") is not None:  # the visitor's own figure: shown as typed into the document
            new = float(p["form16_tds"])
            for i in e["items"]:
                if i["category"] == "tds" or i.get("tds"):
                    old = i.get("tds") or i["amount"]
                    old_s, new_s = _inr_plain(old), _inr_plain(new)
                    i["quote"] = i["quote"].replace(old_s, new_s)
                    src = src.replace(old_s, new_s)
                    if i.get("tds"):
                        i["tds"] = new
                    else:
                        i["amount"] = new
        if name == "ais_sample.txt" and p.get("ais_interest") is not None:
            new = float(p["ais_interest"])
            for i in e["items"]:
                if i["category"] == "interest_deposit":
                    old_s, new_s = _inr_plain(i["amount"]), _inr_plain(new)
                    i["quote"], src = i["quote"].replace(old_s, new_s), src.replace(old_s, new_s)
                    i["amount"] = new
        e["items"] = m.trace(e["items"], src)
        docs.append({"file_id": name, "filename": "Form 16 (employer)" if name.startswith("form16") else "AIS (income-tax department)", "extracted": e})
    return {"points": m.compare(docs, "ABCPS1234K"), "documents": [{"file": d["filename"], "items": d["extracted"]["items"]} for d in docs],
            "summary": m.summary(docs)}


def _inr_plain(v: float) -> str:
    """12,34,567 (Indian grouping, no symbol): how the sample documents print amounts."""
    n = f"{round(float(v)):d}"
    if len(n) <= 3:
        return n
    head, tail = n[:-3], n[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *parts, tail]) if head else ",".join([*parts, tail])


def renewals(p: dict) -> dict:
    from agentry.automations import renewals as m
    every = p.get("every") if p.get("every") in m.STEP else "yearly"
    try:
        due = date.fromisoformat(str(p.get("due_on")))
    except ValueError:
        due = today() + timedelta(days=30)
    r = {"customer": _s(p.get("customer"), 80) or "Anita Desai", "item": _s(p.get("item"), 80) or "AC annual maintenance",
         "amount": max(0.0, float(p.get("amount") or 0)), "due_on": due}
    business, offer = _s(p.get("business"), 80) or "CoolAir Services", _s(p.get("offer"), 120)
    link = "https://rzp.io/l/your-link" if r["amount"] else None
    plan = [{"when": due - timedelta(days=d), "label": f"{d} day{'s' if d != 1 else ''} before", "text": m.reminder(r, d, business, link)} for d in (30, 7, 1)]
    lapse = due + timedelta(days=15)
    first = r["customer"].split()[0]
    winback = (f"Hi {first}, we noticed your {r['item']} with {business} lapsed on {due:%d %b}. We'd love to have you back."
               f"{(' ' + offer) if offer else ''} Reply here and we'll sort it out.")
    return _jsonable({"reminders": plan, "winback": {"when": lapse, "text": winback}, "next_due": m.next_due(due, every)})


CALC = {"itr": itr, "capital-gains": capital_gains, "tds": tds, "audit-3cd": audit_3cd, "gst": gst, "calendar": calendar,
        "chaser": chaser, "tax-docs": tax_docs, "renewals": renewals}


# ---------- the AI agents ----------

async def _site(url: str) -> tuple[str, list]:
    from agentry.automations.lead_research import fetch_pages
    from agentry.knowledge import UnsafeUrl, _check_public
    base, domain = site_audit.normalise(url)
    try:
        _check_public(base)
    except UnsafeUrl as e:
        raise TryRefused(422, "that isn't a public website") from e
    pages = await fetch_pages(domain)
    if not pages:
        raise TryRefused(422, "we couldn't read that website: check the address")
    return domain, pages


async def lead_research(p: dict) -> dict:
    from agentry.automations import lead_research as m
    from agentry.automations.cold_email.research import _pages_text
    domain, pages = await _site(_s(p.get("website")))
    said, offer = _long(p.get("message"), 600), _s(p.get("offer"), 160) or "our services"
    fallback = m.heuristic_note(pages, said)
    note = await _ask("lead_research", fallback, business="us", our_offer=offer, lead="a new enquiry", said=said or "(nothing yet)",
                      domain=domain, pages=_pages_text(pages) or "(none)")
    return {**m.ground(note, pages, said), "domain": domain, "sources": [pg.url for pg in pages]}


def _name_of(pages: list, domain: str) -> str:
    """The business name from the home page title ("Best dentists near you | Clove Dental" -> Clove Dental), else the domain."""
    for part in re.split(r"\s+[|\-–—:]\s+", (pages[0].title or "").strip()):
        if 2 <= len(part.strip()) <= 50 and not site_audit.GENERIC_TITLE.search(part):
            return part.strip()
    return domain.split(".")[0].replace("-", " ").title()


async def cold_email(p: dict) -> dict:
    from agentry.automations.cold_email import research as m
    domain, pages = await _site(_s(p.get("website")))
    business = _name_of(pages, domain)
    snips = m.snippets(pages)
    line = await m.write_line(None, business=business, first_name=_s(p.get("first_name"), 40) or None, role=None, snips=snips)
    offer = _s(p.get("offer"), 200) or "[what you do, in one line]"
    sender = _s(p.get("sender"), 60) or "[your name]"
    first = _s(p.get("first_name"), 40) or "there"
    email = None
    if line.get("line"):
        email = (f"Hi {first},\n\n{line['line']}\n\nI help businesses like yours with {offer[0].lower() + offer[1:].rstrip('.')}. "
                 "Would a 15-minute call next week be useful?\n\nThanks,\n" + sender + "\n\nIf this isn't relevant, reply 'no' and I won't write again.")
    return {"business": business, "domain": domain, "facts": snips, "line": line, "email": email}


async def inbox(p: dict) -> dict:
    from agentry.automations.inbox_triage import rules
    email = {"from": _s(p.get("from"), 120).lower() or "someone@example.com", "from_name": _s(p.get("from_name"), 120), "reply_to": _s(p.get("reply_to"), 120),
             "subject": _s(p.get("subject"), 200), "body": _long(p.get("body"), 4000)}
    if not email["body"]:
        raise TryRefused(422, "paste an email first")
    business = _s(p.get("business"), 80) or "Sharma Digital"
    risk = rules.fraud_signals(email, ["sharmadigital.in", "kaveritextiles.in"])
    heuristic = rules.heuristic_triage(email)
    if (d := rules.rule_decision(email)) is not None:
        triage = d
    else:
        triage = await _ask("inbox_triage_classifier", heuristic, business=business, known_contact="no", vip="no", custom_categories="", corrections="",
                            today=today().isoformat(), **{**email, "reply_to": email["reply_to"] or "(same as sender)"})
    if triage.get("suspicious") and triage.get("suspicious_reason"):
        risk.append(triage["suspicious_reason"])
    reply = None
    if triage.get("needs_reply") and triage.get("category") not in ("Spam", "Promotion", "Newsletter"):
        prompt = load("email_reply_drafter")
        try:
            r = await complete(prompt.tier, prompt.render(business=business, sender_name=f"The {business} team", tone="warm and professional",
                                                          category=triage.get("category"), knowledge=_long(p.get("facts"), 1500) or "(no facts given: don't invent any)",
                                                          language="the email's language", style="(not learned yet: write naturally)", saved_replies="(none)",
                                                          thread="(no earlier messages)",
                                                          **{k: email[k] for k in ("from", "subject", "body")}),
                               prompt_key=prompt.key, prompt_version=prompt.version,
                               mock_response=f"Hi,\n\nThanks for your email about \"{email['subject']}\". [Add your reply here.]\n\nBest regards,\nThe {business} team")
            reply = r.text.strip()
        except AllModelsFailed:
            reply = None
    return {**{k: triage.get(k) for k in ("category", "urgent", "urgent_reason", "needs_reply", "summary", "entities", "language")},
            "risk": list(dict.fromkeys(risk)), "reply": reply}


async def doc(p: dict) -> dict:
    from agentry.automations import doc_drafter as m
    kind = p.get("kind") if p.get("kind") in ("sop", "proposal", "checklist") else "sop"
    brief, business = _long(p.get("brief"), 1500), _s(p.get("business"), 80) or "our business"
    if len(brief.split()) < 5:
        raise TryRefused(422, "describe it in a sentence or two")
    d, probs = {}, []
    for _ in range(2):
        prompt = load("doc_draft")
        msgs = prompt.render(business=business, kind=kind, brief=brief, facts="(none)")
        if probs:
            msgs.append({"role": "user", "content": "Fix these problems: " + "; ".join(probs)})
        try:
            r = await complete(prompt.tier, msgs, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                               mock_response=json.dumps(m._mock(kind, brief)), temperature=0.4)
        except AllModelsFailed as e:
            raise TryRefused(503, "the AI is busy: try again in a minute") from e
        d = r.data if isinstance(r.data, dict) else {}
        probs = m.problems(d, brief, kind)
        if not probs:
            break
    return {"kind": kind, "title": d.get("title"), "content": d.get("content") or "", "diagram": d.get("diagram") or "", "problems": probs}


def festivals_ahead(n: int = 4) -> list[dict]:
    from agentry.automations import festivals as m
    cfg = {"festivals": list(m.FESTIVALS), "festival_dates": {}}
    return [{"key": f["key"], "name": f["name"], "date": f["date"].isoformat()} for f in m.upcoming(cfg, today() + timedelta(days=5), 200)][:n]


async def festival(p: dict) -> dict:
    from agentry.automations import festivals as m
    ahead = festivals_ahead(6)
    f = next((x for x in ahead if x["key"] == p.get("festival")), ahead[0] if ahead else None)
    if not f:
        raise TryRefused(422, "no festival coming up")
    business, offer = _s(p.get("business"), 80) or "SmileCraft Dental", _s(p.get("offer"), 160)
    about, lang = _s(p.get("about"), 300) or "a family dental clinic", _s(p.get("language"), 30) or "English"
    on = date.fromisoformat(f["date"])
    mock = {"theme": f"Celebrating {f['name']} with our customers",
            "posts": [{"platform": pl, "text": f"Wishing you a joyful {f['name']} from all of us at {business}! #Festive #India"} for pl in ("instagram", "facebook")],
            "whatsapp": f"Happy {f['name']} from {business}!{(' ' + offer) if offer else ''} Reply here if we can help.", "greeting": f"Happy {f['name']}!",
            "timeline": [{"when": "7 days before", "what": "Post 1 and the WhatsApp message"}, {"when": "On the day", "what": "The greeting"}]}
    plan, probs = {}, []
    for _ in range(2):
        prompt = load("festival_campaign")
        msgs = prompt.render(business=business, about=about, services=about, festival=f["name"], date=f"{on:%d %B %Y}", offer=offer or "none", language=lang)
        if probs:
            msgs.append({"role": "user", "content": "Fix these problems: " + "; ".join(probs)})
        try:
            r = await complete(prompt.tier, msgs, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                               mock_response=json.dumps(mock), temperature=0.7)
        except AllModelsFailed as e:
            raise TryRefused(503, "the AI is busy: try again in a minute") from e
        plan = r.data if isinstance(r.data, dict) else {}
        probs = m.plan_problems(plan, offer)
        if not probs:
            break
    return {"festival": f, "plan": plan, "problems": probs}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[“”\"'‘’]", "", s or "")).strip().lower()


CONTENT_PROMPT = """You turn a talk, podcast transcript or article into social posts for the speaker's business.

Return only JSON: {"posts": [{"platform": "linkedin" | "instagram" | "x", "hook": <the first line>, "text": <the post>,
"quote": <one sentence copied WORD FOR WORD from the source that the post is built on>}]}

Write 3 posts: one LinkedIn (80-150 words, a story or lesson), one Instagram caption (40-80 words, 3-5 hashtags at the
end) and one X post (under 260 characters). Use only what the source says: no invented numbers, names, results or offers.
The quote must be an exact sentence from the source; never change its words."""


async def content(p: dict) -> dict:
    src = _long(p.get("text"), 5000)
    if len(src.split()) < 40:
        raise TryRefused(422, "paste at least a paragraph (40+ words)")
    speaker = _s(p.get("speaker"), 80) or "the speaker"
    first = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", src) if len(s.split()) >= 8), src[:200])
    mock = {"posts": [{"platform": pl, "hook": first[:80], "text": first, "quote": first} for pl in ("linkedin", "instagram", "x")]}
    try:
        r = await complete("writer", [{"role": "system", "content": CONTENT_PROMPT}, {"role": "user", "content": f"Speaker: {speaker}\n\nSource:\n{src}"}],
                           prompt_key="playground_content", prompt_version="v1", json_output=True, mock_response=json.dumps(mock), temperature=0.6)
    except AllModelsFailed as e:
        raise TryRefused(503, "the AI is busy: try again in a minute") from e
    posts = (r.data or {}).get("posts") if isinstance(r.data, dict) else None
    body = _norm(src)
    out = []
    for x in posts if isinstance(posts, list) else []:
        if isinstance(x, dict) and x.get("text"):
            q = str(x.get("quote") or "")
            out.append({"platform": x.get("platform"), "hook": x.get("hook"), "text": x["text"], "quote": q,
                        "quote_checked": bool(q) and _norm(q) in body})
    return {"posts": out[:3]}


async def video(p: dict) -> dict:
    from agentry.automations.video_studio import RISKY
    business, topic = _s(p.get("business"), 80) or "SmileCraft Dental", _s(p.get("topic"), 160)
    if len(topic) < 4:
        raise TryRefused(422, "give a topic")
    about = _s(p.get("about"), 300) or business
    mock = {"hook": f"Three things nobody tells you about {topic}", "beats": [{"at": "0-3s", "say": f"Three things about {topic}.", "show": "Close-up", "on_screen": topic}],
            "cta": f"Book with {business}", "caption": topic, "hashtags": ["#Shorts"], "seconds": 30}
    s = await _ask("video_script", mock, business=business, about=about, services=about, topic=topic, cta=_s(p.get("cta"), 120) or "Book on WhatsApp",
                   language=_s(p.get("language"), 30) or "English")
    words = " ".join([s.get("hook") or "", s.get("cta") or "", s.get("caption") or "",
                      *[f"{b.get('say', '')} {b.get('on_screen', '')}" for b in s.get("beats") or [] if isinstance(b, dict)]])
    flags = [f"risky wording: \"{m.group(0)}\" (would be sent back for a rewrite)" for m in RISKY.finditer(words)][:3]
    return {"script": s, "checks": flags}


async def hiring(p: dict) -> dict:
    from agentry.automations import hiring as m
    must = p.get("must_have")
    must = [_s(x, 80) for x in (must if isinstance(must, list) else re.split(r"[,\n;]", str(must or ""))) if _s(x, 80)][:8]
    job = {"title": _s(p.get("title"), 120) or "Role", "must_have": must, "description": _long(p.get("description"), 2000)}
    cv = _long(p.get("cv"), 8000)
    if len(cv.split()) < 30:
        raise TryRefused(422, "paste a CV (30+ words)")
    hidden = sorted({x.group(0).lower() for x in m.SKIP.finditer(cv)})
    return {**(await m.score(None, job, cv)), "hidden": hidden}


async def notice(p: dict) -> dict:
    from agentry.automations.ca import notices as m
    body = _long(p.get("text"), 12000)
    if len(body.split()) < 30:
        raise TryRefused(422, "paste the notice's text")
    sample = (_ca_samples() / "notice_143_1_sample.txt").read_text().strip()
    try:
        return await m.read(None, {"name": "the client"}, body.encode(), "text/plain", "notice_143_1_sample.txt" if _norm(body) == _norm(sample) else None)
    except Exception as e:  # CaError: the reading service is busy
        raise TryRefused(503, str(e) or "the AI is busy: try again in a minute") from e


BILL_SAMPLES = ("supplier-tax-invoice.png", "grocery-receipt.jpg", "cafe-receipt-smudged.jpg")


async def bill(p: dict) -> dict:
    from agentry import documents as m
    from agentry.automations.bookkeeping import CATEGORIES
    if p.get("sample") in BILL_SAMPLES:
        data, mime = (m.SAMPLES / p["sample"]).read_bytes(), "image/png" if p["sample"].endswith(".png") else "image/jpeg"
    else:
        data, mime = _image(p.get("image"))
    try:
        raw = await m.read(None, data, mime, CATEGORIES)
    except AllModelsFailed as e:
        raise TryRefused(503, "the AI is busy: try again in a minute") from e
    except m.DocumentError as e:
        raise TryRefused(422, str(e)) from e
    if not raw.get("is_document"):
        return {"is_document": False}
    fields = m.normalise(raw.get("fields") or {}, CATEGORIES)
    unclear = m.mark_unclear(fields, raw.get("unclear"))
    items = m.items_of(raw.get("items"))
    checks = m.check(fields, items=items)
    status, confidence = m.decide(fields, checks, 0.85)
    return {"is_document": True, "fields": fields, "items": items, "checks": checks, "unclear": unclear, "status": status, "confidence": confidence}


async def shelf(p: dict) -> dict:
    data, mime = _image(p.get("image"))
    if mime == "application/pdf":
        raise TryRefused(422, "send a photo of the shelf")
    prompt = load("stock_scan")
    msgs = prompt.render(known="(none yet)", area=_s(p.get("area"), 60) or "not given")
    msgs[-1] = {"role": "user", "content": [{"type": "text", "text": msgs[-1]["content"]},
                                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}]}
    from agentry.automations.stock import SAMPLE
    try:
        r = await complete(prompt.tier, msgs, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                           mock_response=json.dumps({"items": SAMPLE["items"]}), temperature=0)
    except AllModelsFailed as e:
        raise TryRefused(503, "the AI is busy: try again in a minute") from e
    out = []
    for x in (r.data or {}).get("items", []) if isinstance(r.data, dict) else []:
        try:
            out.append({"name": _s(x["name"], 120), "count": max(0, round(float(x.get("count") or 0))), "unit": _s(x.get("unit"), 20) or "pc",
                        "confidence": round(max(0.0, min(1.0, float(x.get("confidence") or 0))), 2)})
        except (KeyError, TypeError, ValueError):
            continue
    return {"items": out[:40]}


async def excel(p: dict) -> dict:
    from agentry.automations.ca import core
    from agentry.automations.ca import excel as m
    rows = _rows(p.get("rows")) if p.get("rows") else _csv(_ca_samples() / "tds_register_sample.csv")
    q = _s(p.get("question"), 300)
    if len(q) < 4:
        raise TryRefused(422, "ask a question about the sheet")
    try:
        return _jsonable(await m.ask(None, rows, q))
    except core.CaError as e:
        raise TryRefused(422, f"couldn't answer that from the sheet: {e}") from e


async def reactivation(p: dict) -> dict:
    business, first = _s(p.get("business"), 80) or "SmileCraft Dental", _s(p.get("first_name"), 40) or "Rahul"
    interest, when = _s(p.get("interest"), 160) or "teeth aligners", _s(p.get("when"), 40) or "about 8 months ago"
    offer = _s(p.get("offer"), 160)
    out = []
    for n in (1, 2, 3):
        mock = {"subject": f"Still thinking about {interest}?", "body": f"Hi {first}, you asked us about {interest} {when}. Still thinking about it? – {business}"}
        out.append({"step": n, "after_days": {1: 0, 2: 4, 3: 10}[n], **await _ask("reactivation_writer", mock, business=business, signoff=business, first_name=first,
                                                                                 interest=interest, when=when, step_number=n, step_total=3, offer=offer or "")})
    return {"messages": out}


LIVE = {"bank": bank, "lead-research": lead_research, "cold-email": cold_email, "inbox": inbox, "doc": doc, "festival": festival, "content": content,
        "video": video, "hiring": hiring, "notice": notice, "bill": bill, "shelf": shelf, "excel": excel, "reactivation": reactivation}


# ---------- samples ----------

def _text_sample(name: str) -> str:
    return (_ca_samples() / name).read_text().strip()


def _podcast() -> str:
    from agentry.config import ROOT
    d = json.loads((ROOT / "mock-data" / "content" / "sample-podcast.json").read_text())
    said = [s["text"] for s in d["segments"] if s["speaker"] != "Host"]
    return " ".join(said)[:2400]


def sample(kind: str) -> dict:
    ca = _ca_samples()
    if kind == "itr":
        return ITR_SAMPLE
    if kind == "capital-gains":
        return {"rows": _from_header(_csv(ca / "broker_pnl_sample.csv"), ("symbol|scrip|name", "buy|purchase"))}
    if kind == "tds":
        return {"rows": _csv(ca / "tds_register_sample.csv")}
    if kind == "audit-3cd":
        return {"rows": _csv(ca / "ledger_sample.csv"), "fy_start": 2025}
    if kind == "gst":
        from agentry.automations.ca import gst as m
        return {"rows": _csv(ca / "purchase_register_sample.csv"), "gstr2b": m.from_2b_json(json.loads((ca / "gstr2b_sample.json").read_text()))}
    if kind == "bank":
        return {"rows": _from_header(_csv(ca / "bank_statement_sample.csv"), ("date", "narration|description|particulars", "withdrawal|debit|dr"))}
    if kind == "excel":
        return {"rows": _csv(ca / "tds_register_sample.csv"),
                "questions": ["Total TDS deducted by section", "Which payments were over ₹50,000?", "How many deductees are there?"]}
    if kind == "notice":
        return {"text": _text_sample("notice_143_1_sample.txt")}
    if kind == "tax-docs":
        return {"form16_tds": 241500, "ais_interest": 52310, "form16": _text_sample("form16_sample.txt"), "ais": _text_sample("ais_sample.txt")}
    if kind == "festival":
        return {"festivals": festivals_ahead(6)}
    if kind == "content":
        return {"text": _podcast(), "speaker": "Dr. Neha Sharma, SmileCraft Dental"}
    if kind == "bill":
        return {"samples": list(BILL_SAMPLES)}
    raise TryRefused(404, "no sample for this")


# ---------- running a try ----------

async def run(kind: str, payload: dict, *, ip: str | None, token: str | None) -> dict:
    from agentry import official_rules
    await official_rules.fresh()
    if kind in CALC:
        async with system_session() as conn:
            if not await site_audit.hit(conn, f"pgc:{site_audit.ip_hash(ip)}", CALC_PER_HOUR, "1 hour"):
                raise TryRefused(429, "that's a lot of tries: give it a few minutes")
        try:
            out = CALC[kind](payload)
            return await out if asyncio.iscoroutine(out) else out
        except TryRefused:
            raise
        except Exception as e:  # CaError (a column missing, a bad date) and friends: say what's wrong with the input
            raise TryRefused(422, f"couldn't read that: {e}" if str(e) else "couldn't read that: check the rows") from e
    if kind not in LIVE:
        raise TryRefused(404, "unknown try-it box")
    if not await site_audit.verify_turnstile(token, ip):
        raise TryRefused(400, "the human check didn't pass: please try again")
    async with system_session() as conn:
        if not await site_audit.hit(conn, f"pgl:{site_audit.ip_hash(ip)}", LIVE_PER_DAY, "24 hours"):
            raise TryRefused(429, f"{LIVE_PER_DAY} AI tries a day per visitor: ask us for a full demo to see more")
        if await site_audit.spent_today(conn) + EST_COST > settings.audit_daily_budget_usd:
            raise TryRefused(503, "lots of people are trying this today: please come back tomorrow, or ask us for a demo")
        tid = (await conn.execute(text("insert into app.public_tries (kind, ip_hash, cost_usd) values (:k, :ip, :c) returning id"),
                                  {"k": kind, "ip": site_audit.ip_hash(ip), "c": EST_COST})).scalar_one()
    bucket: list[float] = []
    token_ = gateway.spend.set(bucket)
    try:
        result = await LIVE[kind](payload)
    except TryRefused:
        raise
    except site_audit.AuditRefused as e:
        raise TryRefused(e.status, str(e)) from e
    finally:
        gateway.spend.reset(token_)
        async with system_session() as conn:
            await conn.execute(text("update app.public_tries set cost_usd = :c where id = :i"), {"c": round(sum(bucket), 4), "i": tid})
    return {**result, "cost_usd": round(sum(bucket), 4)}


# ---------- source of truth: what each box's answer rests on (shown under every try-it box) ----------

_RULES = {  # website agent slug -> official figures it uses (official_rules key prefixes / keys)
    "ca-itr-preparation": ("itr.",), "ca-capital-gains": ("cg.", "itr.rate_111a", "itr.rate_112a", "itr.ltcg_exempt"),
    "ca-tds-returns": ("tds.",), "ca-tax-audit-3cd": ("audit.",), "ca-bank-classifier": ("bank.", "audit.cash_receipt"),
}
_TEXT = {  # what the other boxes rest on: (basis, [(label, source, url)])
    "ca-gst-reconciliation": ("Your purchase register against the GSTR-2B statement, matched by supplier GSTIN and invoice number.", [
        ("GSTR-2B", "Auto-drafted ITC statement from the GST portal (the sample here is a sample download)", "https://www.gst.gov.in/"),
        ("Matching", "Same GSTIN + invoice number; tax within ₹10 counts as matched", None)]),
    "ca-tax-documents-reader": ("Only what's printed in the client's Form 16 and AIS: every figure is traced to its line.", [
        ("Form 16", "Issued by the employer (TRACES)", "https://www.tdscpc.gov.in/"), ("AIS / 26AS", "The department's statement on the e-filing portal", "https://www.incometax.gov.in/iec/foportal/")]),
    "ca-document-chaser": ("The documents each filing needs, from what the client's profile says applies.", [
        ("Checklists", "Agentry's checklist per filing (ITR, GST, TDS, audit, ROC); each firm can edit its own", None)]),
    "ca-notice-handler": ("Only the notice's own text: the dates, demand and DIN read are checked against it before they're shown.", [
        ("The notice", "As issued by the Income Tax Department (verify it on the e-filing portal with its DIN)", "https://www.incometax.gov.in/iec/foportal/")]),
    "excel-desk": ("Your sheet. The AI only picks the columns and the calculation; the numbers are computed by code.", []),
    "ca-filing-tracker": ("The firm's own filing board: the answer to the client is read from the card's status.", []),
    "recurring-books": ("Your entries. EMIs are split with the standard reducing-balance loan formula.", []),
    "renewals": ("Your renewal dates and amounts. Reminders 30, 7 and 1 days before; win-back 15 days after (both can be changed).", []),
    "inbox-triage": ("The email itself. Fraud warnings come from fixed rules (changed bank details, lookalike domains, OTP requests); replies use only the facts you give.", []),
    "lead-research": ("Only the lead's own website and what they wrote. Numbers and names not found there are removed.", []),
    "personal-cold-email": ("One fact from the prospect's own website; a fact-checker rejects any line it doesn't support.", []),
    "sop-and-proposal-drafter": ("Only your brief (and, in the portal, your services and prices). Any number not in them is sent back for a rewrite.", []),
    "content-repurposing": ("Only your transcript or article. Each post's quote is checked word for word against it.", []),
    "ai-video-studio": ("Your business and topic. Guarantees, invented prices and superlatives are checked before anything is made.", []),
    "hiring-assistant": ("Only the CV text, with age, gender, marital status and religion removed first. Each strength quotes the CV.", []),
    "bookkeeping-assistant": ("The bill itself, then fixed checks: totals add up, CGST equals SGST, the GSTIN's check digit, the date.", [
        ("GSTIN format and check digit", "GST registration rules", "https://www.gst.gov.in/")]),
    "stock-shelf-scanner": ("Your photo. Each count shows how sure it is; doubtful ones are for a person to check.", []),
    "lead-reactivation": ("What the lead asked about before and the offer you give; nothing else is promised.", []),
    "speed-to-lead": ("Your enquiry form and your calendar's free slots. Opt-outs are respected.", []),
    "ops-dispatcher": ("Your technicians' skills, areas and daily capacity.", []),
    "invoice-follow-up": ("Your invoices and due dates. Reminders stop when an invoice is paid.", []),
}


async def sources(slug: str) -> dict:
    from agentry import official_rules
    from agentry.automations.ca import calendar as cal
    from agentry.automations.ca import due_dates
    await official_rules.fresh()
    last = await due_dates.last_sync()
    checked = last["finished_at"] if last and last["status"] == "done" else None
    if slug in _RULES:
        figs = [f for f in (await due_dates.rules_listing())["figures"] if any(f["key"].startswith(p) or f["key"] == p for p in _RULES[slug])]
        items = [{"label": f["label"], "value": f["shown"], "source": f["update"]["source"] if f.get("update") else f["source"],
                  "url": (f["update"]["source_url"] if f.get("update") else f["url"]), "updated": bool(f.get("update"))} for f in figs]
        return {"basis": "The law for FY 2025-26 (AY 2026-27), with any change since that's verified on the official source and approved.",
                "items": items, "official": True, "checked_at": checked}
    if slug == "ca-compliance-calendar":
        async with system_session() as conn:
            ups = await cal.active_updates(conn)
        laws = {v for v in cal.STANDARD.values()}
        items = [{"label": law, "value": "standard due dates", "source": "Statutory due date", "url": url, "updated": False} for law, url in sorted(laws)]
        from agentry.automations.ca import core
        items += [{"label": f"{core.KINDS.get(u['kind'], u['kind'])} {u['period']}: extended", "value": f"{u['due_on']:%d %b %Y} (was {u['original_on']:%d %b %Y})", "source": u["source"],
                   "url": u["source_url"], "updated": True} for u in ups]
        return {"basis": "The standard due date in the law for each filing, unless the government has extended it.", "items": items,
                "official": True, "checked_at": checked}
    if slug == "festival-campaigns":
        fests = festivals_ahead(8)
        items = [{"label": f["name"], "value": datetime.fromisoformat(f["date"]).strftime("%d %b %Y"), "source": official_rules.FEST[0],
                  "url": official_rules.FEST[1], "updated": False} for f in fests]
        return {"basis": "Festival dates from the government holiday lists and the published panchang; your posts use only your own offer.",
                "items": items, "official": True, "checked_at": checked}
    basis, links = _TEXT.get(slug, ("Your own input and the agent's checks; nothing is invented.", []))
    return {"basis": basis, "items": [{"label": label, "value": None, "source": src, "url": url, "updated": False} for label, src, url in links],
            "official": False, "checked_at": None}
