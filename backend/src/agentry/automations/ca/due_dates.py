"""Official changes to statutory due dates (extensions), shared by every CA firm on Agentry.

    record    one row per change (app.due_date_updates): filing kind, period, the date it replaces, the new date, and the
              notification / circular / press release it comes from. Not per firm: recorded once, followed everywhere.
    find      a check of official sources, daily at 07:30 IST and on demand ("Check for updates" in HQ or a firm's
              compliance calendar; a firm's request reuses a check from the last hour):
                live pages  official update pages that allow automated reading (Income Tax Department latest news, GST
                            portal news) are read and the AI looks for changes to the dates on the calendar
                web search  the AI searches the official sites for the same, which covers the sites that block
                            automated readers (CBIC, MCA, Income Tax press releases, e-Gazette, PIB, EPFO / ESIC)
              Each change found is verified before anyone sees it: the date it changes must be one the calendar uses, the
              source must be a government site, and the new date must appear on that page (opened and read). It's then
              a proposal in HQ (and an email to the ops inbox).
    apply     Agentry staff approve a proposal (or enter one by hand, from the notification): every firm's open cards for
              that filing and period move to the new date, their reminders start again for it, the calendar shows the
              source, and new cards are made with it. Withdrawing puts the cards back. Nothing changes a date without a
              person's approval unless AGENTRY_DUE_DATES_AUTO_APPLY is on (then only fully verified changes).
"""
import asyncio
import io
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from agentry.automations.ca import calendar, core
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.llm import gateway
from agentry.llm.gateway import AllModelsFailed, complete

OFFICIAL = ("incometax.gov.in", "incometaxindia.gov.in", "cbic.gov.in", "cbic-gst.gov.in", "gst.gov.in", "mca.gov.in", "egazette.gov.in",
            "egazette.nic.in", "pib.gov.in", "epfindia.gov.in", "esic.gov.in", "esic.nic.in", "finmin.gov.in", "dor.gov.in")
LIVE_SOURCES = [  # official update pages that allow automated reading: read directly on every check
    ("Income Tax Department: latest news", "https://www.incometax.gov.in/iec/foportal/latest-news"),
    ("GST portal: news and updates", "https://www.gst.gov.in/newsandupdates"),
]
# sites that block automated readers (or need a browser) are covered by the AI's web search of the official domains
SEARCHED = ["CBIC (cbic-gst.gov.in, taxinformation.cbic.gov.in)", "Income Tax Department press releases and circulars (incometaxindia.gov.in)",
            "MCA (mca.gov.in)", "e-Gazette (egazette.gov.in)", "PIB (pib.gov.in)", "EPFO and ESIC"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; AgentryDueDates/1.0; +https://agentry.duckdns.org)"}
FIRM_REUSE = timedelta(hours=1)
log = logging.getLogger(__name__)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]

FIND = """You keep an Indian CA firm's compliance calendar correct. Today is {today}.

These are the statutory due dates on the calendar (id | filing | period | standard due date):
{dates}

{material}

Report every EXTENSION or CHANGE of one of these due dates that the material clearly states, with the new date. Ignore
dates that are not on the list, changes that only waive late fees without moving the due date, and anything you are not
sure of. Return only JSON:
{{"changes": [{{"id": <id from the list>, "old_date": "YYYY-MM-DD" (the date the material says is being replaced: it must be
the listed standard date of that id), "new_date": "YYYY-MM-DD", "source": <the notification / circular / order / press
release, with its number and date as written>, "source_url": <the official URL it is on>, "quote": <the exact words that
give the old and new dates, copied, at most 300 characters>}}]}}
Match each change to the id whose filing AND standard date are the ones the material names (e.g. an audit report extended
"from 30th September" is the tax audit report due 30 Sep, not another form).
Return {{"changes": []}} when there are none."""


# ---------- what the calendar uses (the only dates a change can apply to) ----------

