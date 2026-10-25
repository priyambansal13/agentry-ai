"""Load mock client data (mock-data/) into the organisations created by `pnpm seed:auth`.

Idempotent: re-running replaces each organisation's seeded rows. Synthetic events for the last 30 days are
generated with a fixed random seed and marked {"mock": true}, so dashboards have realistic numbers to show.
"""
import csv
import json
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.config import ROOT
from agentry.db import system_session, tenant_session
from agentry.knowledge import add_document
from agentry.metrics import rollup, sync_definitions
from agentry.packs import apply_pack

MOCK = ROOT / "mock-data"

ONBOARDING_STEPS = ["profile", "plan", "team", "connect", "import", "knowledge", "settings", "persona",
                    "compliance", "test", "go_live"]

ORGS = {
    "sharma-digital": {
        "status": "live", "industry_pack": "b2b-agency-in", "country": "IN", "timezone": "Asia/Kolkata",
        "currency": "INR", "website": "https://sharmadigital.example", "locations": ["New Delhi"],
        "automations": {"inbox_triage": "live", "invoice_follow_up": "approval_mode", "website_chat": "setup"},
        # events per day: type -> (mean per day, payload factory)
        "events": {"email.triaged": 38, "lead.created": 1.2, "message.sent": 9, "payment.received": 0.5},
        "payment_range": (8000, 110000),
    },
    "kaveri-industrial": {
        "status": "onboarding", "industry_pack": "b2b-distributor-in", "country": "IN", "timezone": "Asia/Kolkata",
        "currency": "INR", "website": "https://kaverisupplies.example", "locations": ["Coimbatore"],
        "automations": {"invoice_follow_up": "approval_mode"},
        "events": {"message.sent": 3, "payment.received": 0.25},
        "payment_range": (40000, 480000),
        "blocked": ("connect", "WhatsApp template awaiting Meta approval"),
    },
    "brightpath": {
        "status": "live", "industry_pack": "b2b-consulting-us", "country": "US", "timezone": "America/Chicago",
        "currency": "USD", "website": "https://brightpath.example", "locations": ["Austin, TX"],
        "automations": {"invoice_follow_up": "live", "inbox_triage": "live"},
        "events": {"email.triaged": 22, "message.sent": 4, "payment.received": 0.4, "lead.created": 0.5},
        "payment_range": (1200, 12750),
    },
    "agentry": {
        "status": "live", "industry_pack": "b2b-agency", "country": "IN", "timezone": "Asia/Kolkata",
        "currency": "INR", "website": "http://localhost:3200", "locations": ["Remote"],
        "automations": {"website_chat": "live"}, "events": {},
    },
    "smilecraft": {
        "status": "live", "industry_pack": "dental-clinic-in", "country": "IN", "timezone": "Asia/Kolkata",
        "currency": "INR", "website": "https://smilecraft.example", "locations": ["Kalyani Nagar", "Baner"],
        "automations": {"website_chat": "live", "ai_receptionist": "live", "lead_reactivation": "approval_mode",
                        "speed_to_lead": "live"},
        "events": {"call.completed": 11, "booking.created": 1.6, "lead.created": 3.2, "message.sent": 14},
    },
}


def _contacts(slug: str) -> list[dict]:
    if slug == "sharma-digital":
        rows = list(csv.DictReader((MOCK / "sharma-digital-sheet.csv").open()))
        seen, out = set(), []
        for r in rows:
            if r["Email"] not in seen:
                seen.add(r["Email"])
                out.append({"name": r["Contact"], "email": r["Email"], "phone": r["Phone"], "company": r["Company"],
                            "source": "google_sheets"})
        return out
    if slug == "kaveri-industrial":
        return [{"name": r["Contact Person"], "email": r["Email"], "phone": r["Mobile"] or None,
                 "company": r["Ledger Name"], "source": "tally"}
                for r in csv.DictReader((MOCK / "kaveri-tally-parties.csv").open())]
    if slug == "brightpath":
        seen, out = set(), []
        for r in csv.DictReader((MOCK / "brightpath-qbo-open-invoices.csv").open()):
            if r["Customer"] not in seen:
                seen.add(r["Customer"])
                out.append({"name": None, "email": r["Customer email"], "phone": None, "company": r["Customer"],
                            "source": "quickbooks"})
        return out
    if slug == "smilecraft":
        out = [{"name": r["name"], "email": r["email"] or None, "phone": r["phone"], "company": None,
                "source": "old_leads_csv"} for r in csv.DictReader((MOCK / "boring-machine" / "old-leads.csv").open())]
        for line in (MOCK / "boring-machine" / "form-leads.jsonl").read_text().splitlines():
            f = json.loads(line)
            out.append({"name": f["name"], "email": f.get("email"), "phone": f["phone"], "company": None,
                        "source": f["source"]})
        return out
    return []


