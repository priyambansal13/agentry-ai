"""Billing: outcomes with attribution, statements (setup, retainer, overage, results, capped commission, GST),
disputes, finalising, platform payment webhook, visibility rules."""
import hashlib
import hmac
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from helpers import enrollment_for, import_invoices, inv
from sqlalchemy import text

from agentry import billing
from agentry.config import settings
from agentry.db import tenant_session
from agentry.invoices import apply_payment
from agentry.sequences import send_step


async def set_plan(org_id: str, **kw) -> None:
    plan = billing.PricingPlan(**kw)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""insert into app.pricing_plans (org_id, currency, setup_fee, retainer, included, overage, outcome_prices,
            revenue_share, tax_rate) values (:o, :c, :sf, :r, cast(:i as jsonb), cast(:ov as jsonb), cast(:op as jsonb), cast(:rs as jsonb), :t)
            on conflict (org_id) do update set setup_fee = excluded.setup_fee, retainer = excluded.retainer, included = excluded.included,
            overage = excluded.overage, outcome_prices = excluded.outcome_prices, revenue_share = excluded.revenue_share, tax_rate = excluded.tax_rate"""),
            {"o": org_id, "c": plan.currency, "sf": plan.setup_fee, "r": plan.retainer, "i": json.dumps(plan.included),
             "ov": json.dumps({k: str(v) for k, v in plan.overage.items()}),
             "op": json.dumps([json.loads(p.model_dump_json()) for p in plan.outcome_prices]),
             "rs": plan.revenue_share.model_dump_json(), "t": plan.tax_rate})


async def overdue_invoice_with_reminder(org_id: str, number: str, amount: int = 45000, days_overdue: int = 10) -> str:
    today = datetime.now(UTC).date()
    await import_invoices(org_id, [inv(number, today - timedelta(days=days_overdue), amount=amount)])
    eid = await enrollment_for(org_id, number)
    await send_step(org_id, eid, 0)  # day-7 reminder delivered (recorded)
    async with tenant_session(org_id) as conn:
        return str((await conn.execute(text("select id from app.invoices where number = :n"), {"n": number})).scalar_one())


async def pay(org_id: str, invoice_id: str, amount: int, ref: str, match: str = "strong") -> dict:
    async with tenant_session(org_id) as conn:
        pid = await apply_payment(conn, org_id, invoice_id=invoice_id, amount=Decimal(amount), currency="INR", gateway="razorpay",
                                  reference=ref, match=match)
        return await billing.record_recovery(conn, org_id, {"invoice_id": invoice_id, "payment_id": pid, "amount": amount,
                                                            "reference": ref, "gateway": "razorpay"})


async def test_recovery_attribution_rules(org):
    await set_plan(org, revenue_share={"basis": "overdue_only", "rate": 0.02, "window_days": 30, "strong_only": True})
    iid = await overdue_invoice_with_reminder(org, "B-1")
    assert (await pay(org, iid, 45000, "pay_1")) == {"billable": True, "reason": None, "strength": "strong"}
    iid2 = await overdue_invoice_with_reminder(org, "B-2")
    weak = await pay(org, iid2, 45000, "pay_2", match="weak")
    assert weak["billable"] is False and "strong matches only" in weak["reason"]
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("B-3", today + timedelta(days=5), email="early@x.example")])
    async with tenant_session(org) as conn:
        iid3 = str((await conn.execute(text("select id from app.invoices where number = 'B-3'"))).scalar_one())
    early = await pay(org, iid3, 45000, "pay_3")
    assert early["billable"] is False and early["reason"] == "paid before it was overdue"


async def test_no_commission_without_a_delivered_reminder(org):
    await set_plan(org, revenue_share={"basis": "all_recovered", "rate": 0.02})
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("B-9", today - timedelta(days=3))])  # no reminder due yet
    async with tenant_session(org) as conn:
        iid = str((await conn.execute(text("select id from app.invoices where number = 'B-9'"))).scalar_one())
    r = await pay(org, iid, 45000, "pay_9")
    assert r["billable"] is False and "no reminder" in r["reason"]


async def test_statement_lines_tax_cap_and_setup_once(org):
    await set_plan(org, setup_fee=25000, retainer=4999, included={"messages": 0}, overage={"messages": 2},
                   outcome_prices=[{"outcome": "appointment_booked", "price": 300}],
                   revenue_share={"basis": "overdue_only", "rate": 0.10, "cap": 6000, "window_days": 30}, tax_rate=0.18)
    iid = await overdue_invoice_with_reminder(org, "C-1", amount=90000)  # 10% of 90,000 = 9,000 -> capped at 6,000
    await pay(org, iid, 90000, "pay_c1")
    async with tenant_session(org) as conn:
        for i in range(2):
            await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, evidence)
                values (:o, 'appointment_booked', :r, now(), 1500, '{"service": "Cleaning"}')"""), {"o": org, "r": f"bk-{i}"})
        start, end = billing.month_bounds(datetime.now(UTC).date())
        sid = await billing.generate_statement(conn, org, start, end)
        assert await billing.generate_statement(conn, org, start, end) == sid  # draft rebuilds in place
        lines = {ln.kind: ln for ln in (await conn.execute(text("select kind, quantity, amount from app.statement_lines where statement_id = :s"), {"s": sid})).all()}
        st = (await conn.execute(text("select subtotal, tax, total from app.statements where id = :s"), {"s": sid})).one()
    assert lines["setup"].amount == 25000 and lines["retainer"].amount == Decimal("4999.00")
    assert lines["outcome"].quantity == 2 and lines["outcome"].amount == 600
    assert lines["commission"].amount == 6000  # cap applied
    assert lines["overage"].quantity >= 1  # the reminder counted as a message (pending: message.sent events)
    assert st.tax == (st.subtotal * Decimal("0.18")).quantize(Decimal("0.01")) and st.total == st.subtotal + st.tax

    async with tenant_session(org) as conn:
        await billing.issue(conn, org, sid)
        assert (await conn.execute(text("select setup_billed from app.pricing_plans"))).scalar_one() is True
        nxt = await billing.generate_statement(conn, org, *billing.month_bounds(datetime.now(UTC).date() + timedelta(days=32)))
        kinds = (await conn.execute(text("select kind from app.statement_lines where statement_id = :s"), {"s": nxt})).scalars().all()
    assert "setup" not in kinds  # setup fee is billed once


