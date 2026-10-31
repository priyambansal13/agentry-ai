"""Document AI + Bookkeeping: fields with confidence, checks done by code (totals, GSTIN, dates, duplicates), a person
checks anything unsure, money roles only, budget alerts once, monthly summary numbers from code, Tally/CSV export of
ready documents only, and receipts sent on WhatsApp."""
import io
import xml.etree.ElementTree as ET
from datetime import date

from conftest import expect
from PIL import Image
from sqlalchemy import text

from agentry import documents
from agentry.automations import bookkeeping as bk
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
S = documents.SAMPLES


async def books(team_org):
    return await team_org(["bookkeeping"])


async def load_samples(client, h) -> dict[str, dict]:
    r = await client.post("/org/bookkeeping/samples", headers=h["finance"])
    assert r.status_code == 201, r.text
    return {i["file"]: i for i in r.json()["items"]}


def test_gstin_check_digit():
    assert documents.gstin_ok("27AAPFU0939F1ZV") and documents.gstin_ok("27aabcs1429b1zu")
    assert not documents.gstin_ok("27AABCS1429B1Z1")  # wrong check digit
    assert not documents.gstin_ok("00AAPFU0939F1ZV") and not documents.gstin_ok("27AAPFU0939F1Z")


def test_code_checks_lower_confidence():
    raw = {"vendor": {"value": "X", "confidence": 0.99}, "date": {"value": "29/10/2026", "confidence": 0.99}, "subtotal": {"value": "1,000", "confidence": 0.99},
           "cgst": {"value": 90, "confidence": 0.99}, "sgst": {"value": 80, "confidence": 0.99}, "total": {"value": "₹1,500.00", "confidence": 0.99},
           "category": {"value": "groceries & pantry", "confidence": 0.9}, "vendor_gstin": {"value": "27AABCS1429B1Z1", "confidence": 0.95}}
    f = documents.normalise(raw, bk.CATEGORIES)
    assert f["date"]["value"] == "2026-10-29" and f["total"]["value"] == 1500.0 and f["category"]["value"] == "Groceries & pantry"
    codes = [c["code"] for c in documents.check(f, today=date(2026, 10, 31))]
    assert codes == ["totals", "tax_split", "gstin"]
    assert f["total"]["confidence"] == 0.5 and f["vendor_gstin"]["confidence"] == 0.3 and f["cgst"]["confidence"] == 0.6
    assert documents.decide(f, documents.check(f, today=date(2026, 10, 31)), 0.85)[0] == "needs_review"
    future = documents.normalise({**raw, "date": {"value": "2027-01-05", "confidence": 1}}, bk.CATEGORIES)
    assert "date_future" in [c["code"] for c in documents.check(future, today=date(2026, 10, 31))]


def test_a_confident_guess_is_still_caught():
    """Seen live: a smudged "7?0" read as 770 at 98% while the items add up to 760, and "2?/10" read as the 22nd at 95%."""
    raw = {"vendor": {"value": "Blue Tokai Coffee", "confidence": 0.98}, "date": {"value": "2026-10-22", "confidence": 0.95},
           "subtotal": {"value": 770, "confidence": 0.9}, "total": {"value": 770, "confidence": 0.98}, "category": {"value": "Meals & entertainment", "confidence": 0.96}}
    f = documents.normalise(raw, bk.CATEGORIES)
    items = documents.items_of([{"description": "2 x Cappuccino", "amount": "520"}, {"description": "Croissant", "amount": 240}])
    checks = documents.check(f, today=date(2026, 10, 31), items=items)
    assert [c["message"] for c in checks] == ["The items add up to 760.00, not 770.00"] and f["total"]["confidence"] == 0.5
    assert documents.mark_unclear(f, ["date", "nonsense"]) == ["date"] and f["date"]["confidence"] == 0.4
    assert documents.decide(f, checks, 0.85)[0] == "needs_review"
    ok = documents.normalise({**raw, "subtotal": {"value": 760, "confidence": 0.9}, "total": {"value": 760, "confidence": 0.9}}, bk.CATEGORIES)
    assert documents.check(ok, today=date(2026, 10, 31), items=items) == []


