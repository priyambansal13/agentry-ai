"""Review management (ROADMAP-V2 9.2): read reviews, reply well, ask happy customers, report the month.

    in        a 'reviews' watcher pulls new reviews every 6 hours (Google Business Profile once connected; until then
              the sample reviews in mock-data/reviews, like the cold-email and content samples)
    classify  sentiment, topics (waiting time, staff, price...) and urgency (the `fast` model; rating-based fallback)
    alert     1-2 stars or urgent: event review.negative at once (default rule: owner + manager, critical)
    reply     a drafted reply in the business's voice -> a Needs-you card; approving posts it (edits allowed).
              Governance action reviews.reply: when an owner lets it act on its own, only 4-5 star, non-urgent
              reviews are answered without a person
    ask       after a visit is marked "showed" or an invoice is paid in full, the customer gets one friendly message
              with the review link (governance reviews.ask: quiet hours, daily limit; once per customer per 90 days;
              never someone whose last review was negative)
    monthly   on the 1st: rating trend, count, replies, themes (event reviews.monthly)
"""
import json
import re
from datetime import UTC, datetime, timedelta

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import governance
from agentry.automations import AutomationTemplate, register
from agentry.config import ROOT, settings
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.worker.handlers import on

SAMPLE = ROOT / "mock-data" / "reviews" / "sample.jsonl"
TOPICS = ["waiting time", "staff", "price", "cleanliness", "results", "booking", "communication", "pain or safety", "facilities", "other"]
KEYWORDS = {"waiting time": r"wait|late|delay", "staff": r"staff|reception|doctor|dentist|team", "price": r"price|pricey|expensive|cost|cheap",
            "cleanliness": r"clean|spotless|hygien", "results": r"result|crown|aligner|treatment|smile", "booking": r"book|appointment",
            "communication": r"call|told|explain|respond", "facilities": r"parking|wifi|seat"}


class ReviewsConfig(BaseModel):
    review_link: str | None = Field(None, title="Your Google review link", description="Google Business Profile → Ask for reviews → copy the link",
                                    json_schema_extra={"editable_by": "client"})
    ask_after_visit: bool = Field(True, title="Ask for a review after a visit", json_schema_extra={"editable_by": "client"})
    ask_after_payment: bool = Field(True, title="Ask for a review after an invoice is paid", json_schema_extra={"editable_by": "client"})
    ask_delay_hours: int = Field(2, ge=0, le=72, title="Wait before asking (hours)", json_schema_extra={"editable_by": "client"})
    reply_contact: str | None = Field(None, title="Contact to give unhappy reviewers", description="e.g. 'call us on 98200 00000'",
                                      json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="reviews",
    name="Review management",
    description="Reads new reviews, alerts you to bad ones at once, drafts replies for approval and asks happy customers for reviews.",
    config_model=ReviewsConfig,
    metrics=("reviews_received",),
))
governance.ACTIONS["reviews.reply"] = governance.Action("Post replies to 4-5 star reviews", "reviews", "reply_draft", True,
                                                        {"max_per_day": 20, "quiet_hours": False})
governance.ACTIONS["reviews.ask"] = governance.Action("Ask customers for a review", "reviews", "", True, {"max_per_day": 40, "quiet_hours": True},
                                                      levels=("shadow", "auto_limited", "auto"), fixed_default="auto_limited")


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'reviews'"))).first()
    return (row.status, ReviewsConfig(**(row.config or {})).model_dump()) if row else (None, ReviewsConfig().model_dump())


async def _business(conn: AsyncConnection, org_id: str) -> dict:
    row = (await conn.execute(text("""select o.name, s.persona from auth.organization o join app.org_settings s on s.org_id = o.id
        where o.id = :o"""), {"o": org_id})).mappings().first()
    return {"name": (row or {}).get("name") or "us", "signoff": ((row or {}).get("persona") or {}).get("signoff") or f"Team {(row or {}).get('name') or ''}".strip()}


