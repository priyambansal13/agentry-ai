"""Official due-date changes (automations/ca/due_dates.py): the calendar's new rules and sources, the check of official
sources (stand-ins for the sites and the search), verification, staff approval moving every firm's cards, withdrawing,
and a firm's "check for updates"."""
from datetime import date

import pytest
from sqlalchemy import text

from agentry.automations.ca import calendar, due_dates
from agentry.db import system_session, tenant_session

CAL = ["ca_filing_tracker", "ca_compliance_calendar"]
NOTICE = ("Order under section 119: the due date for furnishing return of income for Assessment Year 2026-27, which is 31st July, 2026, "
          "is hereby extended to 15th September, 2026. Circular No. 9/2026 dated 20.07.2026.")


@pytest.fixture(autouse=True)
async def clean():
    async with system_session() as conn:
        await conn.execute(text("delete from app.due_date_updates; delete from app.due_date_syncs"))
    yield
    async with system_session() as conn:
        await conn.execute(text("delete from app.due_date_updates; delete from app.due_date_syncs"))


def test_new_rules_and_sources():
    # quarterly GSTR-3B: 22nd in Maharashtra, 24th in Uttar Pradesh (from the GSTIN)
    mh = calendar.deadlines("firm", {"gst": True, "gst_qrmp": True}, date(2027, 1, 1), date(2027, 1, 31), gstin="27AAKFM1234L1Z5")
    up = calendar.deadlines("firm", {"gst": True, "gst_qrmp": True}, date(2027, 1, 1), date(2027, 1, 31), gstin="09AAKFM1234L1Z5")
    assert [d["due_on"].day for d in mh if d["kind"] == "gstr3b"] == [22] and [d["due_on"].day for d in up if d["kind"] == "gstr3b"] == [24]
    # AGM date entered: AOC-4 30 days and MGT-7 60 days after it
    roc = calendar.deadlines("company", {"agm_on": {"2025-26": "2026-09-10"}}, date(2026, 10, 1), date(2026, 11, 30))
    assert {(d["kind"], d["due_on"]) for d in roc} >= {("roc_aoc4", date(2026, 10, 10)), ("roc_mgt7", date(2026, 11, 9))}
    guessed = calendar.deadlines("company", {}, date(2026, 10, 1), date(2026, 11, 30))
    assert next(d for d in guessed if d["kind"] == "roc_aoc4")["note"].startswith("Assumes the AGM")
    # TCS, composition, transfer pricing
    more = calendar.deadlines("company", {"tcs": True, "gst": True, "gst_composition": True, "transfer_pricing": True}, date(2026, 10, 1), date(2026, 11, 30))
    kinds = {(d["kind"], d["due_on"]) for d in more}
    assert {("tcs_27eq", date(2026, 10, 15)), ("gst_cmp08", date(2026, 10, 18)), ("form_3ceb", date(2026, 10, 31)), ("itr", date(2026, 11, 30))} <= kinds
    assert not any(k == "gstr3b" for k, _ in kinds)  # composition dealers don't file GSTR-3B
    assert all(d["source"]["type"] == "standard" and d["source"]["label"].startswith("Standard due date") for d in more)


def test_an_active_change_moves_the_date_and_becomes_its_source():
    upd = [{"id": "u1", "kind": "itr", "period": "AY 2026-27", "original_on": date(2026, 7, 31), "due_on": date(2026, 9, 15),
            "source": "Circular No. 9/2026", "source_url": "https://incometaxindia.gov.in/c9.pdf"}]
    plain = calendar.deadlines("individual", {}, date(2026, 7, 1), date(2026, 9, 30), updates=upd)
    assert [(d["due_on"], d["source"]["type"], d["standard_on"]) for d in plain if d["kind"] == "itr"] == [(date(2026, 9, 15), "extension", date(2026, 7, 31))]
    audited = calendar.deadlines("individual", {"audit": True}, date(2026, 10, 1), date(2026, 10, 31), updates=upd)
    assert [d["due_on"] for d in audited if d["kind"] == "itr"] == [date(2026, 10, 31)]  # the audit-case date isn't the one extended


