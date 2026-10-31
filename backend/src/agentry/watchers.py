"""Watchers (ROADMAP-V2 7.3): check something on a schedule, notice a change, explain it, notify.

    page     a web page (a competitor's offers, a price list): the readable text is hashed; on a change, the added and
             removed lines are summarised in plain words (the `fast` model, which may not add numbers that aren't in
             the change)
    price    a product page: the `fast` model reads {title, price, currency, in_stock}; the rule decides what is worth
             telling ("min_change_pct": 5 by default, any stock change)
    reviews  the business's reviews (automations/reviews): new ones are pulled and handled there

Cost stays bounded: the model runs only when the page's content hash changed. Every 15 minutes the due watchers run;
each sets its own next check. A watcher that fails three times in a row is set to 'error' and its owner is told.
"""
import difflib
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from dbos import DBOS
from sqlalchemy import text

from agentry.config import ROOT
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete

SAMPLES = ROOT / "mock-data" / "watchers"
NUMBER = re.compile(r"\d[\d,.]*")
PRICE = re.compile(r"(?:₹|Rs\.?|INR|\$|USD|€|£)\s?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
MAX_FAILURES = 3


class WatchError(Exception):
    pass


# ---------- fetching ----------

async def fetch(url: str) -> tuple[str, str]:
    """(title, readable text) of one page. Sample sites (*.example) are read from mock-data/watchers/<host>.html."""
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".example"):
        path = SAMPLES / f"{host}.html"
        if not path.exists():
            raise WatchError("sample page not found")
        from agentry.knowledge import extract
        page = extract(path.read_text(), url)
        return page.title, page.text
    from agentry.connectors.http import client
    from agentry.knowledge import UnsafeUrl, _check_public, _get_checked, extract
    try:
        _check_public(url)
        async with client(timeout=20) as c:
            c.headers["User-Agent"] = "AgentryBot/0.1 (+https://agentry.duckdns.org)"
            r = await _get_checked(c, url)
    except UnsafeUrl as e:
        raise WatchError("that address isn't a public website") from e
    except Exception as e:
        raise WatchError(f"couldn't load the page ({type(e).__name__})") from e
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        raise WatchError(f"the page answered {r.status_code}")
    page = extract(r.text[:2_000_000], str(r.url))
    return page.title, page.text


CLOCK = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE)


def _plain(line: str) -> str:
    """A line without times and dates (which change on every visit) and extra spaces."""
    return re.sub(r"\s+", " ", CLOCK.sub("", line)).strip()


def digest(textual: str) -> str:
    """Hash of the meaningful text: whitespace and dates/times don't count."""
    return hashlib.sha256(_plain(textual).lower().encode()).hexdigest()