# ---------- reading reviews ----------

async def fetch_new(org_id: str, since: datetime | None) -> list[dict]:
    """The review source. Google Business Profile isn't connected yet (it needs Google's API approval): the samples."""
    if settings.reviews_source != "sample":
        raise RuntimeError(f"reviews source '{settings.reviews_source}' isn't available yet")
    now = datetime.now(UTC)
    out = []
    for line in SAMPLE.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out.append({"source": "sample", "external_id": r["id"], "author": r["author"], "rating": r["rating"], "body": r["body"],
                        "reviewed_at": now - timedelta(days=r["days_ago"])})
    return out


def heuristic(rating: int, body: str) -> dict:
    found = [t for t, rx in KEYWORDS.items() if re.search(rx, body or "", re.IGNORECASE)][:3]
    urgent = bool(re.search(r"consumer forum|court|lawyer|legal|police|infection|bleed|swell|allerg", body or "", re.IGNORECASE))
    return {"sentiment": "positive" if rating >= 4 else ("mixed" if rating == 3 else "negative"), "topics": found or ["other"], "urgent": urgent}


async def classify(org_id: str, business: str, rating: int, body: str) -> dict:
    fallback = heuristic(rating, body)
    prompt = load("review_classifier")
    try:
        res = await complete(prompt.tier, prompt.render(business=business, rating=rating, body=body or "(no text)"), org_id=org_id,
                             prompt_key=prompt.key, prompt_version=prompt.version, json_output=True, mock_response=json.dumps(fallback))
        d = res.data if isinstance(res.data, dict) else fallback
    except AllModelsFailed:
        d = fallback
    sentiment = d.get("sentiment") if d.get("sentiment") in ("positive", "mixed", "negative") else fallback["sentiment"]
    topics = [t for t in (d.get("topics") or []) if t in TOPICS][:3] or fallback["topics"]
    return {"sentiment": sentiment, "topics": topics, "urgent": bool(d.get("urgent")) or fallback["urgent"]}


def template_reply(author: str | None, rating: int, sentiment: str, contact: str | None, signoff: str) -> str:
    name = (author or "there").split()[0]
    if sentiment == "positive":
        return f"Thank you so much, {name}! We're really glad you had a good experience and look forward to seeing you again. {signoff}"
    reach = f" Please {contact}" if contact else " Please get in touch with us directly"
    return (f"Hi {name}, thank you for telling us, and we're sorry about your experience. We'd like to put this right.{reach} "
            f"so we can look into it. {signoff}")


async def draft_reply(org_id: str, biz: dict, cfg: dict, r: dict, sentiment: str) -> str:
    fallback = template_reply(r["author"], r["rating"], sentiment, cfg.get("reply_contact"), biz["signoff"])
    prompt = load("review_reply")
    try:
        res = await complete(prompt.tier, prompt.render(business=biz["name"], signoff=biz["signoff"], contact=cfg.get("reply_contact") or "the business's phone or email",
                                                        author=r["author"] or "a customer", rating=r["rating"], body=r["body"] or "(no text)"),
                             org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, mock_response=fallback)
        reply = (res.text or "").strip().strip('"')
    except AllModelsFailed:
        reply = ""
    # no numbers (prices, discounts, dates) the review didn't contain; nothing too long
    allowed = set(re.findall(r"\d[\d,.]*", (r["body"] or "") + " " + (cfg.get("reply_contact") or "")))
    if not reply or len(reply) > 700 or any(n not in allowed for n in re.findall(r"\d[\d,.]*", reply)):
        return fallback
    return reply