async def test_percentage_of_customer_value_with_minimum(org):
    await set_plan(org, outcome_prices=[{"outcome": "appointment_booked", "pct_of_customer_value": 0.15, "min": 500}])
    async with tenant_session(org) as conn:
        for ref, value in (("a", 1500), ("b", 60000)):
            await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, evidence)
                values (:o, 'appointment_booked', :r, now(), :v, '{"service": "x"}')"""), {"o": org, "r": ref, "v": value})
        sid = await billing.generate_statement(conn, org, *billing.month_bounds(datetime.now(UTC).date()))
        amounts = sorted((await conn.execute(text("select amount from app.statement_lines where statement_id = :s"), {"s": sid})).scalars().all())
    assert amounts == [Decimal("500.00"), Decimal("9000.00")]  # 15% of 1,500 = 225 -> minimum 500; 15% of 60,000


async def test_dispute_resolve_finalize_and_pay(org, client):
    await set_plan(org, retainer=1000, outcome_prices=[{"outcome": "appointment_booked", "price": 300}], tax_rate=0.18)
    async with tenant_session(org) as conn:
        await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, evidence)
            values (:o, 'appointment_booked', 'd-1', now(), 1500, '{"service": "x"}')"""), {"o": org})
        sid = await billing.generate_statement(conn, org, *billing.month_bounds(datetime.now(UTC).date()))
        await billing.issue(conn, org, sid)
        line = str((await conn.execute(text("select id from app.statement_lines where statement_id = :s and kind = 'outcome'"), {"s": sid})).scalar_one())
        await billing.dispute(conn, line, "That patient booked by phone themselves")
        assert await billing.finalize_due(conn) == 0  # open dispute + window not over
        await billing.resolve(conn, line, accept=True)
        total = (await conn.execute(text("select total from app.statements where id = :s"), {"s": sid})).scalar_one()
        assert total == Decimal("1180.00")  # 1,000 retainer + 18% GST; the disputed booking is removed
        await conn.execute(text("update app.statements set dispute_until = now() - interval '1 minute' where id = :s"), {"s": sid})
        assert await billing.finalize_due(conn) == 1

    secret = "whsec-billing"
    settings.billing_razorpay_webhook_secret = secret
    body = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"notes": {"statement_id": sid, "org_id": org}}},
                                                                  "payment": {"entity": {"id": "pay_bill_1"}}}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        assert (await client.post("/webhooks/billing/razorpay", content=body, headers={"x-razorpay-signature": "x"})).status_code == 401
        assert (await client.post("/webhooks/billing/razorpay", content=body, headers={"x-razorpay-signature": sig})).status_code == 200
    finally:
        settings.billing_razorpay_webhook_secret = None
    async with tenant_session(org) as conn:
        st = (await conn.execute(text("select status, payment_ref from app.statements where id = :s"), {"s": sid})).one()
    assert st.status == "paid" and st.payment_ref == "razorpay:pay_bill_1"


