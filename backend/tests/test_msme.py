"""MSME 45-day recovery (automations/invoice_follow_up/msme.py): legal due dates (MSMED Act s.15), interest at three times
the RBI bank rate compounded monthly (s.16), the registration, the overview, the claim draft, cards once per invoice, the
reminder paragraph, and the website calculator."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from agentry.automations.invoice_follow_up import msme
from agentry.db import tenant_session


def test_legal_due_and_interest():
    d = date(2026, 6, 1)
    assert msme.legal_due(d, d, {}) == date(2026, 6, 16)  # no written agreement: 15 days
    assert msme.legal_due(d, d, {"credit_days": 30}) == date(2026, 7, 1)
    assert msme.legal_due(d, d, {"credit_days": 90}) == date(2026, 7, 16)  # agreed 90, the law caps it at 45
    assert msme.annual_rate() == 3 * 0.0575  # 17.25% a year
    due = date(2026, 7, 1)
    assert msme.interest(100000, due, due) == 0
    assert msme.interest(100000, due, due + timedelta(days=60)) == Decimal("2895.66")  # two monthly rests at 1.4375%
    s = {"enabled": True, "udyam": "UDYAM-MH-26-0012345", "category": "micro", "activity": "manufacturing"}
    inv = {"issued_on": d, "due_on": d, "amount": 100000, "amount_paid": 0, "currency": "INR", "contact_attributes": {}, "company": None}
    assert msme.paragraph(s, inv, date(2026, 6, 10)) is None  # not late yet
    p = msme.paragraph(s, inv, date(2026, 8, 15))
    assert "UDYAM-MH-26-0012345" in p and "16 Jun 2026" in p and "17.25% a year" in p and "section 16" in p
    assert msme.paragraph({**s, "enabled": False}, inv, date(2026, 8, 15)) is None
    assert "claimed as an expense" not in p  # a consumer: no tax note
    biz = msme.paragraph(s, {**inv, "company": "Shah Engineering"}, date(2026, 8, 15))
    assert "only in the year it's actually paid (section 37(2)(g) of the Income-tax Act, 2025)" in biz  # invoice from 1 Jun 2026
    old = msme.paragraph(s, {**inv, "company": "Shah Engineering", "issued_on": date(2026, 2, 1), "due_on": date(2026, 2, 1)}, date(2026, 8, 15))
    assert "section 43B(h) of the Income-tax Act, 1961" in old  # an invoice from FY 2025-26
    assert "claimed as an expense" not in msme.paragraph(s, {**inv, "company": "Shah", "contact_attributes": {"business_buyer": False}}, date(2026, 8, 15))
    assert not msme.settings_of({**s, "activity": "trading"})["enabled"]  # traders aren't covered


async def _invoice(oid: str, days_ago: int, amount: int = 100000) -> str:
    async with tenant_session(oid) as conn:
        cid = (await conn.execute(text("""insert into app.contacts (org_id, name, company, email) values (:o, 'Vikram Shah', 'Shah Engineering', 'vikram@shah.example')
            returning id::text"""), {"o": oid})).scalar_one()
        issued = date.today() - timedelta(days=days_ago)
        await conn.execute(text("""insert into app.invoices (org_id, contact_id, number, currency, amount, amount_paid, issued_on, due_on, status, source)
            values (:o, cast(:c as uuid), 'INV-2231', 'INR', :a, 0, :i, :d, 'open', 'manual')"""), {"o": oid, "c": cid, "a": amount, "i": issued, "d": issued + timedelta(days=30)})
    return cid


async def test_settings_overview_claim_and_cards(client, team_org):
    oid, h = await team_org(["invoice_follow_up"])
    assert (await client.put("/org/invoices/msme", headers=h["owner"], json={"enabled": True, "category": "medium", "activity": "services", "udyam": "UDYAM-MH-26-0012345"})).status_code == 422
    assert (await client.put("/org/invoices/msme", headers=h["owner"], json={"enabled": True, "category": "micro", "activity": "services"})).status_code == 422  # needs Udyam
    trader = await client.put("/org/invoices/msme", headers=h["owner"], json={"enabled": True, "category": "micro", "activity": "trading", "udyam": "UDYAM-MH-26-0012345"})
    assert trader.status_code == 422 and "traders" in trader.json()["detail"]
    assert (await client.put("/org/invoices/msme", headers=h["viewer"], json={"enabled": False})).status_code == 403
    r = await client.put("/org/invoices/msme", headers=h["finance"], json={"enabled": True, "category": "small", "activity": "manufacturing", "udyam": "UDYAM-MH-26-0012345"})
    assert r.status_code == 200, r.text
    cid = await _invoice(oid, days_ago=75)
    o = (await client.get("/org/invoices/msme", headers=h["viewer"])).json()
    c = next(x for x in o["customers"] if x["contact_id"] == cid)
    assert c["credit_days"] == 15 and not c["written"] and c["invoices"][0]["days_late"] == 60 and Decimal(c["interest"]) == Decimal("2895.66")
    assert c["business_buyer"]  # has a company name
    await client.put(f"/org/invoices/msme/customers/{cid}", headers=h["owner"], json={"business_buyer": False})
    r = (await client.put(f"/org/invoices/msme/customers/{cid}", headers=h["owner"], json={"credit_days": 45})).json()
    assert r["written"] and r["business_buyer"] is False  # setting the days kept the buyer choice
    c = next(x for x in (await client.get("/org/invoices/msme", headers=h["owner"])).json()["customers"] if x["contact_id"] == cid)
    assert c["written"] and c["invoices"][0]["days_late"] == 30

    draft = (await client.get(f"/org/invoices/msme/claim/{cid}", headers=h["owner"])).text
    assert "MSME Samadhaan" in draft and "UDYAM-MH-26-0012345" in draft and "Shah Engineering" in draft and "INV-2231" in draft and "Total claimed" in draft

    assert await msme.cards(oid) == 1
    assert await msme.cards(oid) == 0  # once per invoice
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.approvals set status = 'resolved' where payload->>'key' like 'msme:%'"))
    assert await msme.cards(oid) == 0  # still once, after it's dealt with


async def test_website_calculator(client):
    r = (await client.post("/public/playground/msme", json={"input": {"amount": 100000, "invoice_date": str(date.today() - timedelta(days=75))}})).json()
    assert r["days_late"] == 60 and Decimal(r["interest"]) == Decimal("2895.66") and r["credit_days"] == 15
    src = (await client.get("/public/sources/invoice-follow-up")).json()
    assert any(i["value"] == "5.75%" for i in src["items"]) and "MSMED" in src["basis"]
