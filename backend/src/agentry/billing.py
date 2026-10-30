"""Billing (docs/PRICING.md): what each client owes, and the evidence for every rupee.

Outcomes are recorded when they happen (a booking, a recovered payment) together with the facts that make them
billable or not. A monthly statement then adds the setup fee (once), the retainer, usage beyond what's included, the
pay-per-result lines and capped commission, plus GST for Indian clients. Statements are issued with a 7-day dispute
window; disputed lines are resolved by Agentry staff before the statement is finalised.
"""
import json
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import settings
from agentry.connectors.http import client

DISPUTE_DAYS = 7
CLOCK_SKEW = timedelta(seconds=30)
SOURCE_AUTOMATION = {"web_chat": "website_chat", "whatsapp": "whatsapp_assistant", "lead_reactivation": "lead_reactivation",
                     "speed_to_lead": "speed_to_lead", "voice": "ai_receptionist"}
USAGE_EVENTS = {"messages": "message.sent", "emails_triaged": "email.triaged"}
# call minutes: each real (non-test) call rounded up to the next whole minute, like telephony providers bill
VOICE_MINUTES_SQL = """select coalesce(sum(ceil((metadata->>'duration_seconds')::numeric / 60)), 0)::int from app.conversations
    where channel = 'voice' and metadata ? 'duration_seconds' and coalesce(metadata->>'test', 'false') <> 'true'
    and created_at >= :a and created_at < :b"""


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class OutcomePrice(BaseModel):
    outcome: Literal["appointment_booked"]
    price: Decimal | None = Field(None, ge=0)
    pct_of_customer_value: float | None = Field(None, gt=0, le=1)
    min: Decimal | None = Field(None, ge=0)


class RevenueShare(BaseModel):
    basis: Literal["none", "overdue_only", "all_recovered"] = "none"
    rate: float = Field(0, ge=0, le=0.5)
    cap: Decimal | None = Field(None, ge=0)
    window_days: int = Field(30, ge=1, le=120)
    strong_only: bool = False


class PricingPlan(BaseModel):
    currency: Literal["INR", "USD", "EUR", "GBP", "AED"] = "INR"
    setup_fee: Decimal = Field(Decimal(0), ge=0)
    retainer: Decimal = Field(Decimal(0), ge=0)
    included: dict[Literal["messages", "emails_triaged", "voice_minutes", "content_videos"], int] = Field(default_factory=dict)
    overage: dict[Literal["messages", "emails_triaged", "voice_minutes", "content_videos"], Decimal] = Field(default_factory=dict)
    outcome_prices: list[OutcomePrice] = Field(default_factory=list)
    revenue_share: RevenueShare = Field(default_factory=RevenueShare)
    tax_rate: float = Field(0, ge=0, le=0.3)
    pilot_until: date | None = None


async def save_plan(conn: AsyncConnection, org_id: str, plan: PricingPlan) -> None:
    await conn.execute(text("""insert into app.pricing_plans (org_id, currency, setup_fee, retainer, included, overage, outcome_prices,
        revenue_share, tax_rate, pilot_until) values (:o, :c, :sf, :r, cast(:inc as jsonb), cast(:ov as jsonb), cast(:op as jsonb),
        cast(:rs as jsonb), :t, :p)
        on conflict (org_id) do update set currency = excluded.currency, setup_fee = excluded.setup_fee, retainer = excluded.retainer,
        included = excluded.included, overage = excluded.overage, outcome_prices = excluded.outcome_prices,
        revenue_share = excluded.revenue_share, tax_rate = excluded.tax_rate, pilot_until = excluded.pilot_until, updated_at = now()"""),
        {"o": org_id, "c": plan.currency, "sf": plan.setup_fee, "r": plan.retainer,
         "inc": json.dumps(plan.included), "ov": json.dumps({k: str(v) for k, v in plan.overage.items()}),
         "op": json.dumps([json.loads(op.model_dump_json()) for op in plan.outcome_prices]),
         "rs": plan.revenue_share.model_dump_json(), "t": plan.tax_rate, "p": plan.pilot_until})


# ---------- recording outcomes ----------