def test_dates_are_found_in_the_page_text():
    assert due_dates.mentions(NOTICE, date(2026, 9, 15)) and due_dates.mentions("extended till 15.09.2026", date(2026, 9, 15))
    assert not due_dates.mentions(NOTICE, date(2026, 9, 30))
    assert due_dates.official("https://www.incometaxindia.gov.in/x.pdf") and not due_dates.official("https://taxguru.in/x")


async def test_check_verify_approve_and_withdraw(client, team_org, monkeypatch):
    oid, h = await team_org(CAL)
    await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Priya Sharma", "phone": "+919810000011", "profile": {"salaried": True}})
    async with tenant_session(oid) as conn:
        assert await calendar.put_on_board(conn, oid, date(2026, 7, 1), 45) >= 1
        await conn.execute(text("update app.ca_filings set data = jsonb_set(data, '{reminded}', '[7]') where kind = 'itr'"))

    async def pages(cands, today, read=None):
        itr = next(c for c in cands if c["kind"] == "itr" and c["standard_on"] == date(2026, 7, 31))
        return ([{"id": itr["id"], "old_date": "2026-07-31", "new_date": "2026-09-15", "source": "Circular No. 9/2026",
                  "source_url": "https://incometaxindia.gov.in/c9.pdf", "quote": "furnishing return of income for Assessment Year 2026-27, which is 31st July, 2026, is hereby extended to 15th September, 2026"},
                 {"id": itr["id"], "old_date": "2026-07-31", "new_date": "2026-08-31", "source": "a blog", "source_url": "https://taxblog.example/itr",
                  "quote": "ITR due date extended to 31 August"},
                 {"id": itr["id"], "old_date": "2026-07-31", "new_date": "2026-08-15", "source": "x", "source_url": "https://incometaxindia.gov.in/x",
                  "quote": "DIR-3 KYC extended to 15 August"},  # the words are about another filing: dropped
                 {"id": itr["id"], "old_date": "2026-10-31", "new_date": "2026-11-21", "source": "x", "source_url": "https://incometaxindia.gov.in/x"},  # another date
                 {"id": itr["id"], "old_date": "2026-07-31", "new_date": "2026-07-15", "source": "x", "source_url": "https://incometaxindia.gov.in/x"},  # earlier
                 {"id": 99999, "old_date": "2026-07-31", "new_date": "2026-09-01", "source": "x", "source_url": "https://gst.gov.in/x"}],  # not a calendar date
                [{"name": "Income Tax", "url": "https://incometaxindia.gov.in", "ok": True, "note": None}])

    async def search(cands, today):
        return [], {"name": "Web search of official sites", "url": None, "ok": False, "note": "no search engine configured"}

    async def read_page(url):
        return NOTICE
    async def no_pages():
        return [], []
    monkeypatch.setattr(due_dates, "read_sources", no_pages)
    monkeypatch.setattr(due_dates, "from_pages", pages)
    monkeypatch.setattr(due_dates, "from_search", search)
    monkeypatch.setattr(due_dates, "read_page", read_page)
    r = await due_dates.run_sync(None, "staff", today=date(2026, 7, 21))
    assert r["status"] == "done" and r["proposed"] == 2

    staff = {"Authorization": "Bearer admin@agentry.dev"}
    hq = (await client.get("/hq/due-dates", headers=staff)).json()
    good = next(u for u in hq["updates"] if u["source_url"].startswith("https://incometaxindia"))
    blog = next(u for u in hq["updates"] if "taxblog" in u["source_url"])
    assert good["checks"]["official"] and good["checks"]["date_on_page"] and good["checks"]["quote_on_page"] and good["status"] == "proposed"
    assert not blog["checks"]["official"] and "isn't a government site" in blog["checks"]["note"]
    assert (await client.get("/hq/due-dates", headers=h["owner"])).status_code == 403  # staff only

    # nothing moves until staff approve; then the firm's open card follows, with its source, and reminders restart
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select due_on from app.ca_filings where kind = 'itr'"))).scalar_one() == date(2026, 7, 31)
    a = (await client.post(f"/hq/due-dates/{good['id']}/approve", headers=staff)).json()
    assert a["status"] == "active" and a["cards"] == 1
    async with tenant_session(oid) as conn:
        due, data = (await conn.execute(text("select due_on, data from app.ca_filings where kind = 'itr'"))).one()
    assert due == date(2026, 9, 15) and data["extension"]["label"] == "Circular No. 9/2026" and "reminded" not in data
    up = (await client.get("/org/ca/compliance?days=120", headers=h["staff"])).json()["items"]
    assert next(i for i in up if i["kind"] == "itr")["extension"]["was"] == "2026-07-31"
    firm = (await client.get("/org/ca/compliance/updates", headers=h["staff"])).json()
    assert len(firm["active"]) == 1 and firm["pending"] == 1 and firm["last_check"]["status"] == "done"
    await client.post(f"/hq/due-dates/{blog['id']}/reject", headers=staff)

    # withdrawn: back to the standard date
    await client.post(f"/hq/due-dates/{good['id']}/withdraw", headers=staff)
    async with tenant_session(oid) as conn:
        due, data = (await conn.execute(text("select due_on, data from app.ca_filings where kind = 'itr'"))).one()
    assert due == date(2026, 7, 31) and "extension" not in data