def candidates(today: date) -> list[dict]:
    """Every (filing, period, standard date) the calendar can produce from 45 days ago to 5 months ahead."""
    every = {k: True for k in core.PROFILE_FLAGS}
    profiles = [("individual", {**every, "audit": False, "gst_qrmp": False, "gst_composition": False, "transfer_pricing": False}),
                ("individual", {**every, "gst_qrmp": True, "gst_composition": False, "transfer_pricing": False}),
                ("firm", {**every, "gst_qrmp": False, "gst_composition": True, "transfer_pricing": False}),
                ("company", {**every, "gst_qrmp": False, "gst_composition": False, "transfer_pricing": False}),
                ("company", {**every, "gst_qrmp": False, "gst_composition": False, "transfer_pricing": True}), ("llp", every)]
    seen: dict[tuple, dict] = {}
    for kind, prof in profiles:
        for gstin in ("27", "09"):  # a 22nd and a 24th state for quarterly GSTR-3B
            for d in calendar.deadlines(kind, prof, today - timedelta(days=45), today + timedelta(days=150), gstin=gstin):
                key = (d["kind"], d["period"], d["standard_on"])
                seen.setdefault(key, {"kind": d["kind"], "period": d["period"], "standard_on": d["standard_on"], "title": d["title"]})
    out = sorted(seen.values(), key=lambda c: (c["standard_on"], c["kind"]))
    return [{**c, "id": i + 1} for i, c in enumerate(out)]


def _listing(cands: list[dict]) -> str:
    return "\n".join(f"{c['id']} | {core.KINDS[c['kind']]} | {c['period']} | {c['standard_on']:%d %b %Y}" for c in cands)


# ---------- reading sources ----------

def official(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL)


async def read_page(url: str) -> str:
    """The page's text (HTML or PDF), or raises."""
    from agentry.knowledge import _check_public, extract
    _check_public(url)
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=UA) as c:
        r = await c.get(url)
    r.raise_for_status()
    if "pdf" in r.headers.get("content-type", "") or url.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:15])
    page = extract(r.text, url)
    return page.text or re.sub(r"<[^>]+>", " ", r.text)


def date_forms(d: date) -> list[str]:
    m = MONTHS[d.month - 1]
    suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return [f"{d:%d.%m.%Y}", f"{d:%d/%m/%Y}", f"{d:%d-%m-%Y}", f"{d.day}.{d.month}.{d.year}", f"{d.day}/{d.month}/{d.year}",
            f"{d.day} {m} {d.year}", f"{d.day}{suffix} {m} {d.year}", f"{d.day}{suffix} {m}, {d.year}", f"{d.day} {m}, {d.year}",
            f"{m} {d.day}, {d.year}", f"{m} {d.day} {d.year}", f"{d.day}-{m[:3]}-{d.year}", f"{d.day} {m[:3]} {d.year}",
            f"{d.day}{suffix} {m[:3]} {d.year}", f"{d.day}{suffix} {m[:3]}, {d.year}", f"{d:%Y-%m-%d}"]


def mentions(page: str, d: date) -> bool:
    low = re.sub(r"\s+", " ", page.lower())
    return any(f in low for f in date_forms(d))


async def _ask(material: str, cands: list[dict], today: date) -> list[dict]:
    """The AI reads the material against the calendar's dates."""
    prompt = FIND.format(today=f"{today:%d %b %Y}", dates=_listing(cands), material=material)
    try:
        r = await complete("fast", [{"role": "user", "content": prompt}], prompt_key="due_date_find", prompt_version="v1",
                           json_output=True, mock_response=json.dumps({"changes": []}), temperature=0)
    except AllModelsFailed:
        return []
    ch = (r.data or {}).get("changes") if isinstance(r.data, dict) else None
    return [c for c in ch or [] if isinstance(c, dict)]