def _synthetic_events(slug: str, cfg: dict, rng: random.Random) -> list[tuple[str, dict, datetime]]:
    now = datetime.now(UTC)
    out = []
    for day in range(64, -1, -1):  # two full 30-day periods, so period-over-period deltas are honest
        growth = 1 + (64 - day) / 64 * 0.25  # gentle upward trend so period-over-period deltas look real
        for etype, mean in cfg["events"].items():
            n = sum(1 for _ in range(int(mean * 3 * growth)) if rng.random() < 1 / 3)
            for _ in range(n):
                at = now - timedelta(days=day, hours=rng.uniform(0, 23.9))
                if at > now:
                    continue
                payload: dict = {"mock": True}
                if etype == "payment.received":
                    lo, hi = cfg["payment_range"]
                    payload |= {"amount": round(rng.uniform(lo, hi), -2), "currency": cfg["currency"]}
                if etype == "booking.created":
                    payload |= {"source": rng.choice(["website_chat", "ai_receptionist", "lead_reactivation",
                                                      "speed_to_lead"])}
                out.append((etype, payload, at))
    return out


AGENTRY_FAQS = [
    {"q": "What is Agentry?", "a": "Agentry builds and runs AI agents for businesses: an AI receptionist, speed-to-lead calls, a website chat agent, lead reactivation, personal cold email, inbox triage, invoice follow-up and content repurposing. We set them up and run them; you see the results in one dashboard."},
    {"q": "How much does it cost?", "a": "Three options: a setup fee plus a monthly retainer, pay only per booked appointment (10 to 20 percent of what a customer is worth to you), or start small with one agent. Exact prices depend on the agents and volume; we quote after a short discovery call."},
    {"q": "How long does setup take?", "a": "Most businesses are live within 7 days. We build a free demo with your business name first."},
    {"q": "Do customers know they are talking to AI?", "a": "Yes. Our agents always introduce themselves as AI assistants."},
    {"q": "Does the AI send messages without approval?", "a": "Not at first. Every agent starts in approval mode where you approve each draft."},
    {"q": "Which tools do you integrate with?", "a": "Gmail and Outlook, WhatsApp, Google Sheets, Tally, Zoho, QuickBooks, Xero, Razorpay, Stripe, Google Calendar and most CRMs."},
]

PACK_FOR = {"sharma-digital": "b2b-agency", "kaveri-industrial": "b2b-agency", "brightpath": "b2b-agency",
            "smilecraft": "dental-clinic", "agentry": "b2b-agency"}
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def _apply_pack(slug: str, org_id: str, cfg: dict) -> None:
    business = {"sharma-digital": "Sharma Digital Agency", "kaveri-industrial": "Kaveri Industrial Supplies",
                "brightpath": "Brightpath Consulting", "smilecraft": "SmileCraft Dental Clinic", "agentry": "Agentry"}[slug]
    if slug == "agentry":
        await apply_pack(org_id, "b2b-agency", business=business, currency="INR", faqs=AGENTRY_FAQS, persona={
            "greeting": "Hi! I'm Ava, Agentry's AI assistant. Want to see what an AI agent could do for your business?"})
        return
    if slug != "smilecraft":
        await apply_pack(org_id, PACK_FOR[slug], business=business, currency=cfg["currency"])
        return
    t = json.loads((MOCK / "boring-machine" / "tenant.json").read_text())
    open_, close = t["hours"]["MON-SAT"].split("-")
    hours = {d: [[open_, close]] for d in DAY_KEYS[:6]}
    await apply_pack(
        org_id, "dental-clinic", business=business, currency="INR",
        persona={"name": t["persona"]["name"], "tone": t["persona"]["tone"], "signoff": "Team SmileCraft"},
        services=[{"key": s["key"], "name": s["name"], "minutes": s["minutes"], "price": s["price"]} for s in t["services"]],
        staff=[{"name": st["name"], "email": st["calendar"].split(":", 1)[1], "services": st["services"], "hours": hours}
               for st in t["staff"]],
        faqs=t["faqs"], extra_profile={"holidays": t["holidays"], "phone": t["phone"], "city": t["city"]},
    )
    aliases = {"cleaning": "teeth cleaning", "rct": "root canal treatment", "consult": "check-up, consultation",
               "aligners": "clear aligners, braces", "implant": "dental implant"}
    services = "\n".join(f"- {s['name']} ({aliases.get(s['key'], s['key'])}): {s['minutes']} minutes, "
                         + (f"Rs {s['price']}" if s["price"] else "free") for s in t["services"])
    await add_document(org_id, source_type="text", title="Clinic information", source_ref="seed:clinic-info", content=(
        f"{business}, {t['city']}. Phone {t['phone']}.\n\nOpen Monday to Saturday {open_} to {close}; closed on Sundays."
        f"\n\nServices and prices:\n{services}\n\nDoctors: " + ", ".join(st["name"] for st in t["staff"]) + "."))