async def test_samples_ready_or_checked_and_money_roles(client, team_org):
    _oid, h = await books(team_org)
    got = {r: (await client.get("/org/bookkeeping/documents", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=200, viewer=200, agentry=200)
    assert (await client.post("/org/bookkeeping/samples", headers=h["viewer"])).status_code == 403
    s = await load_samples(client, h)
    assert {k: v["status"] for k, v in s.items()} == {"grocery-receipt.jpg": "ready", "supplier-tax-invoice.png": "ready",
                                                     "cafe-receipt-smudged.jpg": "needs_review"}
    cafe = (await client.get(f"/org/bookkeeping/documents/{s['cafe-receipt-smudged.jpg']['id']}", headers=h["viewer"])).json()
    assert cafe["fields"]["date"]["confidence"] == 0.4 and cafe["can_act"] is False and cafe["source"] == "sample"
    cards = {r: [c for c in (await client.get("/org/approvals", headers=h[r])).json().get("items", []) if c["kind"] == "document_review"]
             for r in ("owner", "finance")}
    assert len(cards["owner"]) == 1 == len(cards["finance"]) and cards["finance"][0]["title"].startswith("Check this receipt: Blue Tokai Coffee, ₹760.00")
    staff = await client.get("/org/approvals", headers=h["staff"])
    assert not [c for c in (staff.json().get("items", []) if staff.status_code == 200 else []) if c["kind"] == "document_review"]  # not front desk
    f = (await client.get(f"/org/bookkeeping/documents/{s['cafe-receipt-smudged.jpg']['id']}/file", headers=h["finance"]))
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg"


async def test_same_file_twice_is_rejected_and_review_files_it(client, team_org):
    oid, h = await books(team_org)
    s = await load_samples(client, h)
    again = await client.post("/org/bookkeeping/documents", headers=h["owner"],
                              files={"file": ("again.jpg", (S / "grocery-receipt.jpg").read_bytes(), "image/jpeg")})
    assert again.json()["status"] == "rejected"
    cafe = s["cafe-receipt-smudged.jpg"]["id"]
    assert (await client.put(f"/org/bookkeeping/documents/{cafe}", headers=h["viewer"], json={"action": "accept"})).status_code == 403
    r = await client.put(f"/org/bookkeeping/documents/{cafe}", headers=h["finance"], json={"action": "accept", "fields": {"date": "25/10/2026", "total": "760"}})
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["fields"]["date"] == {"value": "2026-10-25", "confidence": 1.0, "checked": True}
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select status from app.approvals where kind = 'document_review'"))).scalar_one() == "resolved"
        assert (await conn.execute(text("select count(*) from app.audit_log where action = 'document.accepted'"))).scalar_one() == 1
    bad = (await client.post("/org/bookkeeping/documents", headers=h["owner"], files={"file": ("x.txt", b"hello", "text/plain")}))
    assert bad.status_code == 422


async def test_approving_the_card_accepts_as_read(client, team_org):
    oid, h = await books(team_org)
    s = await load_samples(client, h)
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select id::text from app.approvals where kind = 'document_review'"))).scalar_one()
    assert (await client.post(f"/org/approvals/{card}", headers=h["finance"], json={"action": "approve"})).status_code == 200
    assert await bk.document_card_step(oid, card, "approved") == "ready"
    d = (await client.get(f"/org/bookkeeping/documents/{s['cafe-receipt-smudged.jpg']['id']}", headers=h["owner"])).json()
    assert d["status"] == "ready" and d["reviewed_at"]


async def test_budget_alert_once_a_month_and_monthly_summary(client, team_org):
    oid, h = await books(team_org)
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"budgets": {"Groceries & pantry": 1500, "Supplies & materials": 50000}}'"""))
    await load_samples(client, h)
    async with tenant_session(oid) as conn:
        alerts = (await conn.execute(text("select payload from app.events where type = 'budget.alert'"))).scalars().all()
    assert alerts == [{"category": "Groceries & pantry", "month": "2026-10", "spent": 1254.76, "budget": 1500.0, "percent": 84}]
    s = await bk.monthly(oid, "2026-10", with_model=False)
    assert s["title"] == "Expenses for October 2026: ₹11,167"
    assert s["body"].splitlines()[:3] == ["Spent ₹11,167 in October 2026.", "• Supplies & materials: ₹9,912 of ₹50,000 budget",
                                          "• Groceries & pantry: ₹1,255 of ₹1,500 budget"]
    assert s["body"].endswith("1 document still to check.")
    lst = (await client.get("/org/bookkeeping/documents?month=2026-10", headers=h["owner"])).json()
    assert lst["total"] == 11166.76 and lst["by_category"][0] == {"category": "Supplies & materials", "spent": 9912.0, "budget": 50000}


async def test_export_ready_only_once(client, team_org):
    _oid, h = await books(team_org)
    await load_samples(client, h)
    r = await client.get("/org/bookkeeping/export?format=csv", headers=h["finance"])
    rows = r.text.strip().splitlines()
    assert r.headers["x-count"] == "2" and rows[0].startswith("Date,Vendor,Vendor GSTIN,Bill Number,Category")
    assert rows[1].startswith("2026-10-22,Sai Dental Supplies Pvt Ltd,27AABCS1429B1ZU,SDS/24-25/1187,Supplies & materials")
    assert (await client.get("/org/bookkeeping/export?format=csv", headers=h["finance"])).headers["x-count"] == "0"  # already exported
    t = await client.get("/org/bookkeeping/export?format=tally&include_exported=true", headers=h["owner"])
    root = ET.fromstring(t.text)
    vouchers = root.findall(".//VOUCHER")
    assert len(vouchers) == 2 and vouchers[0].findtext("DATE") == "20261022" and vouchers[0].findtext("PARTYGSTIN") == "27AABCS1429B1ZU"
    amounts = [float(a.text) for a in vouchers[0].iter("AMOUNT")]
    assert abs(sum(amounts)) < 0.01 and amounts[0] == 9912.0  # debits equal credits
    assert (await client.get("/org/bookkeeping/export", headers=h["viewer"])).status_code == 403


async def test_receipts_on_whatsapp(team_org, monkeypatch):
    from agentry.connectors import whatsapp
    oid, _h = await books(team_org)
    sent, pngs = [], {}

    async def fake_send(org_id, to, body):
        sent.append((to, body))
        return f"wamid.{len(sent)}"

    async def fake_media(org_id, media_id):
        return pngs[media_id], "image/jpeg"
    monkeypatch.setattr(whatsapp, "send_text", fake_send)
    monkeypatch.setattr(whatsapp, "download_media", fake_media)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    pngs.update({"m1": (S / "grocery-receipt.jpg").read_bytes(), "m2": buf.getvalue()})
    from agentry.leads import resolve_contact
    async with tenant_session(oid) as conn:
        k = await resolve_contact(conn, oid, name="Ramesh", phone="+919800000001", source="whatsapp")
        conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, contact_id, subject, external_ref)
            values (:o, 'whatsapp', :k, 'WhatsApp', 'wa:919800000001') returning id"""), {"o": oid, "k": k})).scalar_one())
    p = {"wa_id": "919800000001", "type": "image", "media": {"id": "m1", "mime": "image/jpeg"}}
    assert await bk.take_from_chat(oid, "whatsapp", conv, p) is True
    assert sent[-1] == ("919800000001", "Got it: FreshMart Supermarket, ₹1,254.76 on 28 Oct, filed under Groceries & pantry.")
    assert await bk.take_from_chat(oid, "whatsapp", conv, {**p, "media": {"id": "m2", "mime": "image/jpeg"}}) is False  # not a bill: the assistant's
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"senders": ["+91 98000 00002"]}'"""))
        src = (await conn.execute(text("select source, contact_id::text from app.documents where status = 'ready'"))).one()
    assert src == ("whatsapp", str(k))
    assert await bk.take_from_chat(oid, "whatsapp", conv, p) is False  # not on the senders list
    assert len(sent) == 1


def test_tally_voucher_balances_even_if_the_subtotal_was_misread():
    doc = {"id": "0123456789", "fields": {k: {"value": v} for k, v in {"vendor": "Blue Tokai", "date": "2026-10-25", "subtotal": 770, "total": 760,
                                                                       "category": "Meals & entertainment", "cgst": None, "sgst": None, "igst": None}.items()}}
    amounts = [float(a.text) for a in ET.fromstring(bk.to_tally([doc], "SmileCraft")).iter("AMOUNT")]
    assert amounts == [760.0, -760.0]
