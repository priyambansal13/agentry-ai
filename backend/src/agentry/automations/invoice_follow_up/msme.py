"""MSME 45-day recovery (docs/PLAN-COMMERCIAL-2026-11.md #4), part of invoice follow-up, for a business registered as a micro
or small enterprise (Udyam).

    legal due  MSMED Act section 15: the date agreed in writing with the buyer (at most 45 days from the invoice), or 15
               days without a written agreement. The day counts are official figures (official_rules msme.*).
    interest   section 16: from the legal due date, compound interest with monthly rests at three times the RBI bank rate
               (official figure msme.bank_rate, checked daily against official sources). Whole months compound; a part
               month is pro rata.
    reminders  polite / firm / final reminders on an invoice past its legal due date get a short, factual paragraph: the
               registration, the legal due date, the rate and the interest so far (added by code, never by the writer)
    cards      a Needs-you card when an invoice crosses its legal due date
    claim      a MSME Samadhaan claim draft per customer: the facts, every invoice with its legal due date and interest, the
               total, to file at samadhaan.msme.gov.in
Medium enterprises aren't covered by sections 15-16, so only micro and small can switch it on.
"""
import json
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text

from agentry import official_rules as rules

CATEGORIES = ("micro", "small")


def _q(v: Decimal | float) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def settings_of(raw: dict | None) -> dict:
    s = raw or {}
    return {"enabled": bool(s.get("enabled")) and s.get("category") in CATEGORIES, "udyam": s.get("udyam"), "category": s.get("category")}


def credit_days(attrs: dict | None) -> tuple[int, bool]:
    """(days, written): the buyer's agreed days capped at the legal maximum, else the no-agreement default."""
    agreed = (attrs or {}).get("credit_days")
    try:
        if agreed is not None and int(agreed) > 0:
            return min(int(agreed), int(rules.num("msme.max_days"))), True
    except (TypeError, ValueError):
        pass
    return int(rules.num("msme.default_days")), False


def legal_due(issued_on: date | None, due_on: date, attrs: dict | None) -> date:
    days, _ = credit_days(attrs)
    return (issued_on or due_on) + timedelta(days=days)


def annual_rate() -> float:
    return 3 * rules.num("msme.bank_rate")


def interest(outstanding: float | Decimal, due: date, as_of: date) -> Decimal:
    """Compound with monthly rests at three times the bank rate, from the day after the legal due date."""
    if as_of <= due or float(outstanding) <= 0:
        return Decimal(0)
    m = annual_rate() / 12
    days = (as_of - due).days
    months, rest = divmod(days, 30)
    grown = float(outstanding) * (1 + m) ** months * (1 + m * rest / 30)
    return _q(grown - float(outstanding))


def paragraph(s: dict, inv: dict, as_of: date) -> str | None:
    """The reminder's MSME paragraph, or None when it doesn't apply (not registered, not past the legal due date)."""
    if not s["enabled"]:
        return None
    due = legal_due(inv.get("issued_on"), inv["due_on"], inv.get("contact_attributes"))
    if as_of <= due:
        return None
    outstanding = float(inv["amount"]) - float(inv["amount_paid"])
    acc = interest(outstanding, due, as_of)
    sym = "₹" if inv.get("currency", "INR") == "INR" else f"{inv.get('currency')} "
    udyam = f" (Udyam {s['udyam']})" if s.get("udyam") else ""
    return (f"As a {s['category']} enterprise registered under the MSMED Act, 2006{udyam}, "
            f"payment for this invoice was due by {due:%d %b %Y} (section 15). Interest at three times the RBI bank rate "
            f"({annual_rate() * 100:.2f}% a year, compounded monthly) applies after that date (section 16): {sym}{acc:,.2f} so far.")


async def overview(conn, as_of: date | None = None) -> dict:
    as_of = as_of or datetime.now(UTC).date()
    s = settings_of((await conn.execute(text("select msme from app.org_settings"))).scalar_one_or_none())
    rows = (await conn.execute(text("""select i.id::text, i.number, i.currency, i.amount, i.amount_paid, i.issued_on, i.due_on, i.status,
        k.id::text as contact_id, coalesce(k.company, k.name) as customer, k.attributes as contact_attributes
        from app.invoices i left join app.contacts k on k.id = i.contact_id where i.status in ('open','partially_paid','disputed')"""))).mappings().all()
    by: dict[str, dict] = {}
    for r in rows:
        due = legal_due(r["issued_on"], r["due_on"], r["contact_attributes"])
        outstanding = float(r["amount"]) - float(r["amount_paid"])
        acc = interest(outstanding, due, as_of)
        days, written = credit_days(r["contact_attributes"])
        c = by.setdefault(r["contact_id"] or "none", {"contact_id": r["contact_id"], "customer": r["customer"] or "Unknown", "credit_days": days,
                                                       "written": written, "invoices": [], "outstanding": Decimal(0), "late": Decimal(0), "interest": Decimal(0)})
        c["invoices"].append({"id": r["id"], "number": r["number"], "issued_on": r["issued_on"], "legal_due": due, "days_late": max(0, (as_of - due).days),
                              "outstanding": _q(outstanding), "interest": acc})
        c["outstanding"] += _q(outstanding)
        if as_of > due:
            c["late"] += _q(outstanding)
            c["interest"] += acc
    customers = sorted(by.values(), key=lambda c: -c["late"])
    return json.loads(json.dumps({"settings": s, "rate": annual_rate(), "bank_rate": rules.num("msme.bank_rate"), "as_of": as_of,
                                  "late": sum((c["late"] for c in customers), Decimal(0)), "interest": sum((c["interest"] for c in customers), Decimal(0)),
                                  "customers": customers}, default=str))