async def sync(org_id: str) -> int:
    """Pull and handle new reviews. Returns how many were new."""
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode"):
            return 0
        biz = await _business(conn, org_id)
        since = (await conn.execute(text("select max(reviewed_at) from app.reviews"))).scalar_one_or_none()
    new = 0
    for r in await fetch_new(org_id, since):
        async with tenant_session(org_id) as conn:
            rid = (await conn.execute(text("""insert into app.reviews (org_id, source, external_id, author, rating, body, reviewed_at)
                values (:o, :s, :e, :a, :r, :b, :t) on conflict (org_id, source, external_id) do nothing returning id::text"""),
                {"o": org_id, "s": r["source"], "e": r["external_id"], "a": r["author"], "r": r["rating"], "b": r["body"], "t": r["reviewed_at"]})).scalar_one_or_none()
        if rid:
            new += 1
            await handle(org_id, rid, r, biz, cfg)
    return new


async def handle(org_id: str, rid: str, r: dict, biz: dict, cfg: dict) -> str:
    c = await classify(org_id, biz["name"], r["rating"], r["body"])
    urgent = c["urgent"] or r["rating"] <= 2
    reply = await draft_reply(org_id, biz, cfg, r, c["sentiment"])
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""update app.reviews set sentiment = :s, topics = :t, urgent = :u, reply = :rp, reply_status = 'drafted'
            where id = cast(:i as uuid)"""), {"s": c["sentiment"], "t": c["topics"], "u": urgent, "rp": reply, "i": rid})
        await emit(conn, org_id, "review.received", {"review_id": rid, "rating": r["rating"], "sentiment": c["sentiment"]})
        if urgent:
            await emit(conn, org_id, "review.negative", {"review_id": rid, "rating": r["rating"], "author": r["author"],
                                                         "excerpt": (r["body"] or "")[:200], "urgent": c["urgent"]})
        if r["rating"] >= 4 and not urgent:
            d = await governance.decide(conn, org_id, "reviews.reply")
            if d.mode == "send":
                await post_reply(conn, org_id, rid, reply, by=None)
                return "posted"
            if d.mode == "shadow":
                return "shadow"
        stars = "★" * r["rating"]
        aid = (await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
            values (:o, 'reply_draft', 'reviews', :t, :b, cast(:p as jsonb)) returning id::text"""),
            {"o": org_id, "t": f"Reply to {r['author'] or 'a reviewer'}'s {stars} review", "b": reply,
             "p": json.dumps({"review_id": rid, "rating": r["rating"], "review": (r["body"] or "")[:1000], "topics": c["topics"],
                              **({"urgent": True} if urgent else {})})})).scalar_one()
        await conn.execute(text("update app.reviews set approval_id = cast(:a as uuid) where id = cast(:i as uuid)"), {"a": aid, "i": rid})
    return "card"


async def post_reply(conn: AsyncConnection, org_id: str, rid: str, body: str, by: str | None) -> None:
    """Publish the reply where the review is. Google: not connected yet, so the reply is recorded (sample mode)."""
    await conn.execute(text("""update app.reviews set reply = :b, reply_status = 'posted', replied_at = now() where id = cast(:i as uuid)"""),
                       {"b": body, "i": rid})
    await emit(conn, org_id, "review.replied", {"review_id": rid, "by": by, "sample": settings.reviews_source == "sample"})


@on("approval.decided")
@DBOS.workflow()
async def review_card_decided(event: dict) -> None:
    p = event["payload"]
    if p.get("kind") == "reply_draft":
        await review_card_step(event["org_id"], p["approval_id"], p.get("status", ""))


@DBOS.step()
async def review_card_step(org_id: str, approval_id: str, status: str) -> str:
    async with tenant_session(org_id) as conn:
        a = (await conn.execute(text("""select body, payload, decided_by, automation_key from app.approvals where id = cast(:a as uuid)"""),
                                {"a": approval_id})).mappings().first()
        if not a or a["automation_key"] != "reviews":
            return "not_mine"
        rid = a["payload"]["review_id"]
        if status in ("approved", "edited"):
            await post_reply(conn, org_id, rid, a["body"], by=a["decided_by"])
            return "posted"
        if status == "rejected":
            await conn.execute(text("update app.reviews set reply_status = 'skipped' where id = cast(:i as uuid)"), {"i": rid})
            return "skipped"
    return "ignored"