async def from_pages(cands: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """(changes, sources checked) from the official update pages."""
    async def one(name: str, url: str) -> tuple[dict, str | None]:
        try:
            body = await read_page(url)
            ok = len(body.split()) > 150  # a page that loads its news with JavaScript gives only its menu
            return {"name": name, "url": url, "ok": ok, "note": None if ok else "page had no readable text (it needs a browser)"}, body if ok else None
        except Exception as e:  # noqa: BLE001 - one site being down never stops the check
            return {"name": name, "url": url, "ok": False, "note": f"couldn't open: {type(e).__name__}"}, None
    got = await asyncio.gather(*(one(n, u) for n, u in LIVE_SOURCES))
    sources = [s for s, _ in got]
    texts = [(s, b) for s, b in got if b]
    changes: list[dict] = []
    for s, body in texts:
        for c in await _ask(f"Material: the official page \"{s['name']}\" ({s['url']}), as it reads today:\n{body[:18000]}", cands, today):
            c["source_url"] = s["url"]
            changes.append(c)
    return changes, sources


async def from_search(cands: list[dict], today: date) -> tuple[list[dict], dict]:
    """The AI searches the official sites (OpenAI web search). Off when there's no OpenAI key (tests, local)."""
    from agentry import ai_search
    model = next((m for m in ai_search.engines().values() if m.startswith("openai/")), None)
    if not model:
        return [], {"name": "Web search of official sites", "url": None, "ok": False, "note": "no search engine configured"}
    import litellm
    ask = FIND.format(today=f"{today:%d %b %Y}", dates=_listing(cands), material=(
        "Material: search the official sites (" + ", ".join(OFFICIAL) + ") and news of them for notifications, circulars, orders "
        "and press releases from the last 120 days that extend or change these due dates. Use only official sources for source_url."))
    try:
        r = await litellm.aresponses(model=model, input=ask, timeout=150,
                                     tools=[{"type": "web_search", "search_context_size": "medium", "user_location": {"type": "approximate", "country": "IN"}}])
        msgs = [o for o in r.output if getattr(o, "type", "") == "message"]
        txt = "\n".join(getattr(p, "text", "") or "" for p in (msgs[-1].content if msgs else []))
        try:
            cost = float(litellm.completion_cost(completion_response=r)) or settings.ai_search_cost_usd * 3
        except Exception:  # noqa: BLE001
            cost = settings.ai_search_cost_usd * 3
        if (bucket := gateway.spend.get()) is not None:
            bucket.append(cost)
    except Exception as e:  # noqa: BLE001
        return [], {"name": "Web search of official sites", "url": None, "ok": False, "note": f"search failed: {type(e).__name__}"}
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    ch = [c for c in data.get("changes") or [] if isinstance(c, dict)]
    return ch, {"name": "Web search of official sites", "url": None, "ok": True, "note": f"{len(ch)} possible change(s)"}


ABOUT = {  # words the source's own sentence must use for the filing it moves (stops a change landing on another filing due the same day)
    "itr": r"return of income|income tax return|\bitr\b|returns? of income", "tax_audit": r"audit report|tax audit|3ca|3cb|3cd",
    "form_3ceb": r"3ceb|transfer pricing|section 92e", "tds_24q": r"\btds\b|24q|tds statement|tds return",
    "tds_26q": r"\btds\b|26q|tds statement|tds return", "tcs_27eq": r"\btcs\b|27eq", "tds_payment": r"\btds\b|\btcs\b|deposit of tax",
    "advance_tax": r"advance tax", "gstr1": r"gstr-?1\b|form gstr-1", "gstr3b": r"gstr-?3b", "gstr9": r"gstr-?9\b|annual return",
    "gstr4": r"gstr-?4\b", "gst_cmp08": r"cmp-?08", "gstr7": r"gstr-?7\b", "gstr8": r"gstr-?8\b", "roc_aoc4": r"aoc-?4|form 8\b|financial statement",
    "roc_mgt7": r"mgt-?7|form 11\b|annual return", "dir3_kyc": r"dir-?3|kyc", "pf_esi": r"\bpf\b|provident fund|\besi\b|ecr",
}


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


async def verify(c: dict, by_id: dict[int, dict]) -> dict | None:
    """A change the calendar can use, with its checks; None when it isn't one: the old date must be the calendar's date
    for that filing, and the new date must be later (an extension) and within a year."""
    try:
        cand = by_id[int(c.get("id"))]
    except (TypeError, ValueError, KeyError):
        return None
    new, old = core.parse_date(c.get("new_date")), core.parse_date(c.get("old_date"))
    if not new or old != cand["standard_on"] or not cand["standard_on"] < new <= cand["standard_on"] + timedelta(days=366):
        return None
    quote = str(c.get("quote") or "")[:400] or None
    if not quote or not re.search(ABOUT.get(cand["kind"], r"."), quote, re.IGNORECASE):
        return None  # the words given don't speak of this filing: a mismatch, not a change to it
    url = str(c.get("source_url") or "")
    if official(url):
        url = url.split("?")[0].split("#")[0]  # search links carry tracking junk; the page is the page
    url = url if url.startswith("http") and len(url) <= 300 else None
    checks = {"official": official(url), "opened": False, "date_on_page": False, "quote_on_page": False, "note": None}
    if checks["official"]:
        try:
            page = await read_page(url)
            checks["opened"] = True
            checks["date_on_page"] = mentions(page, new)
            checks["quote_on_page"] = bool(quote) and _norm(quote)[:120] in _norm(page)
            if not (checks["date_on_page"] and checks["quote_on_page"]):
                checks["note"] = "the new date or the quoted words aren't on the source page: read it before approving"
        except Exception as e:  # noqa: BLE001
            checks["note"] = f"couldn't open the source ({type(e).__name__}): open it yourself before approving"
    else:
        checks["note"] = ("no usable link to the source" if not url else "the source isn't a government site") + ": find the official notification before approving"
    return {"kind": cand["kind"], "period": cand["period"], "original_on": cand["standard_on"], "due_on": new,
            "title": f"{cand['title']}: {cand['standard_on']:%d %b %Y} → {new:%d %b %Y}", "source": str(c.get("source") or "unnamed source")[:300],
            "source_url": url, "quote": quote, "checks": checks}


# ---------- the check ----------

async def last_sync() -> dict | None:
    async with system_session() as conn:
        r = (await conn.execute(text("""select id::text, trigger, status, found, proposed, sources, error, started_at, finished_at
            from app.due_date_syncs order by started_at desc limit 1"""))).mappings().first()
    return dict(r) if r else None


async def request_sync(trigger: str, org_id: str | None = None) -> dict:
    """A firm's or HQ's "check now": a firm's request reuses a check from the last hour. Returns the sync row to watch."""
    last = await last_sync()
    if last and (last["status"] == "running" and last["started_at"] > datetime.now(UTC) - timedelta(minutes=10)):
        return last | {"reused": True}
    if trigger == "firm" and last and last["status"] == "done" and last["started_at"] > datetime.now(UTC) - FIRM_REUSE:
        return last | {"reused": True}
    async with system_session() as conn:
        sid = str((await conn.execute(text("insert into app.due_date_syncs (trigger, org_id) values (:t, :o) returning id"),
                                      {"t": trigger, "o": org_id})).scalar_one())
        from agentry.events import emit
        await emit(conn, None, "due_dates.sync_requested", {"sync_id": sid})
    return {"id": sid, "status": "running", "reused": False}


async def run_sync(sync_id: str | None = None, trigger: str = "daily", today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    if not sync_id:
        async with system_session() as conn:
            sync_id = str((await conn.execute(text("insert into app.due_date_syncs (trigger) values (:t) returning id"), {"t": trigger})).scalar_one())
    bucket: list[float] = []
    tok = gateway.spend.set(bucket)
    try:
        cands = candidates(today)
        by_id = {c["id"]: c for c in cands}
        (page_changes, sources), (search_changes, search_src) = await asyncio.gather(from_pages(cands, today), from_search(cands, today))
        found = [v for v in await asyncio.gather(*(verify(c, by_id) for c in page_changes + search_changes)) if v]
        new = await _propose(found)
        if new and settings.due_dates_auto_apply:
            for u in new:
                if u["checks"]["official"] and u["checks"]["date_on_page"] and u["checks"]["quote_on_page"]:
                    await approve(u["id"], "auto (verified on the official page)")
        status, err = "done", None
    except Exception as e:  # noqa: BLE001 - recorded on the sync row, retried tomorrow
        found, new, sources, search_src, status, err = [], [], [], {}, "failed", f"{type(e).__name__}: {e}"[:500]
    finally:
        gateway.spend.reset(tok)
    async with system_session() as conn:
        await conn.execute(text("""update app.due_date_syncs set status = :s, found = :f, proposed = :p, sources = cast(:src as jsonb), error = :e,
            cost_usd = :c, finished_at = now() where id = cast(:i as uuid)"""),
            {"s": status, "f": len(found), "p": len(new), "src": json.dumps([*sources, *([search_src] if search_src else [])]), "e": err,
             "c": round(sum(bucket), 4), "i": sync_id})
    if new:
        await _tell_ops(new)
    return {"id": sync_id, "status": status, "found": len(found), "proposed": len(new), "error": err}


async def _propose(found: list[dict]) -> list[dict]:
    out = []
    async with system_session() as conn:
        for f in found:
            dup = (await conn.execute(text("""select 1 from app.due_date_updates where kind = :k and period = :p and due_on = :d
                and original_on is not distinct from :o"""), {"k": f["kind"], "p": f["period"], "d": f["due_on"], "o": f["original_on"]})).first()
            if dup:
                continue
            uid = str((await conn.execute(text("""insert into app.due_date_updates (kind, period, original_on, due_on, title, source, source_url,
                quote, found_by, checks) values (:k, :p, :o, :d, :t, :s, :u, :q, 'sync', cast(:c as jsonb)) returning id"""),
                {"k": f["kind"], "p": f["period"], "o": f["original_on"], "d": f["due_on"], "t": f["title"], "s": f["source"],
                 "u": f["source_url"], "q": f["quote"], "c": json.dumps(f["checks"])})).scalar_one())
            out.append(f | {"id": uid})
    return out


async def _tell_ops(new: list[dict]) -> None:
    from agentry.notify.email import send_email
    lines = "\n\n".join(f"• {u['title']}\n  Source: {u['source']} {u['source_url'] or ''}\n  "
                        + ("Verified on the official page." if u["checks"]["date_on_page"] and u["checks"]["quote_on_page"] else (u["checks"]["note"] or "")) for u in new)
    body = (f"The daily check of official sources found {len(new)} possible change(s) to statutory due dates:\n\n{lines}\n\n"
            "Approve or reject them in HQ → Due dates. Nothing changes on any firm's calendar until you approve.")
    try:
        await asyncio.to_thread(send_email, settings.ops_email, f"{len(new)} due date change(s) to review", body)
    except Exception as e:  # noqa: BLE001 - the proposals are in HQ either way
        log.warning("couldn't email the due date changes: %s", e)


# ---------- applying ----------

async def _ca_orgs() -> list[str]:
    async with system_session() as conn:
        return list((await conn.execute(text("""select distinct org_id from app.automation_instances where template_key = any(:k)"""),
                                        {"k": list(core.CA_KEYS)})).scalars())


async def _move_cards(u: dict) -> int:
    """Open cards for this filing and period that still carry the date it replaces move to the new date; reminders restart."""
    ext = {"update_id": str(u["id"]), "label": u["source"], "url": u["source_url"], "type": "extension", "was": u["original_on"].isoformat()}
    moved = 0
    for org in await _ca_orgs():
        async with tenant_session(org) as conn:
            moved += (await conn.execute(text("""update app.ca_filings set due_on = :new,
                data = (data - 'reminded') || jsonb_build_object('extension', cast(:x as jsonb))
                where kind = :k and period = :p and due_on = :orig and status not in ('filed','verified')"""),
                {"new": u["due_on"], "x": json.dumps(ext), "k": u["kind"], "p": u["period"], "orig": u["original_on"]})).rowcount or 0
    return moved


async def _restore_cards(u: dict) -> int:
    back = 0
    for org in await _ca_orgs():
        async with tenant_session(org) as conn:
            back += (await conn.execute(text("""update app.ca_filings set due_on = cast(data->'extension'->>'was' as date),
                data = (data - 'extension') - 'reminded' where data->'extension'->>'update_id' = :i and due_on = :new"""),
                {"i": str(u["id"]), "new": u["due_on"]})).rowcount or 0
    return back


async def get(update_id: str) -> dict:
    async with system_session() as conn:
        u = (await conn.execute(text("select * from app.due_date_updates where id = cast(:i as uuid)"), {"i": update_id})).mappings().first()
    if not u:
        raise core.CaError("update not found")
    return dict(u)


async def approve(update_id: str, by: str) -> dict:
    u = await get(update_id)
    if u["status"] == "active":
        return u
    async with system_session() as conn:  # one active change per filing, period and date replaced
        clash = (await conn.execute(text("""select id::text from app.due_date_updates where status = 'active' and kind = :k and period = :p
            and original_on is not distinct from :o and id <> cast(:i as uuid)"""), {"k": u["kind"], "p": u["period"], "o": u["original_on"], "i": update_id})).scalar()
    if clash:
        await withdraw(clash, f"{by} (replaced)")
    moved = await _move_cards(u)
    async with system_session() as conn:
        await conn.execute(text("""update app.due_date_updates set status = 'active', decided_by = :b, decided_at = now(), cards = :n
            where id = cast(:i as uuid)"""), {"b": by[:120], "n": moved, "i": update_id})
    return await get(update_id)


async def reject(update_id: str, by: str) -> dict:
    async with system_session() as conn:
        await conn.execute(text("""update app.due_date_updates set status = 'rejected', decided_by = :b, decided_at = now()
            where id = cast(:i as uuid) and status = 'proposed'"""), {"b": by[:120], "i": update_id})
    return await get(update_id)


async def withdraw(update_id: str, by: str) -> dict:
    u = await get(update_id)
    back = await _restore_cards(u) if u["status"] == "active" else 0
    async with system_session() as conn:
        await conn.execute(text("""update app.due_date_updates set status = 'withdrawn', decided_by = :b, decided_at = now(), cards = cards - :n
            where id = cast(:i as uuid)"""), {"b": by[:120], "n": back, "i": update_id})
    return await get(update_id)


async def add(kind: str, period: str, original_on: date, due_on: date, source: str, source_url: str | None, quote: str | None, by: str) -> dict:
    """Staff enter a change from the notification itself: it's checked like a found one, then applied."""
    if kind not in core.KINDS:
        raise core.CaError("unknown filing type")
    if due_on == original_on:
        raise core.CaError("the new date is the same as the old one")
    checks = {"official": official(source_url), "opened": False, "date_on_page": False, "note": "entered by Agentry staff"}
    async with system_session() as conn:
        uid = str((await conn.execute(text("""insert into app.due_date_updates (kind, period, original_on, due_on, title, source, source_url, quote,
            found_by, checks) values (:k, :p, :o, :d, :t, :s, :u, :q, 'staff', cast(:c as jsonb)) returning id"""),
            {"k": kind, "p": period.strip(), "o": original_on, "d": due_on, "t": f"{core.KINDS[kind]} {period.strip()}: {original_on:%d %b %Y} → {due_on:%d %b %Y}",
             "s": source.strip()[:300], "u": source_url, "q": quote, "c": json.dumps(checks)})).scalar_one())
    return await approve(uid, by)


async def listing() -> dict:
    async with system_session() as conn:
        rows = (await conn.execute(text("""select id::text, kind, period, original_on, due_on, title, source, source_url, quote, status, found_by, checks,
            cards, decided_by, decided_at, created_at from app.due_date_updates order by (status = 'proposed') desc, created_at desc limit 200"""))).mappings().all()
        syncs = (await conn.execute(text("""select id::text, trigger, status, found, proposed, sources, error, cost_usd, started_at, finished_at
            from app.due_date_syncs order by started_at desc limit 10"""))).mappings().all()
    return {"updates": [dict(r) for r in rows], "syncs": [dict(s) for s in syncs]}


async def for_firm() -> dict:
    """What a firm sees on its calendar: the changes in force, how many await verification, and the last check."""
    async with system_session() as conn:
        active = (await conn.execute(text("""select kind, period, original_on, due_on, title, source, source_url, decided_at from app.due_date_updates
            where status = 'active' order by due_on desc limit 50"""))).mappings().all()
        pending = (await conn.execute(text("select count(*) from app.due_date_updates where status = 'proposed'"))).scalar_one()
    return {"active": [dict(a) for a in active], "pending": pending, "last_check": await last_sync(),
            "sources": [{"name": n, "url": u} for n, u in LIVE_SOURCES], "searched": SEARCHED}