async def claim_draft(conn, contact_id: str, as_of: date | None = None) -> str:
    """The facts for a MSME Samadhaan application against one buyer, ready to copy into samadhaan.msme.gov.in."""
    as_of = as_of or datetime.now(UTC).date()
    o = await overview(conn, as_of)
    c = next((x for x in o["customers"] if x["contact_id"] == contact_id), None)
    if not c or not any(i["days_late"] for i in c["invoices"]):
        raise ValueError("no invoices past their legal due date for this customer")
    biz = (await conn.execute(text("""select o.name, s.profile, s.msme from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
    k = (await conn.execute(text("select name, company, email, phone_e164, attributes from app.contacts where id = cast(:c as uuid)"), {"c": contact_id})).mappings().one()
    s = o["settings"]
    late = [i for i in c["invoices"] if i["days_late"]]
    principal = sum(Decimal(i["outstanding"]) for i in late)
    accrued = sum(Decimal(i["interest"]) for i in late)
    lines = "\n".join(f"| {i['number']} | {date.fromisoformat(i['issued_on']):%d %b %Y} | {date.fromisoformat(i['legal_due']):%d %b %Y} | {i['days_late']} | "
                      f"₹{Decimal(i['outstanding']):,.2f} | ₹{Decimal(i['interest']):,.2f} |" if i["issued_on"] else
                      f"| {i['number']} | – | {date.fromisoformat(i['legal_due']):%d %b %Y} | {i['days_late']} | ₹{Decimal(i['outstanding']):,.2f} | ₹{Decimal(i['interest']):,.2f} |"
                      for i in late)
    attrs = k["attributes"] or {}
    return f"""# MSME Samadhaan application: draft

To file at https://samadhaan.msme.gov.in (Delayed Payment Monitoring System). Check every figure against your books before filing.

## Supplier (applicant)
- Name: {biz['name']}
- Udyam registration: {s.get('udyam') or '[add your Udyam number]'} ({s.get('category') or 'micro / small'} enterprise)

## Buyer (respondent)
- Name: {k['company'] or k['name']}{f" (contact: {k['name']})" if k['company'] and k['name'] else ''}
- GSTIN: {attrs.get('gstin') or '[buyer GSTIN]'}
- Email / phone: {k['email'] or '-'} / {k['phone_e164'] or '-'}
- Credit agreed in writing: {f"{c['credit_days']} days" if c['written'] else "none (15 days applies)"}

## Facts
Goods / services were supplied against the invoices below. Under section 15 of the MSMED Act, 2006, payment was due by the
dates shown. The amounts remain unpaid as on {as_of:%d %b %Y}. Under section 16, compound interest with monthly rests at three
times the RBI bank rate ({o['rate'] * 100:.2f}% a year; bank rate {o['bank_rate'] * 100:.2f}%) is payable from those dates.

| Invoice | Invoice date | Due by (s.15) | Days late | Unpaid | Interest to {as_of:%d %b %Y} |
|---|---|---|---|---|---|
{lines}

**Principal unpaid: ₹{principal:,.2f} · Interest so far: ₹{accrued:,.2f} · Total claimed: ₹{principal + accrued:,.2f}** (interest continues until paid).

## Reminders sent
Payment reminders were sent by email / WhatsApp on the dates recorded in our follow-up log (attach it).

## Attach
Invoices, proof of delivery / acceptance, any written credit terms, the reminder log, the Udyam certificate.
"""


async def cards(org_id: str, as_of: date | None = None) -> int:
    """A Needs-you card the first time each invoice is past its legal due date."""
    from agentry.db import tenant_session
    as_of = as_of or datetime.now(UTC).date()
    n = 0
    async with tenant_session(org_id) as conn:
        o = await overview(conn, as_of)
        if not o["settings"]["enabled"]:
            return 0
        for c in o["customers"]:
            for i in c["invoices"]:
                if not i["days_late"]:
                    continue
                key = f"msme:{i['id']}"
                if (await conn.execute(text("select 1 from app.approvals where payload->>'key' = :k"), {"k": key})).first():
                    continue  # carded once already, whatever happened to the card
                await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
                    values (:o, 'escalation', 'invoice_follow_up', :t, :b, cast(:p as jsonb))"""),
                    {"o": org_id, "t": f"{c['customer']}: invoice {i['number']} is past the MSME due date"[:200],
                     "b": f"Due by {date.fromisoformat(i['legal_due']):%d %b %Y} under the MSMED Act; ₹{Decimal(i['outstanding']):,.2f} unpaid, "
                          f"interest ₹{Decimal(i['interest']):,.2f} so far. Reminders now mention it; a MSME Samadhaan draft is on the Invoices page.",
                     "p": json.dumps({"key": key, "invoice_id": i["id"], "contact_id": c["contact_id"]})})
                made = True
                n += 1 if made else 0
    return n