# ---------- asking for reviews ----------

async def ask(org_id: str, contact_id: str, reason: str) -> str:
    """One friendly request for a review. Returns the request's status (or why it wasn't sent)."""
    from agentry.outbound import reach_contact
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode") or not cfg.get("review_link"):
            return "off" if status not in ("live", "approval_mode") else "no_link"
        if (await conn.execute(text("select 1 from app.review_requests where reason = :r"), {"r": reason})).first():
            return "already"
        recent = (await conn.execute(text("""select 1 from app.review_requests where contact_id = cast(:k as uuid)
            and created_at > now() - interval '90 days' and status in ('sent','recorded')"""), {"k": contact_id})).first()
        who = (await conn.execute(text("""select id as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
            from app.contacts where id = cast(:k as uuid)"""), {"k": contact_id})).mappings().first()
        unhappy = who and (await conn.execute(text("""select 1 from app.reviews where lower(author) = lower(:n) and rating <= 3"""),
                                              {"n": who["contact_name"] or "~"})).first()

        async def note(st: str, why: str | None = None, channel: str | None = None) -> str:
            await conn.execute(text("""insert into app.review_requests (org_id, contact_id, reason, channel, status, note)
                values (:o, cast(:k as uuid), :r, :c, :s, :n) on conflict (org_id, reason) do nothing"""),
                {"o": org_id, "k": contact_id, "r": reason, "c": channel, "s": st, "n": why})
            return st
        if not who or recent or unhappy:
            return await note("skipped", "asked in the last 90 days" if recent else ("their last review was unhappy" if unhappy else "no contact"))
        d = await governance.decide(conn, org_id, "reviews.ask")
        if d.mode != "send":
            return await note("held", d.reason or "watching only")
        biz = await _business(conn, org_id)
        name = (who["contact_name"] or "there").split()[0]
        body = (f"Hi {name}, thank you for choosing {biz['name']}! If you have a minute, a quick review really helps others find us: "
                f"{cfg['review_link']}")
        r = await reach_contact(conn, org_id, dict(who), body, agent="reviews", subject=f"How was your visit to {biz['name']}?",
                                email_ref=f"review:{contact_id}")
        if r["status"] == "no_channel":
            return await note("skipped", "no WhatsApp, Telegram or email to reach them")
        return await note(r["status"], None, r.get("channel"))


@DBOS.step()
async def ask_step(org_id: str, contact_id: str, reason: str) -> str:
    return await ask(org_id, contact_id, reason)


@DBOS.step()
async def ask_plan(org_id: str, kind: str, ref: str) -> dict:
    """Who to ask and when, for a visit (booking id) or a paid invoice (invoice id)."""
    async with tenant_session(org_id) as conn:
        status, cfg = await settings_of(conn)
        if status not in ("live", "approval_mode") or not cfg[f"ask_after_{kind}"]:
            return {}
        table = "bookings" if kind == "visit" else "invoices"
        k = (await conn.execute(text(f"select contact_id::text from app.{table} where id = cast(:i as uuid)"), {"i": ref})).scalar_one_or_none()
    return {"contact_id": k, "at": (datetime.now(UTC) + timedelta(hours=cfg["ask_delay_hours"])).isoformat()} if k else {}


async def _ask_later(org_id: str, kind: str, ref: str) -> None:
    plan = await ask_plan(org_id, kind, ref)
    if not plan:
        return
    target = datetime.fromisoformat(plan["at"])
    while (left := (target - datetime.now(UTC)).total_seconds()) > 1:
        await DBOS.sleep_async(min(left, 86400))
    await ask_step(org_id, plan["contact_id"], f"{'booking' if kind == 'visit' else 'invoice'}:{ref}")


@on("booking.showed")
@DBOS.workflow()
async def ask_after_visit(event: dict) -> None:
    await _ask_later(event["org_id"], "visit", event["payload"]["booking_id"])


