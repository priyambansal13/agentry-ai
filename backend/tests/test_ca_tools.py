"""CA Firm pack, agents 5-13 (docs/PACKS.md): GST reconciliation, ITR preparation, capital gains, bank statements,
notices, TDS returns, tax audit (3CD), recurring entries, Excel desk."""
from datetime import date

from sqlalchemy import text

from agentry.automations.ca import audit3cd, capgains, core, excel, gst, itr, recurring, tds
from agentry.automations.ca.taxdocs import SAMPLES
from agentry.db import tenant_session

TOOLS = ["ca_filing_tracker", "ca_document_chaser", "ca_tax_docs_reader", "ca_gst_reconciliation", "ca_itr_prep", "ca_capital_gains",
         "ca_bank_classifier", "ca_notice_handler", "ca_tds_returns", "ca_tax_audit", "excel_desk"]


async def _client(client, h, **extra) -> str:
    body = {"name": "Mehta Traders", "kind": "firm", "pan": "AAKFM1234L", "gstin": "27AAKFM1234L1Z5", "phone": "+919810000022"} | extra
    r = await client.post("/org/ca/clients", headers=h["owner"], json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_gst_reconciliation(client, team_org):
    _oid, h = await team_org(TOOLS)
    cid = await _client(client, h)
    r = await client.post(f"/org/ca/clients/{cid}/gst/sample", headers=h["finance"])
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    status = {(x["books"] or x["gstr2b"])["invoice"]: x["status"] for x in res["rows"]}
    assert status["SP/1187"] == "matched"            # SP/1187 vs SP/1187/26-27 in 2B: the year suffix is ignored
    assert status["BST-457"] == "matched"            # BST-0457 in 2B
    assert status["ME/2026/118"] == "missing_in_2b"  # the supplier hasn't filed
    assert status["KL/889"] == "amount_differs" and status["ROS-3321"] == "gstin_differs"
    assert res["itc_at_risk"] == 6900 and res["messages"][0]["supplier"] == "Mehul Electricals"
    assert "GSTIN 27AAKFM1234L1Z5" in res["messages"][0]["message"]
    # uploaded files: a portal-style CSV 2B against the register
    two_b = "GSTIN of supplier,Trade/Legal name,Invoice number,Invoice date,Taxable Value (₹),Integrated Tax(₹),Central Tax(₹),State/UT Tax(₹)\n" \
            "27ABCPM5544K1Z8,Mehul Electricals,ME/2026/118,28-10-2026,30000,0,2700,2700\n"
    r = await client.post(f"/org/ca/clients/{cid}/gst", headers=h["owner"], data={"period": "Oct 2026"},
                          files={"gstr2b": ("2b.csv", two_b.encode(), "text/csv"), "books": ("pr.csv", (SAMPLES / "purchase_register_sample.csv").read_bytes(), "text/csv")})
    assert r.status_code == 201, r.text
    assert r.json()["result"]["totals"]["matched"]["count"] == 1
    x = await client.get(f"/org/ca/work/{r.json()['id']}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert (await client.post(f"/org/ca/clients/{cid}/gst/sample", headers=h["viewer"])).status_code == 403


def test_tax_both_regimes():
    p = {"salary_gross": 1840000, "exempt_allowances": 120000, "professional_tax": 2400, "d_80c": 150000, "d_80d": 25000,
         "interest_deposit": 52310, "interest_savings": 6842, "dividend": 8400, "tds": 241500}
    r = itr.prepare(p)
    assert r["old"]["tax_liability"] == 289633 and r["new"]["tax_liability"] == 173171 and r["better"] == "new"
    assert r["new"]["refund"] == 68329 and r["itr_form"] == "ITR-1 (Sahaj)"
    assert itr.compute({"salary_gross": 1275000}, "new")["tax_liability"] == 0          # ₹12 lakh after the standard deduction
    assert itr.compute({"salary_gross": 1300000}, "new")["tax_liability"] == 26000      # marginal relief: ₹25,000 + cess
    assert itr.compute({"salary_gross": 550000}, "old")["tax_liability"] == 0           # 87A in the old regime
    cg = itr.compute({"stcg_111a": 100000, "ltcg_112a": 225000}, "new")
    assert cg["special_rate_tax"] == 0  # all inside the ₹4 lakh basic exemption, which is used against special-rate gains first
    cg = itr.compute({"salary_gross": 2000000, "stcg_111a": 100000, "ltcg_112a": 225000}, "new")
    assert cg["special_rate_tax"] == 20000 + 12500 and cg["ltcg_exempt"] == 125000
    assert itr.itr_form({"ltcg_112a": 200000}) == "ITR-2" and itr.itr_form({"business_income": 1}).startswith("ITR-3")


async def test_itr_prefilled_from_documents_and_gains(client, team_org):
    _oid, h = await team_org(TOOLS)
    cid = await _client(client, h, name="Priya Sharma", kind="individual", pan="ABCPS1234K", gstin=None)
    await client.post(f"/org/ca/clients/{cid}/samples", headers=h["owner"])
    await client.post(f"/org/ca/clients/{cid}/capital-gains/sample", headers=h["owner"])
    pre = (await client.get(f"/org/ca/clients/{cid}/itr/prefill", headers=h["owner"])).json()
    i = pre["inputs"]
    assert i["salary_gross"] == 1840000 and i["exempt_allowances"] == 120000 and i["d_80c"] == 150000 and i["interest_deposit"] == 52310
    assert i["tds"] == 241500 + 5231  # what AIS / 26AS shows: only that can be claimed
    assert i["ltcg_112a"] == 94890 and i["stcg_111a"] == 18780
    r = await client.post(f"/org/ca/clients/{cid}/itr", headers=h["owner"], json={"inputs": i})
    assert r.status_code == 201 and r.json()["result"]["itr_form"] == "ITR-2"
    assert (await client.get(f"/org/ca/work/{r.json()['id']}/sheet.xlsx", headers=h["owner"])).status_code == 200


def test_capital_gains_rules():
    r = capgains.compute((SAMPLES / "broker_pnl_sample.csv").read_bytes(), "text/csv")
    rows = {x["name"]: x for x in r["rows"]}
    assert rows["TCS"]["cost"] == 61380 and rows["TCS"]["section"] == "112A"  # grandfathered at the 31 Jan 2018 FMV
    assert rows["ITC"]["flags"] and rows["ITC"]["cost"] == 72300               # no FMV given: flagged, cost as is
    assert rows["HDFCBANK"]["section"] == "111A"
    assert rows["HDFC Liquid Fund - Direct Growth"]["section"] == "slab (50AA)"  # a debt fund bought after Apr 2023
    assert r["summary"]["ltcg_112a"] == 94890 and r["summary"]["stcg_111a"] == 18780
    old = capgains.classify({"name": "INFY", "type": "equity", "buy_date": date(2023, 1, 2), "sell_date": date(2024, 6, 1), "buy_value": 100.0,
                             "sell_value": 150.0, "fmv_2018": None})
    assert old["after_cutoff"] is False and old["section"] == "112A"


async def test_bank_statement_and_learning(client, team_org):
    oid, h = await team_org(TOOLS)
    cid = await _client(client, h)
    r = await client.post(f"/org/ca/clients/{cid}/bank/sample", headers=h["owner"])
    assert r.status_code == 201, r.text
    w = r.json()
    t = w["result"]["totals"]
    lines = {ln["narration"][:20]: ln for ln in w["result"]["lines"]}
    assert lines["GST CPIN 26102700012"]["category"] == "GST paid" and lines["ACH D- HDFC LTD-LOAN"]["category"] == "Loan EMI"
    assert t["cash_receipts"] == 250000 and any("269ST" in f for f in t["flags"])
    assert t["receipts"] == 48500 + 250000 + 72000  # not the interest
    rahul = next(ln for ln in w["result"]["lines"] if "RAHUL MEHTA" in ln["narration"])
    r = await client.post(f"/org/ca/work/{w['id']}/bank-line", headers=h["owner"], json={"row": rahul["row"], "category": "Drawings / personal"})
    assert r.json()["learned"] == "RAHUL MEHTA" and r.json()["totals"]["by_category"]["Drawings / personal"]["out"] == 15000
    again = (await client.post(f"/org/ca/clients/{cid}/bank/sample", headers=h["owner"])).json()  # the next statement uses the rule
    assert next(ln for ln in again["result"]["lines"] if "RAHUL MEHTA" in ln["narration"])["by"] == "rule"
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select category from app.ca_bank_rules"))).scalar_one() == "Drawings / personal"


async def test_notice_becomes_a_card_with_its_documents(client, team_org):
    oid, h = await team_org(TOOLS)
    cid = await _client(client, h, name="Priya Sharma", kind="individual", pan="ABCPS1234K", gstin=None)
    r = await client.post(f"/org/ca/clients/{cid}/notices/sample", headers=h["staff"])
    assert r.status_code == 201, r.text
    n = r.json()
    assert n["section"] == "143(1)(a)" and n["respond_by"] == "2026-11-11" and n["demand"] == 19840 and n["flags"] == []
    assert len(n["quotes"]) == 5
    card = (await client.get(f"/org/ca/filings?client_id={cid}", headers=h["owner"])).json()["items"][0]
    assert card["kind"] == "notice_reply" and card["due_on"] == "2026-11-06"  # 5 days before the deadline
    assert "FD interest certificates for FY 2024-25" in card["missing"]
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.approvals where kind = 'ca_task' and title like '%143(1)(a)%'"))).scalar_one() == 1


def test_a_notice_value_not_in_the_text_is_dropped():
    body = "Intimation u/s 143(1)(a). DIN: CPC/2526/A6/123456789. Respond on or before 11/11/2026. Demand of Rs. 19,840."
    out, flags = __import__("agentry.automations.ca.notices", fromlist=["verify"]).verify(
        {"respond_by": "2026-11-21", "demand": 25000, "din": "CPC/2526/A6/999", "quotes": ["Demand of Rs. 19,840.", "made up"]}, body)
    assert out["respond_by"] is None and out["demand"] == 0 and out["din"] is None and out["quotes"] == ["Demand of Rs. 19,840."]
    assert len(flags) == 3


def test_tds_checks():
    r = tds.compute((SAMPLES / "tds_register_sample.csv").read_bytes(), "text/csv")
    by = {(i["name"], i["row"]): " ".join(i["problems"]) for i in r["issues"]}
    assert "1.5%" in by[("Sunrise Properties", 4)]            # deposited 10 Sep, due 7 Sep
    assert "should be ₹500" in by[("Anil Sharma", 5)]          # 194H at 2%
    assert "206AA" in by[("Neha Verma", 6)]
    assert "should be ₹250" in by[("Priya Iyer", 7)]           # 194C: ₹1.15 lakh in the year crosses ₹1 lakh
    assert "deducted 1 month(s) late" in by[("Priya Iyer", 8)]
    assert ("Kumar Logistics", 2) not in by and ("Ravi Kumar", 3) not in by
    assert tds.due_date(date(2027, 3, 31)) == date(2027, 4, 30) and tds.months_part(date(2026, 8, 1), date(2026, 9, 10)) == 2
    assert r["summary"][0]["form"] == "26Q" and r["summary"][0]["quarter"] == "Q2 FY 2026-27"


def test_tax_audit_clauses():
    r = audit3cd.compute((SAMPLES / "ledger_sample.csv").read_bytes(), "text/csv", 2025)
    c = {x["clause"]: x for x in r["clauses"]}
    assert c["40A(3)"]["disallow"] == 14500             # two cash payments the same day
    assert "40A(3)" in c and all(i["party"] != "Speedway Transport" for i in c["40A(3)"]["items"])  # transporter limit ₹35,000
    assert c["43B"]["disallow"] == 48500 and c["36(1)(va)"]["disallow"] == 22400
    assert {i["party"] for i in c["43B(h)"]["items"]} == {"Mehul Electricals", "Shree Packaging"}  # Sai paid within 15 days
    assert c["269ST"]["items"][0]["amount"] == 250000 and c["269SS/269T"]["items"][0]["party"] == "Rohan Kapoor"
    assert c["40(a)(ia)"]["disallow"] == 36000 and r["disallowance"] == 348400


async def test_audit_and_tds_through_the_portal(client, team_org):
    _oid, h = await team_org(TOOLS)
    cid = await _client(client, h)
    a = await client.post(f"/org/ca/clients/{cid}/audit/sample", headers=h["owner"])
    t = await client.post(f"/org/ca/clients/{cid}/tds/sample", headers=h["owner"])
    assert a.status_code == t.status_code == 201
    assert {w["agent"] for w in (await client.get(f"/org/ca/clients/{cid}/work", headers=h["viewer"])).json()["items"]} == {"ca_tax_audit", "ca_tds_returns"}
    bad = await client.post(f"/org/ca/clients/{cid}/tds", headers=h["owner"], files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 422 and "couldn't find" in bad.json()["detail"]


async def test_recurring_entries_are_booked_once(client, team_org):
    oid, h = await team_org(["bookkeeping", "recurring_books"])
    r = await client.post("/org/ca/recurring", headers=h["owner"], json={"name": "Office rent", "vendor": "Sunrise Properties", "category": "Rent",
                                                                        "amount": 90000, "gst_rate": 18, "frequency": "monthly", "next_on": "2026-08-31"})
    assert r.status_code == 201
    assert await recurring.book_due(oid, date(2026, 10, 31)) == 3  # 31 Aug, 30 Sep, 31 Oct
    assert await recurring.book_due(oid, date(2026, 10, 31)) == 0
    async with tenant_session(oid) as conn:
        docs = (await conn.execute(text("select fields->'date'->>'value', fields->'total'->>'value' from app.documents where source = 'recurring' order by 1"))).all()
    assert [d[0] for d in docs] == ["2026-08-31", "2026-09-30", "2026-10-31"] and float(docs[0][1]) == 106200
    lst = (await client.get("/org/ca/recurring", headers=h["owner"])).json()
    assert lst["items"][0]["next_on"] == "2026-11-30" and lst["monthly_cost"] == 106200
    assert recurring.step(date(2026, 1, 31), "monthly", 31) == date(2026, 2, 28) and recurring.step(date(2026, 2, 28), "monthly", 31) == date(2026, 3, 31)


async def test_excel_desk(client, team_org):
    _oid, h = await team_org(["excel_desk"])
    r = await client.post("/org/ca/excel/ask", headers=h["owner"], data={"question": "total TDS for 194C"},
                          files={"file": ("tds.csv", (SAMPLES / "tds_register_sample.csv").read_bytes(), "text/csv")})
    assert r.status_code == 201, r.text
    t = await client.post("/org/ca/excel/table", headers=h["owner"], files={"file": ("ais.txt", (SAMPLES / "ais_sample.txt").read_bytes(), "text/plain")})
    assert t.status_code == 201 and t.json()["result"]["columns"][0] == "SR. NO." and all(t.json()["result"]["checked"])
    pr = (SAMPLES / "purchase_register_sample.csv").read_bytes()
    lines = pr.decode().splitlines()
    second = "\n".join([lines[0], lines[1], lines[2].replace("23600", "23000"), lines[3]]).encode()
    rec = await client.post("/org/ca/excel/reconcile", headers=h["owner"], files={"first": ("a.csv", pr, "text/csv"), "second": ("b.csv", second, "text/csv")})
    counts = rec.json()["result"]["counts"]
    assert counts == {"matched": 2, "amount_differs": 1, "only_first": 3, "only_second": 0}
    assert len((await client.get("/org/ca/excel", headers=h["owner"])).json()["items"]) == 3
    assert (await client.get(f"/org/ca/work/{rec.json()['id']}/sheet.xlsx", headers=h["owner"])).content[:2] == b"PK"


def test_sheet_questions_are_computed_by_code():
    rows = core.table_rows((SAMPLES / "tds_register_sample.csv").read_bytes(), "text/csv")
    assert excel.run_query(rows, {"filter": [{"column": "Section", "op": "=", "value": "194C"}], "agg": "sum", "measure": "TDS deducted"})["value"] == 2600
    top = excel.run_query(rows, {"group_by": "Deductee Name", "agg": "sum", "measure": "Amount paid", "top": 1})
    assert top["groups"] == [["Priya Iyer", 115000.0]]
    assert gst.inv_norm("BST-0457") == gst.inv_norm("bst/457") and gst.inv_norm("SP/1187/26-27") == gst.inv_norm("SP-1187")