async def test_staff_enter_a_change_by_hand(client, team_org):
    await team_org(CAL)  # signs in the test users, Agentry staff among them
    staff = {"Authorization": "Bearer admin@agentry.dev"}
    r = await client.post("/hq/due-dates", headers=staff, json={"kind": "gstr9", "period": "FY 2025-26", "original_on": "2026-12-31",
                                                               "due_on": "2027-02-28", "source": "Notification No. 3/2027-Central Tax",
                                                               "source_url": "https://cbic-gst.gov.in/n3.pdf"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["found_by"] == "staff"
    assert (await client.post("/hq/due-dates", headers=staff, json={"kind": "nope", "period": "FY 2025-26", "original_on": "2026-12-31",
                                                                   "due_on": "2027-02-28", "source": "x x x x"})).status_code == 422


async def test_firm_check_reuses_a_recent_one(client, team_org):
    _oid, h = await team_org(CAL)
    first = (await client.post("/org/ca/compliance/updates/check", headers=h["owner"])).json()
    assert first["status"] == "running" and not first["reused"]
    again = (await client.post("/org/ca/compliance/updates/check", headers=h["manager"])).json()
    assert again["reused"] and again["id"] == first["id"]
    assert (await client.post("/org/ca/compliance/updates/check", headers=h["viewer"])).status_code == 403


# ---------- official figures (official_rules.py) ----------

@pytest.fixture
async def clean_rules():
    from agentry import official_rules
    async with system_session() as conn:
        await conn.execute(text("delete from app.rule_updates"))
    await official_rules.refresh()
    yield
    async with system_session() as conn:
        await conn.execute(text("delete from app.rule_updates"))
    await official_rules.refresh()


async def test_a_figure_change_is_verified_approved_used_and_withdrawn(client, team_org, monkeypatch, clean_rules):
    from agentry import official_rules
    from agentry.automations.ca import tds
    _oid, h = await team_org(["ca_tds_returns", "ca_compliance_calendar"])
    staff = {"Authorization": "Bearer admin@agentry.dev"}
    page = ("Standard deduction of Rs.50,000 is available from AY 2024-25. Notification No. 41/2026: with effect from 1 April 2026 the threshold for deduction under section 194J for fees for "
            "professional services is increased to ₹60,000. Diwali (Deepavali) falls on 17 October 2028.")
    cands = due_dates.rule_candidates()
    cid = {c["key"]: c["id"] for c in cands}
    raw = [{"id": cid["tds.194J(b).threshold"], "old_value": 50000, "new_value": 60000, "applies_from": "FY 2026-27", "source": "Notification No. 41/2026",
            "source_url": "https://incometaxindia.gov.in/n41.pdf", "quote": "with effect from 1 April 2026 the threshold for deduction under section 194J for fees for professional services is increased to ₹60,000"},
           {"id": cid["tds.194H.threshold"], "old_value": 20000, "new_value": 60000, "source": "x", "source_url": "https://incometaxindia.gov.in/n41.pdf",
            "quote": "threshold under section 194J is increased to ₹60,000"},  # the words are about another section: dropped
           {"id": cid["itr.std_new"], "old_value": 50000, "new_value": 100000, "source": "x", "source_url": "https://incometaxindia.gov.in/x",
            "quote": "standard deduction of 1,00,000"},  # the old value isn't the one in force: dropped
           {"id": cid["itr.std_new"], "old_value": 75000, "new_value": 50000, "source": "an old FAQ", "source_url": "https://incometax.gov.in/faq",
            "quote": "Standard deduction of Rs.50,000 is available from AY 2024-25"},  # an old page: applies before the figures' year, dropped
           {"id": cid["festival.diwali.2028"], "old_value": None, "new_value": "2028-10-17", "source": "Holiday list 2028",
            "source_url": "https://dopt.gov.in/holidays-2028.pdf", "quote": "Diwali (Deepavali) falls on 17 October 2028"}]

    async def read_page(url):
        return page
    monkeypatch.setattr(due_dates, "read_page", read_page)
    found = [v for v in [await due_dates.verify_rule(c, {c["id"]: c for c in cands}) for c in raw] if v]
    assert [f["key"] for f in found] == ["tds.194J(b).threshold", "festival.diwali.2028"]
    assert all(f["checks"]["official"] and f["checks"]["value_on_page"] and f["checks"]["quote_on_page"] for f in found)
    await due_dates.propose_rules(found)

    hq = (await client.get("/hq/due-dates/rules", headers=staff)).json()
    j = next(u for u in hq["updates"] if u["key"] == "tds.194J(b).threshold")
    assert j["status"] == "proposed" and j["title"] == "194J(b) Professional fees: threshold: ₹50,000 → ₹60,000"
    rows = [["Deductee Name", "PAN", "Section", "Date of payment", "Amount paid", "TDS deducted"], ["Ravi Kumar", "ABCPK9999Z", "194J", "12/07/2026", "55000", "0"]]
    assert tds.check(tds.parse(rows))["issues"]  # nothing changes before approval: ₹55,000 is over ₹50,000
    assert (await client.post(f"/hq/due-dates/rules/{j['id']}/approve", headers=staff)).json()["status"] == "active"
    assert official_rules.get("tds.194J(b).threshold") == 60000
    assert not tds.check(tds.parse(rows))["issues"]  # under the new threshold
    fig = (await client.get("/org/ca/rules", headers=h["owner"])).json()["figures"]
    row = next(f for f in fig if f["key"] == "tds.194J(b).threshold")
    assert row["shown"] == "₹60,000" and row["update"]["source"] == "Notification No. 41/2026"

    d = next(u for u in hq["updates"] if u["key"] == "festival.diwali.2028")
    await client.post(f"/hq/due-dates/rules/{d['id']}/approve", headers=staff)
    from agentry.automations.festivals import festival_on
    assert str(festival_on("diwali", 2028)) == "2028-10-17"

    await client.post(f"/hq/due-dates/rules/{j['id']}/withdraw", headers=staff)
    assert official_rules.get("tds.194J(b).threshold") == 50000


async def test_staff_set_a_figure_by_hand(client, team_org, clean_rules):
    from agentry import official_rules
    from agentry.automations.ca import itr
    await team_org(["ca_itr_prep"])
    staff = {"Authorization": "Bearer admin@agentry.dev"}
    before = itr.compute({"salary_gross": 1500000}, "new")["tax_liability"]
    r = await client.post("/hq/due-dates/rules", headers=staff, json={"key": "itr.std_new", "new_value": "100000", "applies_from": "FY 2026-27",
                                                                     "source": "Finance Act, 2026", "source_url": "https://indiabudget.gov.in/fa.pdf"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert official_rules.get("itr.std_new") == 100000
    assert itr.compute({"salary_gross": 1500000}, "new")["tax_liability"] < before  # a bigger deduction, less tax
    assert (await client.post("/hq/due-dates/rules", headers=staff, json={"key": "itr.std_new", "new_value": "100000",
                                                                         "source": "Finance Act, 2026"})).status_code == 422  # already in force
    assert (await client.post("/hq/due-dates/rules", headers=staff, json={"key": "nope", "new_value": "1", "source": "xxxx"})).status_code == 422