async def test_clients_never_see_drafts_and_exports_need_permission(client, login, orgs):
    from agentry.db import tenant_session as ts
    sm = orgs["smilecraft"]
    async with ts(sm) as conn:  # the seeded client has its own plan and statements: keep them
        saved_plan = (await conn.execute(text("select * from app.pricing_plans"))).mappings().first()
    await set_plan(sm, retainer=7999, outcome_prices=[{"outcome": "appointment_booked", "price": 250}], tax_rate=0.18)
    async with ts(sm) as conn:  # a month no seed or earlier run has a statement for
        sid = await billing.generate_statement(conn, sm, *billing.month_bounds(date(2024, 1, 15)))
    owner = login("neha@smilecraft.example") | {"X-Org-Id": sm}
    staff = login("admin@agentry.dev") | {"X-Org-Id": sm}
    frontdesk = login("frontdesk@smilecraft.example") | {"X-Org-Id": sm}
    home = (await client.get("/org/billing", headers=owner)).json()
    assert home["plan"]["retainer"] and home["estimate"]["statement"]["status"] == "draft"  # live estimate (rolled back)
    assert all(s["status"] != "draft" for s in home["statements"])
    assert (await client.get(f"/org/billing/statements/{sid}", headers=owner)).status_code == 404
    assert (await client.get(f"/org/billing/statements/{sid}", headers=staff)).status_code == 200
    assert (await client.get("/org/billing", headers=frontdesk)).status_code == 403
    csv_ = await client.get("/org/export/leads.csv", headers=owner)
    assert csv_.status_code == 200 and csv_.text.startswith("name,email")
    assert (await client.get("/org/export/leads.csv", headers=frontdesk)).status_code == 403
    async with ts(sm) as conn:  # remove this test's statement and put the seeded plan back
        await conn.execute(text("update app.outcomes set statement_id = null where statement_id = cast(:s as uuid)"), {"s": sid})
        await conn.execute(text("delete from app.statements where id = cast(:s as uuid)"), {"s": sid})
        if saved_plan:
            await conn.execute(text("""update app.pricing_plans set setup_fee = :sf, retainer = :r, included = cast(:i as jsonb),
                overage = cast(:ov as jsonb), outcome_prices = cast(:op as jsonb), revenue_share = cast(:rs as jsonb), tax_rate = :t,
                setup_billed = :sb"""), {"sf": saved_plan["setup_fee"], "r": saved_plan["retainer"], "i": json.dumps(saved_plan["included"]),
                "ov": json.dumps(saved_plan["overage"]), "op": json.dumps(saved_plan["outcome_prices"]),
                "rs": json.dumps(saved_plan["revenue_share"]), "t": saved_plan["tax_rate"], "sb": saved_plan["setup_billed"]})
        else:
            await conn.execute(text("delete from app.pricing_plans"))