async def record_booking(conn: AsyncConnection, org_id: str, payload: dict) -> str | None:
    if payload.get("source") in (None, "test"):
        return None
    row = (await conn.execute(text("""select b.id, b.starts_at, b.status, b.conversation_id, b.contact_id, s.name as service,
        s.price, (select profile->>'customer_value' from app.org_settings) as customer_value
        from app.bookings b join app.services s on s.id = b.service_id where b.id = cast(:b as uuid)"""),
        {"b": payload["booking_id"]})).mappings().first()
    if not row:
        return None
    value = row["price"] if row["price"] and row["price"] > 0 else Decimal(row["customer_value"] or 0)
    return str((await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, automation_key, evidence)
        values (:o, 'appointment_booked', :ref, now(), :v, :a, cast(:e as jsonb)) on conflict (org_id, kind, source_ref) do nothing
        returning id"""), {"o": org_id, "ref": str(row["id"]), "v": value, "a": SOURCE_AUTOMATION.get(payload["source"], payload["source"]),
                           "e": json.dumps({"booking_id": str(row["id"]), "service": row["service"], "starts_at": row["starts_at"].isoformat(),
                                            "conversation_id": str(row["conversation_id"]) if row["conversation_id"] else None,
                                            "source": payload["source"]})})).scalar_one_or_none() or "") or None


async def record_recovery(conn: AsyncConnection, org_id: str, payload: dict) -> dict | None:
    """Was this payment recovered by Agentry? Applies the client's revenue-share rules and stores the verdict."""
    if not payload.get("invoice_id") or not payload.get("payment_id"):
        return None
    plan = PricingPlan(**(await _plan_row(conn) or {}))
    rs = plan.revenue_share
    inv = (await conn.execute(text("select number, due_on from app.invoices where id = cast(:i as uuid)"),
                               {"i": payload["invoice_id"]})).mappings().one()
    pay = (await conn.execute(text("select received_at, match from app.payments where id = cast(:p as uuid)"),
                              {"p": payload["payment_id"]})).mappings().one()
    paid_at = pay["received_at"]
    logs = (await conn.execute(text("""select st->>'at' as at, (st->>'step')::int as step, r->>'channel' as channel
        from app.sequence_enrollments e, jsonb_array_elements(e.log) st, jsonb_array_elements(st->'results') r
        where e.subject_type = 'invoice' and e.subject_id = cast(:i as uuid) and r->>'status' in ('sent','recorded')"""),
        {"i": payload["invoice_id"]})).mappings().all()
    # Reminder times come from the app's clock, payment times from the database's: allow for a little clock skew.
    reminders = sorted([dict(r) for r in logs if datetime.fromisoformat(r["at"]) <= paid_at + CLOCK_SKEW], key=lambda r: r["at"])
    strength = "strong" if pay["match"] == "strong" else "weak"
    reason = None
    if rs.basis == "none" or rs.rate == 0:
        reason = "no commission on this plan"
    elif rs.basis == "overdue_only" and paid_at.date() <= inv["due_on"]:
        reason = "paid before it was overdue"
    elif not reminders:
        reason = "no reminder had been delivered before payment"
    elif paid_at - datetime.fromisoformat(reminders[-1]["at"]) > timedelta(days=rs.window_days):
        reason = f"paid more than {rs.window_days} days after the last reminder"
    elif rs.strong_only and strength == "weak":
        reason = "payment matched by customer and amount only (plan counts strong matches only)"
    evidence = {"invoice": inv["number"], "invoice_id": payload["invoice_id"], "payment_id": payload["payment_id"],
                "reference": payload.get("reference"), "gateway": payload.get("gateway"), "due_on": inv["due_on"].isoformat(),
                "paid_at": paid_at.isoformat(), "days_overdue": (paid_at.date() - inv["due_on"]).days, "reminders": reminders}
    await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, strength, status,
        exclusion_reason, automation_key, evidence) values (:o, 'amount_recovered', :ref, :at, :v, :s, :st, :r, 'invoice_follow_up',
        cast(:e as jsonb)) on conflict (org_id, kind, source_ref) do nothing"""),
        {"o": org_id, "ref": payload["payment_id"], "at": paid_at, "v": money(payload["amount"]), "s": strength,
         "st": "excluded" if reason else "billable", "r": reason, "e": json.dumps(evidence)})
    return {"billable": reason is None, "reason": reason, "strength": strength}


async def cancel_booking_outcome(conn: AsyncConnection, booking_id: str) -> None:
    await conn.execute(text("""update app.outcomes set status = 'cancelled', exclusion_reason = 'appointment cancelled'
        where kind = 'appointment_booked' and source_ref = :b and statement_id is null"""), {"b": booking_id})


# ---------- statements ----------

async def _plan_row(conn: AsyncConnection) -> dict | None:
    row = (await conn.execute(text("select * from app.pricing_plans"))).mappings().first()
    if not row:
        return None
    return {k: row[k] for k in ("currency", "setup_fee", "retainer", "included", "overage", "outcome_prices", "revenue_share",
                                "tax_rate", "pilot_until")} | {"setup_billed": row["setup_billed"]}


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=monthrange(day.year, day.month)[1])


async def generate_statement(conn: AsyncConnection, org_id: str, period_start: date, period_end: date) -> str:
    """Build (or rebuild, while still a draft) the statement for a period. Returns its id."""
    raw = await _plan_row(conn)
    if raw is None:
        raise ValueError("this client has no pricing plan")
    plan = PricingPlan(**{k: v for k, v in raw.items() if k != "setup_billed"})
    existing = (await conn.execute(text("select id, status from app.statements where period_start = :s"), {"s": period_start})).first()
    if existing and existing.status != "draft":
        return str(existing.id)
    if existing:
        sid = str(existing.id)
        await conn.execute(text("delete from app.statement_lines where statement_id = :s"), {"s": sid})
        await conn.execute(text("update app.outcomes set statement_id = null where statement_id = :s"), {"s": sid})
    else:
        number = f"AGT-{period_start:%Y%m}-{(await conn.execute(text("select nextval('app.statement_number_seq')"))).scalar_one()}"
        sid = str((await conn.execute(text("""insert into app.statements (org_id, number, period_start, period_end, currency)
            values (:o, :n, :s, :e, :c) returning id"""), {"o": org_id, "n": number, "s": period_start, "e": period_end,
                                                           "c": plan.currency})).scalar_one())
    start_ts = datetime(period_start.year, period_start.month, period_start.day, tzinfo=UTC)
    end_ts = datetime(period_end.year, period_end.month, period_end.day, tzinfo=UTC) + timedelta(days=1)
    lines: list[dict] = []
    in_pilot = plan.pilot_until is not None and period_end <= plan.pilot_until

    if plan.setup_fee > 0 and not raw["setup_billed"]:
        lines.append({"kind": "setup", "description": "One-time setup", "quantity": 1, "unit_price": plan.setup_fee})
    if plan.retainer > 0:
        lines.append({"kind": "retainer", "description": f"Monthly retainer, {period_start:%B %Y}" + (" (pilot: no charge)" if in_pilot else ""),
                      "quantity": 1, "unit_price": Decimal(0) if in_pilot else plan.retainer})
    for key in (*USAGE_EVENTS, "voice_minutes", "content_videos"):
        if key == "voice_minutes":
            used = (await conn.execute(text(VOICE_MINUTES_SQL), {"a": start_ts, "b": end_ts})).scalar_one()
        elif key == "content_videos":  # recordings turned into posts (the demo sample doesn't count)
            from agentry.automations.content.results import VIDEOS_SQL
            used = (await conn.execute(text(VIDEOS_SQL), {"a": start_ts, "b": end_ts})).scalar_one()
        else:
            used = (await conn.execute(text("""select count(*) from app.events where type = :t and occurred_at >= :a and occurred_at < :b
                and coalesce(payload->>'mock', 'false') <> 'true'"""), {"t": USAGE_EVENTS[key], "a": start_ts, "b": end_ts})).scalar_one()
        extra = max(0, used - plan.included.get(key, 0)) if key in plan.overage else 0
        if extra:
            lines.append({"kind": "overage", "description": f"{key.replace('_', ' ').capitalize()} beyond the {plan.included.get(key, 0):,} included ({used:,} used)",
                          "quantity": extra, "unit_price": plan.overage[key]})

    outcomes = (await conn.execute(text("""select id, kind, value, evidence from app.outcomes where status = 'billable'
        and statement_id is null and occurred_at >= :a and occurred_at < :b order by occurred_at"""),
        {"a": start_ts, "b": end_ts})).mappings().all()
    bookings = [o for o in outcomes if o["kind"] == "appointment_booked"]
    price = next((p for p in plan.outcome_prices if p.outcome == "appointment_booked"), None)
    if bookings and price:
        if price.price is not None:
            lines.append({"kind": "outcome", "description": "Appointments booked by your agents", "quantity": len(bookings),
                          "unit_price": price.price, "evidence": [str(o["id"]) for o in bookings]})
        else:
            for o in bookings:  # % of what this appointment is worth, with a floor
                fee = max(money(Decimal(o["value"]) * Decimal(str(price.pct_of_customer_value))), price.min or Decimal(0))
                lines.append({"kind": "outcome", "description": f"Appointment booked: {o['evidence'].get('service')}",
                              "quantity": 1, "unit_price": fee, "evidence": [str(o["id"])]})
    recovered = [o for o in outcomes if o["kind"] == "amount_recovered"]
    if recovered and plan.revenue_share.rate > 0:
        total = sum(Decimal(o["value"]) for o in recovered)
        fee = money(total * Decimal(str(plan.revenue_share.rate)))
        capped = min(fee, plan.revenue_share.cap) if plan.revenue_share.cap is not None else fee
        lines.append({"kind": "commission", "description": f"{plan.revenue_share.rate:.1%} of {_fmt(total, plan.currency)} recovered "
                      f"on {len(recovered)} overdue invoice{'s' if len(recovered) != 1 else ''}" + (" (monthly cap applied)" if capped < fee else ""),
                      "quantity": 1, "unit_price": capped, "evidence": [str(o["id"]) for o in recovered]})

    for i, ln in enumerate(lines):
        await conn.execute(text("""insert into app.statement_lines (org_id, statement_id, position, kind, description, quantity, unit_price,
            amount, evidence) values (:o, :s, :p, :k, :d, :q, :u, :a, cast(:e as jsonb))"""),
            {"o": org_id, "s": sid, "p": i, "k": ln["kind"], "d": ln["description"], "q": ln["quantity"], "u": money(ln["unit_price"]),
             "a": money(Decimal(ln["quantity"]) * money(ln["unit_price"])), "e": json.dumps(ln.get("evidence", []))})
    await conn.execute(text("update app.outcomes set statement_id = :s where id = any(cast(:ids as uuid[]))"),
                       {"s": sid, "ids": [str(o["id"]) for o in outcomes]})
    await _totals(conn, sid, plan.tax_rate)
    await conn.execute(text("update app.statements set results = cast(:r as jsonb) where id = :s"),
                       {"s": sid, "r": json.dumps(await results_summary(conn, start_ts, end_ts, plan.currency), default=str)})
    return sid


async def _totals(conn: AsyncConnection, sid: str, tax_rate: float) -> None:
    sub = (await conn.execute(text("""select coalesce(sum(amount), 0) from app.statement_lines where statement_id = :s
        and not (disputed and coalesce(dispute_resolution, '') not in ('rejected', 'partial'))"""), {"s": sid})).scalar_one()
    tax = money(Decimal(sub) * Decimal(str(tax_rate)))
    await conn.execute(text("update app.statements set subtotal = :s, tax = :t, total = :tot where id = :id"),
                       {"s": money(sub), "t": tax, "tot": money(sub) + tax, "id": sid})


async def results_summary(conn: AsyncConnection, start: datetime, end: datetime, currency: str) -> dict:
    """What the agents delivered in the period (for the monthly results report and the ROI multiple)."""
    o = dict((await conn.execute(text("""select kind, json_build_object('n', count(*), 'value', coalesce(sum(value), 0))
        from app.outcomes where status = 'billable' and occurred_at >= :a and occurred_at < :b group by kind"""),
        {"a": start, "b": end})).all())
    usage = {k: (await conn.execute(text("""select count(*) from app.events where type = :t and occurred_at >= :a and occurred_at < :b
        and coalesce(payload->>'mock', 'false') <> 'true'"""), {"t": ev, "a": start, "b": end})).scalar_one() for k, ev in USAGE_EVENTS.items()}
    booked, recovered = o.get("appointment_booked", {"n": 0, "value": 0}), o.get("amount_recovered", {"n": 0, "value": 0})
    return {"appointments": booked["n"], "appointments_value": float(booked["value"]), "recovered": float(recovered["value"]),
            "invoices_recovered": recovered["n"], **usage, "currency": currency}


async def month_report(conn: AsyncConnection, start: date, end: date) -> dict:
    """The monthly results report (portal Reports page and the emailed report): what the agents delivered, its value,
    what Agentry cost that month and the ROI multiple."""
    currency = (await conn.execute(text("select currency from app.pricing_plans"))).scalar_one_or_none() or \
        (await conn.execute(text("select currency from app.org_settings"))).scalar_one()
    res = await results_summary(conn, datetime(start.year, start.month, start.day, tzinfo=UTC),
                                datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1), currency)
    fee = (await conn.execute(text("select total from app.statements where period_start = :s and status <> 'void'"),
                              {"s": start})).scalar_one_or_none()
    value = res["appointments_value"] + res["recovered"]
    from agentry.automations.content.results import summary as content_summary
    content = await content_summary(conn, datetime(start.year, start.month, start.day, tzinfo=UTC),
                                    datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1))
    return {"month": f"{start:%Y-%m}", **res, "content": content, "value_delivered": value, "fee": float(fee) if fee is not None else None,
            "roi_multiple": round(value / float(fee), 1) if fee else None}


def _fmt(v: Decimal, currency: str) -> str:
    return f"₹{v:,.0f}" if currency == "INR" else f"{currency} {v:,.2f}"


async def issue(conn: AsyncConnection, org_id: str, sid: str) -> dict:
    st = (await conn.execute(text("select * from app.statements where id = :s"), {"s": sid})).mappings().one()
    if st["status"] != "draft":
        raise ValueError(f"statement is already {st['status']}")
    link = await _payment_link(st, org_id) if st["total"] > 0 else None
    await conn.execute(text("""update app.statements set status = 'issued', issued_at = now(),
        dispute_until = now() + make_interval(days => :d), payment_link = :l where id = :s"""), {"d": DISPUTE_DAYS, "l": link, "s": sid})
    if (await conn.execute(text("select 1 from app.statement_lines where statement_id = :s and kind = 'setup'"), {"s": sid})).first():
        await conn.execute(text("update app.pricing_plans set setup_billed = true"))
    return {"payment_link": link}


async def dispute(conn: AsyncConnection, line_id: str, reason: str) -> None:
    row = (await conn.execute(text("""select s.status, s.dispute_until from app.statement_lines l join app.statements s on s.id = l.statement_id
        where l.id = cast(:l as uuid)"""), {"l": line_id})).first()
    if not row:
        raise ValueError("line not found")
    if row.status != "issued" or row.dispute_until < datetime.now(UTC):
        raise ValueError("this statement can no longer be disputed")
    await conn.execute(text("update app.statement_lines set disputed = true, dispute_reason = :r, dispute_resolution = null where id = cast(:l as uuid)"),
                       {"r": reason, "l": line_id})


async def resolve(conn: AsyncConnection, line_id: str, accept: bool, *, credit: Decimal | None = None, note: str | None = None,
                  exclude_outcomes: list[str] | None = None) -> None:
    """Staff decision on a disputed line:
    accepted = removed from the bill (all its results excluded); rejected = stays;
    partial (a credit amount) = the line stays, a credit line is added, and only the results named are excluded."""
    line = (await conn.execute(text("""select statement_id, amount, evidence, description from app.statement_lines
        where id = cast(:l as uuid) and disputed and dispute_resolution is null"""), {"l": line_id})).mappings().first()
    if not line:
        raise ValueError("this line has no open dispute")
    resolution = "partial" if credit is not None else ("accepted" if accept else "rejected")
    if credit is not None:
        credit = money(credit)
        if not (Decimal(0) < credit <= Decimal(line["amount"])):
            raise ValueError(f"the credit must be more than 0 and at most {line['amount']}")
        unknown = set(exclude_outcomes or []) - {str(x) for x in line["evidence"]}
        if unknown:
            raise ValueError("you can only exclude results that are on this line")
        pos = (await conn.execute(text("select coalesce(max(position), 0) + 1 from app.statement_lines where statement_id = :s"),
                                  {"s": line["statement_id"]})).scalar_one()
        await conn.execute(text("""insert into app.statement_lines (org_id, statement_id, position, kind, description, quantity,
            unit_price, amount, evidence, credit_for) select org_id, statement_id, :p, 'credit', :d, 1, :a, :a, cast(:e as jsonb),
            cast(:l as uuid) from app.statement_lines where id = cast(:l as uuid)"""),
            {"p": pos, "d": f"Credit: {note.strip() if note and note.strip() else line['description']}", "a": -credit,
             "e": json.dumps(exclude_outcomes or []), "l": line_id})
    await conn.execute(text("update app.statement_lines set dispute_resolution = :r where id = cast(:l as uuid)"),
                       {"r": resolution, "l": line_id})
    excluded = [str(x) for x in line["evidence"]] if resolution == "accepted" else (exclude_outcomes or [])
    if excluded:
        await conn.execute(text("""update app.outcomes set status = 'excluded', exclusion_reason = :why
            where id = any(cast(:ids as uuid[]))"""),
            {"ids": excluded, "why": "disputed and accepted" if resolution == "accepted" else "disputed: credited"})
    rate = (await conn.execute(text("select tax_rate from app.pricing_plans"))).scalar_one()
    await _totals(conn, str(line["statement_id"]), float(rate))


async def finalize_due(conn: AsyncConnection) -> int:
    """Issued statements past their dispute window with no open disputes become final."""
    return (await conn.execute(text("""update app.statements s set status = 'finalized', finalized_at = now()
        where status = 'issued' and dispute_until < now() and not exists (select 1 from app.statement_lines l
          where l.statement_id = s.id and l.disputed and l.dispute_resolution is null)"""))).rowcount or 0


async def mark_paid(conn: AsyncConnection, sid: str, reference: str) -> None:
    await conn.execute(text("update app.statements set status = 'paid', paid_at = now(), payment_ref = :r where id = cast(:s as uuid)"),
                       {"r": reference, "s": sid})


async def _payment_link(st: dict, org_id: str) -> str | None:
    """Agentry's own gateway: Razorpay payment link for INR, Stripe Checkout for other currencies."""
    amount = int(Decimal(st["total"]) * 100)
    notes = {"statement_id": str(st["id"]), "org_id": org_id, "statement": st["number"]}
    async with client() as c:
        if st["currency"] == "INR" and settings.billing_razorpay_key_id:
            r = await c.post("https://api.razorpay.com/v1/payment_links",
                             auth=(settings.billing_razorpay_key_id, settings.billing_razorpay_key_secret or ""),
                             json={"amount": amount, "currency": "INR", "description": f"{settings.company_name} statement {st['number']}",
                                   "reference_id": st["number"], "notes": notes})
            return r.json().get("short_url") if r.status_code < 300 else None
        if st["currency"] != "INR" and settings.billing_stripe_secret_key:
            r = await c.post("https://api.stripe.com/v1/checkout/sessions", auth=(settings.billing_stripe_secret_key, ""), data={
                "mode": "payment", "success_url": f"{settings.dashboard_url}/billing?paid=1", "cancel_url": f"{settings.dashboard_url}/billing",
                "line_items[0][quantity]": 1, "line_items[0][price_data][currency]": st["currency"].lower(),
                "line_items[0][price_data][unit_amount]": amount,
                "line_items[0][price_data][product_data][name]": f"{settings.company_name} statement {st['number']}",
                **{f"metadata[{k}]": v for k, v in notes.items()}, **{f"payment_intent_data[metadata][{k}]": v for k, v in notes.items()}})
            return r.json().get("url") if r.status_code < 300 else None
    return None