INVOICE_FILES = {"sharma-digital": "sharma-digital-sheet.csv", "kaveri-industrial": "kaveri-tally-bills-receivable.csv",
                 "brightpath": "brightpath-qbo-open-invoices.csv"}


async def _phase2(slug: str, org_id: str) -> str:
    """Invoices (each client's own export format), old leads, lead forms. Reminder sequences start when the worker runs."""
    from agentry.automations.lead_reactivation import import_old_leads
    from agentry.automations.speed_to_lead import create_source
    from agentry.invoices import (
        enroll_open,
        map_columns_heuristic,
        normalise_rows,
        parse_file,
        upsert_invoices,
    )
    from agentry.leads import backfill_identity, dedupe
    async with tenant_session(org_id) as conn:
        await backfill_identity(conn)
        if slug in INVOICE_FILES:
            rows = parse_file((MOCK / INVOICE_FILES[slug]).read_bytes(), INVOICE_FILES[slug])
            clean, _ = normalise_rows(rows, map_columns_heuristic(list(rows[0])), ORGS[slug]["currency"])
            res = await upsert_invoices(conn, org_id, clean, source=INVOICE_FILES[slug].split("-")[0])
            enrolled = await enroll_open(conn, org_id)
            return f"invoices={res['created']} reminders={enrolled}"
        if slug == "smilecraft":
            rows = parse_file((MOCK / "boring-machine" / "old-leads.csv").read_bytes(), "old-leads.csv")
            stats = await import_old_leads(conn, org_id, rows)
            merged = await dedupe(conn)
            await create_source(conn, org_id, "Website form")
            return f"old_leads={stats['leads_created']} merged={merged} lead_form=1"
    return ""


PLANS = {
    "sharma-digital": {"currency": "INR", "setup_fee": 15000, "retainer": 4999, "tax_rate": 0.18,
                       "revenue_share": {"basis": "overdue_only", "rate": 0.015, "cap": 25000, "window_days": 30}},
    "kaveri-industrial": {"currency": "INR", "tax_rate": 0.18,
                          "revenue_share": {"basis": "overdue_only", "rate": 0.04, "window_days": 45, "strong_only": True}},
    "brightpath": {"currency": "USD", "retainer": 199},
    "smilecraft": {"currency": "INR", "retainer": 7999, "included": {"messages": 500}, "overage": {"messages": 1},
                   "outcome_prices": [{"outcome": "appointment_booked", "price": 250}], "tax_rate": 0.18},
}


