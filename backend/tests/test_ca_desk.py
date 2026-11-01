"""CA Firm pack, agents 1-4 (docs/PACKS.md): filing tracker, document chaser, tax documents reader, compliance calendar."""
from datetime import date, timedelta

from sqlalchemy import text

from agentry.automations.ca import calendar, chaser, taxdocs, tracker
from agentry.db import tenant_session

CA4 = ["ca_filing_tracker", "ca_document_chaser", "ca_tax_docs_reader", "ca_compliance_calendar"]
PRIYA = {"name": "Priya Sharma", "pan": "ABCPS1234K", "phone": "+91 98100 00011", "email": "priya@example.com",
         "profile": {"salaried": True, "capital_gains": True, "deductions": True}}


async def test_clients_board_and_a_season(client, team_org):
    oid, h = await team_org(CA4)
    r = await client.post("/org/ca/clients", headers=h["owner"], json=PRIYA)
    assert r.status_code == 201, r.text
    priya = r.json()["id"]
    assert (await client.post("/org/ca/clients", headers=h["owner"], json=PRIYA | {"name": "Dup"})).status_code == 422  # same PAN
    assert (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Bad", "pan": "12345"})).status_code == 422
    csv = "Name,PAN,Mobile,Email,Type\nMehta Traders,AAKFM1234L,9810000022,accounts@mehta.example,firm\nRavi Kumar,ABCPK9999Z,,ravi@example.com,\n"
    r = await client.post("/org/ca/clients/import", headers=h["manager"], files={"file": ("clients.csv", csv.encode(), "text/csv")})
    assert r.json() == {"added": 2, "updated": 0, "errors": []}
    assert (await client.post("/org/ca/clients", headers=h["viewer"], json={"name": "Xavier"})).status_code == 403  # viewers read only
    assert len((await client.get("/org/ca/clients", headers=h["viewer"])).json()["items"]) == 3

    # ITR season for individuals: two cards, and the salaried client's checklist follows their profile
    r = await client.post("/org/ca/filings/season", headers=h["staff"], json={"kind": "itr", "period": "AY 2026-27", "due_on": "2026-07-31",
                                                                              "client_kinds": ["individual"]})
    assert r.json() == {"created": 2, "already_there": 0}
    assert (await client.post("/org/ca/filings/season", headers=h["staff"], json={"kind": "itr", "period": "AY 2026-27"})).json() == \
        {"created": 1, "already_there": 2}  # the firm too, the rest already there
    board = (await client.get(f"/org/ca/filings?client_id={priya}", headers=h["owner"])).json()["items"]
    card = board[0]
    assert card["status"] == "docs_pending" and card["title"] == "ITR AY 2026-27"
    assert {"Form 16 from your employer", "Capital gains statement (broker tax P&L, CAMS or KFintech)"} <= set(card["missing"])
    assert "Rent receipts and your landlord's PAN (for HRA)" not in card["missing"]  # doesn't pay rent

    # move it on; filing it emits the metric event
    r = await client.patch(f"/org/ca/filings/{card['id']}", headers=h["staff"], json={"status": "filed", "ack_no": "123456789012345"})
    assert r.json()["status"] == "filed"
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.events where type = 'ca.filing_filed'"))).scalar_one() == 1
        f = (await conn.execute(text("select filed_on from app.ca_filings where id = cast(:i as uuid)"), {"i": card["id"]})).scalar_one()
    assert f is not None
    mine = (await client.get("/org/ca/filings?assignee=me", headers=h["staff"])).json()["items"]
    assert mine == []  # nobody assigned yet
    await client.patch(f"/org/ca/filings/{card['id']}", headers=h["owner"], json={"assignee": (await client.get("/org/ca/meta", headers=h["staff"])).json()["me"]})
    assert len((await client.get("/org/ca/filings?assignee=me", headers=h["staff"])).json()["items"]) == 1


async def test_documents_come_in_on_whatsapp_and_the_card_moves(client, team_org, monkeypatch):
    from agentry.connectors import whatsapp
    oid, h = await team_org(CA4)
    priya = (await client.post("/org/ca/clients", headers=h["owner"], json=PRIYA | {"profile": {"salaried": True}})).json()["id"]
    await client.post("/org/ca/filings", headers=h["owner"], json={"client_id": priya, "kind": "itr", "period": "AY 2026-27"})
    sent = []

    async def fake_send(org_id, to, body):
        sent.append((to, body))
        return f"wamid.{len(sent)}"

    files = {"m1": (b"FORM NO. 16\nCertificate under section 203 ... TAN of the Deductor", "form16.txt")}

    async def fake_media(org_id, media_id):
        return files[media_id][0], "text/plain"
    monkeypatch.setattr(whatsapp, "send_text", fake_send)
    monkeypatch.setattr(whatsapp, "download_media", fake_media)
    async with tenant_session(oid) as conn:
        k = (await conn.execute(text("select contact_id::text from app.ca_clients where id = cast(:i as uuid)"), {"i": priya})).scalar_one()
        conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, contact_id, subject, external_ref)
            values (:o, 'whatsapp', :k, 'WhatsApp', 'wa:919810000011') returning id"""), {"o": oid, "k": k})).scalar_one())
    p = {"wa_id": "919810000011", "type": "document", "media": {"id": "m1", "filename": "form16.txt"}}
    assert await chaser.take_from_whatsapp(oid, conv, p) is True
    assert "received your form16" in sent[-1][1].lower() and "Bank statements" in sent[-1][1]
    assert await chaser.take_from_whatsapp(oid, conv, p | {"wa_id": "919999999999"}) is False  # not one of the firm's clients
    # the rest arrive through the portal; when nothing is missing the card moves to In preparation
    for name, body in (("bank-statement.txt", b"STATEMENT OF ACCOUNT HDFC Bank"), ("interest-certificate.txt", b"Interest certificate FY 2025-26")):
        r = await client.post(f"/org/ca/clients/{priya}/files", headers=h["staff"], files={"file": (name, body, "text/plain")})
        assert r.status_code == 201, r.text
    assert r.json()["complete"] is True
    card = (await client.get(f"/org/ca/filings?client_id={priya}", headers=h["owner"])).json()["items"][0]
    assert card["status"] == "in_prep" and card["missing"] == [] and card["files"] == 3
    # status on WhatsApp: only their own filings
    assert await tracker.answer_status(oid, conv, "919810000011", "Is my ITR filed?") is True
    assert "ITR AY 2026-27: In preparation" in sent[-1][1]
    assert await tracker.answer_status(oid, conv, "919810000011", "thanks!") is False


async def test_reminders_until_a_person_should_call(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(CA4)
    priya = (await client.post("/org/ca/clients", headers=h["owner"], json=PRIYA)).json()["id"]
    await client.post("/org/ca/filings", headers=h["owner"], json={"client_id": priya, "kind": "itr", "period": "AY 2026-27"})
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append((who["contact_name"], body, kw["subject"]))
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    from datetime import UTC, datetime
    now = datetime(2026, 6, 1, 10, tzinfo=UTC)
    assert await chaser.send_reminders(oid, now) == 1
    assert "Form 16 from your employer" in sent[0][1] and sent[0][1].startswith("Hi Priya,")
    assert await chaser.send_reminders(oid, now + timedelta(days=1)) == 0  # every 3 days
    for i in range(4):
        assert await chaser.send_reminders(oid, now + timedelta(days=3 * (i + 1))) == 1
    assert await chaser.send_reminders(oid, now + timedelta(days=30)) == 0  # 5 sent: a person calls now
    async with tenant_session(oid) as conn:
        cards = (await conn.execute(text("select title from app.approvals where kind = 'ca_task'"))).scalars().all()
    assert any("hasn't sent documents after 5 reminders" in c for c in cards)


async def test_tax_documents_read_and_compared(client, team_org):
    _oid, h = await team_org(CA4)
    priya = (await client.post("/org/ca/clients", headers=h["owner"], json=PRIYA)).json()["id"]
    assert (await client.post(f"/org/ca/clients/{priya}/samples", headers=h["owner"])).status_code == 200
    t = (await client.get(f"/org/ca/clients/{priya}/tax", headers=h["finance"])).json()
    assert {d["doc_type"] for d in t["documents"]} == {"form16", "ais"} and t["years"] == ["2026-27"]
    assert all(i["traced"] for d in t["documents"] for i in d["items"])
    first = t["points"][0]
    assert first["kind"] == "tds_mismatch" and "₹2,46,500" in first["message"] and "₹2,41,500" in first["message"]
    kinds = [p["kind"] for p in t["points"]]
    assert kinds.count("income_to_declare") == 4  # deposit interest, savings interest, dividend, share sales
    assert any("capital gains statement" in p["message"] for p in t["points"])
    assert t["summary"]["from"] == "AIS / 26AS" and t["summary"]["income"]["interest_deposit"] == 52310
    x = await client.get(f"/org/ca/clients/{priya}/tax.xlsx", headers=h["owner"])
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_an_invented_number_is_not_traced():
    doc = "TDS-194A | HDFC BANK LIMITED | Amount paid: 52,310 TDS: 5,231"
    items = [{"category": "interest_deposit", "amount": 52310, "tds": 5231, "quote": "Amount paid: 52,310 TDS: 5,231"},
             {"category": "dividend", "amount": 9000, "quote": "Amount paid: 52,310"},  # amount not in its quote
             {"category": "rent", "amount": 120000, "quote": "Rent received 1,20,000"}]  # quote not in the document
    assert [i["traced"] for i in taxdocs.trace(items, doc)] == [True, False, False]


def test_due_dates_follow_the_profile():
    gst_monthly = calendar.deadlines("firm", {"gst": True, "tds": True}, date(2026, 11, 1), date(2026, 11, 30))
    titles = {(d["title"], d["due_on"]) for d in gst_monthly}
    assert ("GSTR-1 Oct 2026", date(2026, 11, 11)) in titles and ("GSTR-3B Oct 2026", date(2026, 11, 20)) in titles
    assert ("TDS payment Oct 2026", date(2026, 11, 7)) in titles
    qrmp = calendar.deadlines("individual", {"gst": True, "gst_qrmp": True}, date(2027, 1, 1), date(2027, 1, 31))
    assert [(d["title"], d["due_on"]) for d in qrmp if d["kind"] == "gstr3b"] == [("GSTR-3B Q3 FY 2026-27", date(2027, 1, 22))]
    tds_q = calendar.deadlines("company", {"tds": True}, date(2027, 1, 1), date(2027, 1, 31))
    assert {d["kind"] for d in tds_q if d["due_on"] == date(2027, 1, 31)} == {"tds_26q", "tds_24q"}
    itr = calendar.deadlines("individual", {}, date(2026, 7, 1), date(2026, 7, 31))
    assert [(d["title"], d["due_on"]) for d in itr] == [("ITR AY 2026-27", date(2026, 7, 31))]
    audit = calendar.deadlines("individual", {"audit": True, "business": True}, date(2026, 9, 1), date(2026, 10, 31))
    assert {(d["kind"], d["due_on"]) for d in audit} >= {("tax_audit", date(2026, 9, 30)), ("itr", date(2026, 10, 31)),
                                                         ("advance_tax", date(2026, 9, 15))}
    roc = calendar.deadlines("company", {}, date(2026, 9, 1), date(2026, 11, 30))
    assert {d["kind"] for d in roc} >= {"roc_aoc4", "roc_mgt7", "dir3_kyc", "itr"}


async def test_calendar_puts_due_dates_on_the_board_and_reminds(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(CA4)
    await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Traders", "kind": "firm", "phone": "+919810000022",
                                                                   "profile": {"gst": True}})
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    today = date(2026, 11, 13)
    assert await calendar.daily(oid, today) >= 2  # GSTR-3B Oct (20 Nov) and the next ones within 30 days
    assert await calendar.daily(oid, today) == 0  # never twice
    assert any("GSTR-3B Oct 2026 is due on 20 Nov 2026" in s for s in sent)  # 7 days before
    n = len(sent)
    await calendar.daily(oid, today + timedelta(days=1))
    assert len(sent) == n  # not again until 2 days before
    await calendar.daily(oid, date(2026, 11, 18))
    assert len(sent) == n + 1
    up = (await client.get("/org/ca/compliance", headers=h["staff"])).json()["items"]
    assert any(i["title"] == "GSTR-3B Oct 2026" for i in up)


async def test_each_part_needs_its_agent(client, team_org):
    _oid, h = await team_org(["ca_compliance_calendar"])
    assert (await client.get("/org/ca/clients", headers=h["owner"])).status_code == 200
    assert (await client.get("/org/ca/filings", headers=h["owner"])).status_code == 404  # no board
    assert (await client.get("/org/ca/compliance", headers=h["owner"])).status_code == 200
    _oid2, h2 = await team_org(["inbox_triage"])
    assert (await client.get("/org/ca/clients", headers=h2["owner"])).status_code == 404