def changes(old: str, new: str, limit: int = 12) -> list[dict]:
    """Added and removed lines (meaningful ones: over 12 characters)."""
    out = []
    before = [x for x in map(_plain, (old or "").splitlines()) if x]
    after = [x for x in map(_plain, new.splitlines()) if x]
    for line in difflib.unified_diff(before, after, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        body = line[1:].strip()
        if len(body) >= 12:
            out.append({"kind": "added" if line[0] == "+" else "removed", "text": body[:300]})
    return out[:limit]


def _guard(line: str, source: str) -> bool:
    allowed = set(NUMBER.findall(source))
    return bool(line) and len(line) <= 400 and all(n in allowed for n in NUMBER.findall(line))


async def summarise(org_id: str, name: str, diff: list[dict]) -> str:
    plain = "\n".join(f"{'+' if d['kind'] == 'added' else '-'} {d['text']}" for d in diff)
    fallback = "; ".join(("New: " if d["kind"] == "added" else "Gone: ") + d["text"][:120] for d in diff[:3])
    try:
        res = await complete("fast", [{"role": "user", "content": (
            f"A small business watches the web page '{name}'. These lines were added (+) or removed (-) since the last check:\n\n"
            f"{plain}\n\nIn one or two short sentences, say what changed that matters to the business. Use only these lines; "
            "no numbers that aren't in them; no greeting.")}], org_id=org_id, prompt_key="watch_summary", prompt_version="v1",
            mock_response=fallback)
        line = (res.text or "").strip()
    except AllModelsFailed:
        line = ""
    return line if _guard(line, plain) else fallback


async def read_price(org_id: str, title: str, page: str) -> dict:
    """{title, price, currency, in_stock}: a price pattern on the page as the fallback, the model when it can."""
    m = PRICE.search(page)
    fallback = {"title": title[:120], "price": float(m[1].replace(",", "")) if m else None,
                "currency": "INR" if m and re.search(r"₹|rs|inr", m[0], re.IGNORECASE) else ("USD" if m and "$" in m[0] else None),
                "in_stock": not re.search(r"out of stock|sold out|unavailable", page, re.IGNORECASE)}
    try:
        res = await complete("fast", [{"role": "user", "content": (
            "From this product page, return only JSON {\"title\": str, \"price\": number or null, \"currency\": ISO code or null, "
            "\"in_stock\": true/false}. The price is the current selling price of the main product (not a crossed-out price). "
            f"Use only what the page says.\n\nTitle: {title}\n\n{page[:6000]}")}],
            org_id=org_id, prompt_key="watch_price", prompt_version="v1", json_output=True, mock_response=json.dumps(fallback))
        data = res.data if isinstance(res.data, dict) else fallback
    except AllModelsFailed:
        data = fallback
    price = data.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is not None and str(int(price)) not in page.replace(",", "") and f"{price:.2f}" not in page.replace(",", ""):
        price = fallback["price"]  # a number the page doesn't show: don't trust it
    return {"title": str(data.get("title") or title)[:120], "price": price, "currency": data.get("currency") or fallback["currency"],
            "in_stock": bool(data.get("in_stock", fallback["in_stock"]))}


def price_change(old: dict | None, new: dict, min_pct: float) -> list[dict]:
    if not old:
        return []
    out = []
    if old.get("price") and new.get("price") and old["price"] != new["price"]:
        pct = (new["price"] - old["price"]) / old["price"] * 100
        if abs(pct) >= min_pct:
            out.append({"kind": "price", "from": old["price"], "to": new["price"], "pct": round(pct, 1)})
    if old.get("in_stock") is not None and old.get("in_stock") != new.get("in_stock"):
        out.append({"kind": "stock", "from": old["in_stock"], "to": new["in_stock"]})
    return out


def price_summary(name: str, value: dict, diff: list[dict]) -> str:
    parts = []
    for d in diff:
        if d["kind"] == "price":
            cur = value.get("currency") or ""
            parts.append(f"price {'dropped' if d['pct'] < 0 else 'rose'} from {cur} {d['from']:,.2f} to {cur} {d['to']:,.2f} ({d['pct']:+.1f}%)")
        else:
            parts.append("back in stock" if d["to"] else "out of stock")
    return f"{value.get('title') or name}: " + ", ".join(parts)


# ---------- one check ----------

async def check(org_id: str, watcher_id: str, now: datetime | None = None) -> dict:
    """Run one watcher now. Returns {"changed": bool, "summary"?}."""
    now = now or datetime.now(UTC)
    async with tenant_session(org_id) as conn:
        w = dict((await conn.execute(text("select * from app.watchers where id = cast(:i as uuid)"), {"i": watcher_id})).mappings().one())
    nxt = now + timedelta(minutes=w["every_minutes"])
    if w["kind"] == "reviews":
        from agentry.automations.reviews import sync
        new = await sync(org_id)
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.watchers set last_checked_at = :n, next_check_at = :x, error = null, status = 'active',
                last_changed_at = case when :c > 0 then :n else last_changed_at end where id = cast(:i as uuid)"""),
                {"n": now, "x": nxt, "c": new, "i": watcher_id})
        return {"changed": new > 0, "new_reviews": new}
    try:
        title, page = await fetch(w["url"])
    except WatchError as e:
        async with tenant_session(org_id) as conn:
            fails = int((w["last_value"] or {}).get("_failures", 0)) + 1
            await conn.execute(text("""update app.watchers set last_checked_at = :n, next_check_at = :x, error = :e,
                status = case when :f >= :max then 'error' else status end,
                last_value = coalesce(last_value, '{}'::jsonb) || jsonb_build_object('_failures', cast(:f as int)) where id = cast(:i as uuid)"""),
                {"n": now, "x": nxt, "e": str(e), "f": fails, "max": MAX_FAILURES, "i": watcher_id})
            if fails == MAX_FAILURES:
                await emit(conn, org_id, "watch.failing", {"watcher_id": watcher_id, "name": w["name"], "error": str(e)})
        return {"changed": False, "error": str(e)}
    h = digest(page)
    first = w["last_hash"] is None
    if h == w["last_hash"]:
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.watchers set last_checked_at = :n, next_check_at = :x, error = null, status = 'active',
                last_value = last_value - '_failures' where id = cast(:i as uuid)"""), {"n": now, "x": nxt, "i": watcher_id})
        return {"changed": False}
    old = w["last_value"] or {}
    if w["kind"] == "price":
        value = await read_price(org_id, title, page)
        diff = price_change(old if not first else None, value, float((w["rule"] or {}).get("min_change_pct", 5)))
        summary = price_summary(w["name"], value, diff) if diff else None
    else:
        value = {"title": title[:200], "text": page[:20000]}
        diff = [] if first else changes(old.get("text", ""), page)
        summary = await summarise(org_id, w["name"], diff) if diff else None
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""update app.watchers set last_hash = :h, last_value = cast(:v as jsonb), last_checked_at = :n, next_check_at = :x,
            error = null, status = 'active', last_changed_at = case when :c then :n else last_changed_at end where id = cast(:i as uuid)"""),
            {"h": h, "v": json.dumps(value), "n": now, "x": nxt, "c": bool(diff), "i": watcher_id})
        await conn.execute(text("""insert into app.watch_snapshots (org_id, watcher_id, hash, value, changes, summary, notified)
            values (:o, cast(:w as uuid), :h, cast(:v as jsonb), cast(:c as jsonb), :s, :nt)"""),
            {"o": org_id, "w": watcher_id, "h": h, "v": json.dumps({k: v for k, v in value.items() if k != "text"}), "c": json.dumps(diff),
             "s": summary, "nt": bool(diff)})
        if diff:
            await emit(conn, org_id, "watch.changed", {"watcher_id": watcher_id, "name": w["name"], "kind": w["kind"], "url": w["url"],
                                                       "summary": summary, "changes": diff[:5]})
    return {"changed": bool(diff), "summary": summary, "first": first}


async def due(now: datetime | None = None) -> list[tuple[str, str]]:
    async with system_session() as conn:
        return [(r.org_id, str(r.id)) for r in (await conn.execute(text("""select org_id, id from app.watchers
            where status = 'active' and next_check_at <= :n order by next_check_at limit 200"""), {"n": now or datetime.now(UTC)})).all()]


@DBOS.step()
async def watch_one(org_id: str, watcher_id: str) -> dict:
    return await check(org_id, watcher_id)


@DBOS.step()
async def watchers_due() -> list[list[str]]:
    async with system_session() as conn:  # every business with review management has its reviews watcher
        await conn.execute(text("""insert into app.watchers (org_id, kind, name, every_minutes)
            select a.org_id, 'reviews', 'Google reviews', 360 from app.automation_instances a
            where a.template_key = 'reviews' and a.status in ('live','approval_mode')
              and not exists (select 1 from app.watchers w where w.org_id = a.org_id and w.kind = 'reviews')"""))
    return [list(x) for x in await due()]


@DBOS.workflow()
async def run_watchers(scheduled_time: datetime, context) -> None:
    for org_id, wid in await watchers_due():
        await watch_one(org_id, wid)