async def margin(conn: AsyncConnection, start: datetime, end: datetime) -> dict:
    """Cost to serve vs revenue, for Agentry HQ (costs: model calls + WhatsApp templates + call minutes; rough, in INR)."""
    llm_usd = (await conn.execute(text("select coalesce(sum(cost_usd), 0) from app.llm_calls where at >= :a and at < :b"),
                                  {"a": start, "b": end})).scalar_one()
    templates = (await conn.execute(text("""select count(*) from app.messages where created_at >= :a and created_at < :b
        and metadata ? 'template'"""), {"a": start, "b": end})).scalar_one()
    rows = (await conn.execute(text("""select currency, coalesce(sum(subtotal), 0) from app.statements where period_start >= cast(:a as date)
        and period_start < cast(:b as date) and status <> 'void' group by currency"""), {"a": start, "b": end})).all()
    revenue_inr = sum(float(v) * settings.fx_to_inr.get(c, 1) for c, v in rows)
    # every call costs speech and telephony, test calls included
    seconds = (await conn.execute(text("""select coalesce(sum((metadata->>'duration_seconds')::numeric), 0) from app.conversations
        where channel = 'voice' and metadata ? 'duration_seconds' and created_at >= :a and created_at < :b"""), {"a": start, "b": end})).scalar_one()
    voice_minutes = round(float(seconds) / 60, 1)
    transcription_usd = (await conn.execute(text("select coalesce(sum(cost_usd), 0) from app.content_sources where created_at >= :a and created_at < :b"),
                                            {"a": start, "b": end})).scalar_one()
    cost_inr = (float(llm_usd + transcription_usd) * settings.usd_to_inr + templates * settings.whatsapp_template_cost_inr
                + voice_minutes * settings.voice_cost_inr_per_minute)
    return {"llm_usd": float(llm_usd), "transcription_usd": float(transcription_usd), "whatsapp_templates": templates,
            "voice_minutes": voice_minutes, "cost_inr": round(cost_inr, 2),
            "revenue": {c: float(v) for c, v in rows}, "revenue_inr": round(revenue_inr, 2),
            "margin_pct": round(100 * (1 - cost_inr / revenue_inr), 1) if revenue_inr else None}