async def _billing(slug: str, org_id: str, events: list) -> str:
    """Pricing plan + last month's results as outcomes (from the synthetic history) + an issued statement."""
    from datetime import date

    from agentry import billing
    if slug not in PLANS:
        return ""
    plan = billing.PricingPlan(**PLANS[slug])
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.pricing_plans (org_id, currency, setup_fee, retainer, included, overage, outcome_prices,
            revenue_share, tax_rate, setup_billed) values (:o, :c, :sf, :r, cast(:i as jsonb), cast(:ov as jsonb), cast(:op as jsonb),
            cast(:rs as jsonb), :t, false)"""),
            {"o": org_id, "c": plan.currency, "sf": plan.setup_fee, "r": plan.retainer, "i": json.dumps(plan.included),
             "ov": json.dumps({k: str(v) for k, v in plan.overage.items()}),
             "op": json.dumps([json.loads(p.model_dump_json()) for p in plan.outcome_prices]),
             "rs": plan.revenue_share.model_dump_json(), "t": plan.tax_rate})
        for i, (etype, payload, at) in enumerate(events):
            if etype == "booking.created":
                await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, automation_key, evidence)
                    values (:o, 'appointment_booked', :r, :at, 1500, :a, cast(:e as jsonb))"""),
                    {"o": org_id, "r": f"mock-booking-{i}", "at": at, "a": payload.get("source"),
                     "e": json.dumps({"mock": True, "service": "Consultation", "source": payload.get("source")})})
            elif etype == "payment.received" and plan.revenue_share.rate:
                await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, strength, automation_key, evidence)
                    values (:o, 'amount_recovered', :r, :at, :v, 'strong', 'invoice_follow_up', cast(:e as jsonb))"""),
                    {"o": org_id, "r": f"mock-payment-{i}", "at": at, "v": payload["amount"],
                     "e": json.dumps({"mock": True, "invoice": f"MOCK-{i}", "reminders": [{"step": 0, "channel": "email"}]})})
        today = date.today()
        last_start, last_end = billing.month_bounds(today.replace(day=1) - timedelta(days=1))
        sid = await billing.generate_statement(conn, org_id, last_start, last_end)
        await billing.issue(conn, org_id, sid)
        total = (await conn.execute(text("select total, currency from app.statements where id = :s"), {"s": sid})).one()
    return f"plan=yes statement_{last_start:%b}={total.currency} {total.total:,.2f}"


async def seed() -> None:
    async with system_session() as conn:
        await sync_definitions(conn)
        orgs = {r.slug: r.id for r in (await conn.execute(text("select id, slug from auth.organization"))).all()}
    missing = [s for s in ORGS if s not in orgs]
    if missing:
        raise SystemExit(f"organisations missing: {missing}. Run `pnpm --filter @agentry/dashboard seed:auth` first.")

    for slug, cfg in ORGS.items():
        org_id = orgs[slug]
        rng = random.Random(slug)
        async with tenant_session(org_id) as conn:  # row-level security also guards the seed
            await conn.execute(text("update app.contacts set merged_into = null"))
            for table in ("statement_lines", "statements", "outcomes", "pricing_plans", "approvals", "conversations", "bookings", "sequence_enrollments", "campaigns", "sequences", "payments",
                          "invoices", "lead_sources", "leads", "consents", "suppressions", "staff", "services", "kb_documents",
                          "events", "contacts", "automation_instances", "locations", "onboarding_progress",
                          "metrics_daily", "org_settings"):
                await conn.execute(text(f"delete from app.{table}"))
            await conn.execute(
                text("""insert into app.org_settings (org_id, status, industry_pack, country, timezone, currency, website)
                        values (:o, :status, :pack, :country, :tz, :cur, :web)"""),
                {"o": org_id, "status": cfg["status"], "pack": cfg["industry_pack"], "country": cfg["country"],
                 "tz": cfg["timezone"], "cur": cfg["currency"], "web": cfg["website"]},
            )
            for name in cfg["locations"]:
                await conn.execute(text("insert into app.locations (org_id, name) values (:o, :n)"), {"o": org_id, "n": name})
            for key, status in cfg["automations"].items():
                await conn.execute(
                    text("insert into app.automation_instances (org_id, template_key, status) values (:o, :k, :s)"),
                    {"o": org_id, "k": key, "s": status},
                )
            for c in _contacts(slug):
                await conn.execute(
                    text("""insert into app.contacts (org_id, name, email, phone, company, source, attributes)
                            values (:o, :name, :email, :phone, :company, :source, '{"mock": true}')"""),
                    {"o": org_id, **c},
                )
            blocked = cfg.get("blocked")
            for i, step in enumerate(ONBOARDING_STEPS):
                if cfg["status"] == "live":
                    st, blocker = "done", None
                elif blocked and step == blocked[0]:
                    st, blocker = "blocked", blocked[1]
                else:
                    st, blocker = ("done" if i < ONBOARDING_STEPS.index(blocked[0] if blocked else "go_live") else "todo"), None
                await conn.execute(
                    text("""insert into app.onboarding_progress (org_id, step_key, status, done_by, blocker)
                            values (:o, :k, :s, :by, :b)"""),
                    {"o": org_id, "k": step, "s": st, "by": "agentry" if st == "done" else None, "b": blocker},
                )
            events = _synthetic_events(slug, cfg, rng)
            for etype, payload, at in events:
                await conn.execute(
                    text("""insert into app.events (org_id, type, payload, occurred_at, dispatched_at)
                            values (:o, :t, cast(:p as jsonb), :at, now())"""),  # history: never re-dispatched
                    {"o": org_id, "t": etype, "p": json.dumps(payload), "at": at},
                )
        await _apply_pack(slug, org_id, cfg)
        extra = await _phase2(slug, org_id)
        print(f"{slug:18} {extra} {await _billing(slug, org_id, events)}")
        print(f"{slug:18} contacts={len(_contacts(slug)):3}  automations={len(cfg['automations'])}  events={len(events)}")

    async with system_session() as conn:
        n = await rollup(conn)
    print(f"metric rollups: {n} rows")