async def test_hq_plan_statement_and_margin_in_rupees(client, login, org):
    staff = login("admin@agentry.dev")
    plan = {"currency": "USD", "retainer": 199, "revenue_share": {"basis": "none"}}
    assert (await client.put(f"/hq/orgs/{org}/plan", json=plan, headers=staff)).status_code == 200
    assert (await client.put(f"/hq/orgs/{org}/plan", json={**plan, "tax_rate": 0.9}, headers=staff)).status_code == 422
    sid = (await client.post(f"/hq/orgs/{org}/statements", json={"month": "2024-02"}, headers=staff)).json()["statement_id"]
    d = (await client.get(f"/hq/orgs/{org}/statements/{sid}", headers=staff)).json()
    assert d["statement"]["status"] == "draft" and Decimal(str(d["statement"]["total"])) == Decimal("199.00")
    assert (await client.get(f"/hq/orgs/{org}/statements/{sid}", headers=login("riya@sharmadigital.example"))).status_code == 403
    async with tenant_session(org) as conn:
        m = await billing.margin(conn, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC))
    assert m["revenue"] == {"USD": 199.0} and m["revenue_inr"] == 199 * settings.fx_to_inr["USD"] and m["margin_pct"] == 100.0



async def test_dispute_partial_credit(client, login, org):
    """A commission covers two recovered invoices; the client disputes one. Staff give a partial credit for that one:
    the line stays, a credit line is added, only that result is excluded, and tax and total follow."""
    await set_plan(org, revenue_share={"basis": "overdue_only", "rate": 0.02, "window_days": 30}, tax_rate=0.18)
    i1 = await overdue_invoice_with_reminder(org, "P-1", amount=100000)
    i2 = await overdue_invoice_with_reminder(org, "P-2", amount=50000)
    await pay(org, i1, 100000, "pay_p1")
    await pay(org, i2, 50000, "pay_p2")
    async with tenant_session(org) as conn:
        sid = await billing.generate_statement(conn, org, *billing.month_bounds(datetime.now(UTC).date()))
        await billing.issue(conn, org, sid)
        line = (await conn.execute(text("select id, amount, evidence from app.statement_lines where statement_id = :s and kind = 'commission'"),
                                   {"s": sid})).one()
        p2 = str((await conn.execute(text("""select o.id from app.outcomes o where o.evidence->>'invoice' = 'P-2'"""))).scalar_one())
    assert line.amount == Decimal("3000.00")  # 2% of 150,000
    staff = login("admin@agentry.dev")
    async with tenant_session(org) as conn:
        await billing.dispute(conn, str(line.id), "P-2 was paid by cheque before any reminder")
    bad = await client.post(f"/hq/orgs/{org}/lines/{line.id}/resolve", headers=staff, json={"credit": 5000})
    assert bad.status_code == 409  # more than the line
    ok = await client.post(f"/hq/orgs/{org}/lines/{line.id}/resolve", headers=staff,
                           json={"credit": 1000, "note": "P-2 paid by cheque before the reminder", "exclude_outcomes": [p2]})
    assert ok.status_code == 200, ok.text
    async with tenant_session(org) as conn:
        lines = {r.kind: r for r in (await conn.execute(text("""select kind, amount, description, dispute_resolution, credit_for
            from app.statement_lines where statement_id = :s"""), {"s": sid})).all()}
        st = (await conn.execute(text("select subtotal, tax, total from app.statements where id = :s"), {"s": sid})).one()
        p2_status = (await conn.execute(text("select status from app.outcomes where id = cast(:i as uuid)"), {"i": p2})).scalar_one()
        p1_status = (await conn.execute(text("select status from app.outcomes where evidence->>'invoice' = 'P-1'"))).scalar_one()
    assert lines["commission"].dispute_resolution == "partial" and lines["commission"].amount == Decimal("3000.00")
    assert lines["credit"].amount == Decimal("-1000.00") and "cheque" in lines["credit"].description and lines["credit"].credit_for
    assert st.subtotal == Decimal("2000.00") and st.tax == Decimal("360.00") and st.total == Decimal("2360.00")
    assert p2_status == "excluded" and p1_status == "billable"
    # resolved once only
    again = await client.post(f"/hq/orgs/{org}/lines/{line.id}/resolve", headers=staff, json={"accept": True})
    assert again.status_code == 409
