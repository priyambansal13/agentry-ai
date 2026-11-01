"""Recurring entries & budgets (bookkeeping): rent, retainers, EMIs and subscriptions booked on their dates.

    entries   name, vendor, category, amount, GST rate, weekly / monthly / quarterly / yearly, next date, optional end
    booking   a daily run books every entry that's due (catching up missed dates) as a ready bookkeeping document, so it
              shows in the month's spend, the Tally / CSV export and the budget check like any bill; never twice
    budgets   the bookkeeping assistant's monthly budgets (an alert at 80% of a category, once a month) count these too
"""
import calendar as cal
import json
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.db import tenant_session


class RecurringConfig(BaseModel):
    pass


register(AutomationTemplate(
    key="recurring_books", name="Recurring entries & budgets",
    description="Rent, retainers and EMIs booked on their dates; alerts at 80% of a budget.",
    config_model=RecurringConfig, metrics=(),
))


def step(d: date, frequency: str, anchor_day: int) -> date:
    if frequency == "weekly":
        return d + timedelta(days=7)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency]
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    return date(y, m, min(anchor_day, cal.monthrange(y, m)[1]))


def _field(v: object) -> dict:
    return {"value": v, "confidence": 1.0}


async def book_due(org_id: str, today: date | None = None) -> int:
    """Book every recurring entry due up to today. Returns the number of entries booked."""
    from agentry.automations.bookkeeping import budget_check, settings_of
    today = today or datetime.now(UTC).date()
    booked = 0
    async with tenant_session(org_id) as conn:
        if not await core.enabled(conn, "recurring_books"):
            return 0
        currency = (await conn.execute(text("select currency from app.org_settings"))).scalar_one_or_none() or "INR"
        _status, bk_cfg = await settings_of(conn)
        rows = (await conn.execute(text("""select * from app.recurring_entries where active and next_on <= :t
            and (ends_on is null or next_on <= ends_on) for update"""), {"t": today})).mappings().all()
        for r in rows:
            d, anchor = r["next_on"], r["next_on"].day
            while d <= today and (not r["ends_on"] or d <= r["ends_on"]):
                sha = f"recurring:{r['id']}:{d}"
                if not (await conn.execute(text("select 1 from app.documents where sha256 = :s"), {"s": sha})).first():
                    base = float(r["amount"])
                    tax = round(base * float(r["gst_rate"]) / 100, 2)
                    fields = {"vendor": _field(r["vendor"]), "bill_number": _field(f"{r['name'][:20]}-{d:%Y%m%d}"), "date": _field(str(d)),
                              "currency": _field(currency), "subtotal": _field(base), "cgst": _field(round(tax / 2, 2) if tax else None),
                              "sgst": _field(round(tax / 2, 2) if tax else None), "igst": _field(None), "total": _field(round(base + tax, 2)),
                              "category": _field(r["category"]), "vendor_gstin": _field(None)}
                    await conn.execute(text("""insert into app.documents (org_id, kind, source, filename, mime, bytes, sha256, file_path, status,
                        fields, confidence, automation_key) values (:o, 'bill', 'recurring', :fn, 'application/x-recurring', 0, :s, '', 'ready',
                        cast(:f as jsonb), 1.0, 'recurring_books')"""),
                        {"o": org_id, "fn": f"{r['name']} ({d:%d %b %Y})", "s": sha, "f": json.dumps(fields)})
                    await budget_check(conn, org_id, fields, bk_cfg)
                    booked += 1
                d = step(d, r["frequency"], anchor)
            await conn.execute(text("update app.recurring_entries set next_on = :n, last_booked_on = :l where id = :i"),
                               {"n": d, "l": today, "i": r["id"]})
    return booked


async def entries(conn: AsyncConnection) -> list[dict]:
    rows = (await conn.execute(text("""select r.*, (select count(*) from app.documents d where d.sha256 like 'recurring:' || r.id || ':%') as booked
        from app.recurring_entries r order by r.active desc, r.next_on"""))).mappings().all()
    return [dict(r) | {"id": str(r["id"]), "amount": float(r["amount"]), "gst_rate": float(r["gst_rate"])} for r in rows]


def monthly_cost(rows: list[dict]) -> float:
    per = {"weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3, "yearly": 1 / 12}
    return round(sum(r["amount"] * (1 + r["gst_rate"] / 100) * per[r["frequency"]] for r in rows if r["active"]), 2)