@on("payment.received")
@DBOS.workflow()
async def ask_after_payment(event: dict) -> None:
    p = event["payload"]
    if p.get("status") == "paid" and p.get("invoice_id"):
        await _ask_later(event["org_id"], "payment", p["invoice_id"])


# ---------- reports and setup ----------

async def stats(conn: AsyncConnection, start: datetime, end: datetime) -> dict:
    r = (await conn.execute(text("""select count(*) as n, round(avg(rating)::numeric, 2) as avg,
            count(*) filter (where reply_status = 'posted') as replied, count(*) filter (where rating <= 2) as low
        from app.reviews where reviewed_at >= :s and reviewed_at < :e"""), {"s": start, "e": end})).mappings().one()
    themes = (await conn.execute(text("""select t, count(*) filter (where sentiment = 'negative' or sentiment = 'mixed') as bad,
            count(*) filter (where sentiment = 'positive') as good
        from app.reviews, unnest(topics) t where reviewed_at >= :s and reviewed_at < :e group by t order by count(*) desc limit 5"""),
        {"s": start, "e": end})).mappings().all()
    return {"count": r["n"], "average": float(r["avg"]) if r["avg"] is not None else None, "replied": r["replied"], "low": r["low"],
            "themes": [dict(t) for t in themes]}


async def monthly(org_id: str, month_start: datetime) -> dict:
    prev = (month_start - timedelta(days=1)).replace(day=1)
    nxt = (month_start + timedelta(days=32)).replace(day=1)
    async with tenant_session(org_id) as conn:
        now, before = await stats(conn, month_start, nxt), await stats(conn, prev, month_start)
    label = month_start.strftime("%B %Y")
    lines = [f"{now['count']} new review{'s' if now['count'] != 1 else ''} in {label}"
             + (f", average {now['average']:.1f}★" if now["average"] is not None else "")
             + (f" (was {before['average']:.1f}★)" if before["average"] is not None else "") + "."]
    if now["count"]:
        lines.append(f"Replied to {now['replied']} of {now['count']}." + (f" {now['low']} low rating{'s' if now['low'] != 1 else ''}." if now["low"] else ""))
    praise = [t["t"] for t in now["themes"] if t["good"] > t["bad"]][:2]
    issues = [t["t"] for t in now["themes"] if t["bad"] >= t["good"] and t["bad"]][:2]
    if praise:
        lines.append("People liked: " + ", ".join(praise) + ".")
    if issues:
        lines.append("Complaints about: " + ", ".join(issues) + ".")
    return {"month": month_start.date().isoformat()[:7], "title": f"Reviews for {label}", "body": "\n".join(lines), "count": now["count"],
            "average": now["average"]}


async def send_monthly(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with system_session() as conn:
        orgs = (await conn.execute(text("""select org_id from app.automation_instances where template_key = 'reviews'
            and status in ('live','approval_mode')"""))).scalars().all()
    n = 0
    for org_id in orgs:
        s = await monthly(org_id, month_start)
        async with tenant_session(org_id) as conn:
            if not (await conn.execute(text("select 1 from app.events where type = 'reviews.monthly' and payload->>'month' = :m"), {"m": s["month"]})).first():
                await emit(conn, org_id, "reviews.monthly", s)
                n += 1
    return n


@DBOS.step()
async def reviews_monthly_step() -> int:
    return await send_monthly()


@DBOS.workflow()
async def reviews_monthly(scheduled_time: datetime, context) -> None:
    await reviews_monthly_step()


async def ensure_watcher(conn: AsyncConnection, org_id: str) -> None:
    """The 'reviews' watcher every business with the agent has (pulls new reviews every 6 hours)."""
    await conn.execute(text("""insert into app.watchers (org_id, kind, name, every_minutes)
        select :o, 'reviews', 'Google reviews', 360 where not exists (select 1 from app.watchers where kind = 'reviews')"""), {"o": org_id})
