"""Anomaly finder (docs/PLAN-CA-DESK-2.md #2): each check on the sample day book (every planted problem found), the edge
rules (cash split on a day, tax type from the firm's GSTIN, Benford), the API on the Excel desk and on a client, the website."""
import io
from datetime import date

from agentry.automations.ca import anomalies
from agentry.automations.ca.taxdocs import SAMPLES

DAYBOOK = (SAMPLES / "purchase_daybook_sample.csv").read_bytes()


def _by_key(r: dict) -> dict:
    return {f["key"]: f for f in r["findings"]}


def test_sample_daybook_every_planted_problem():
    r = anomalies.compute(DAYBOOK, "text/csv", as_of=date(2026, 11, 13))
    f = _by_key(r)
    assert r["columns"]["amount"] == "Amount" and r["columns"]["voucher"] == "Voucher No" and r["fy_start"] == 2026
    assert {x["voucher"] for x in f["possible_duplicate"]["rows"]} >= {"PV-1154", "PV-1155"}
    assert f["exact_duplicate"]["count"] == 1
    assert {x["party"] for x in f["voucher_repeated"]["rows"]} == {"Shree Packaging Pvt Ltd", "Gupta Stationers"}
    assert f["voucher_gap"]["rows"][0]["voucher"] == "PV-1020 to PV-1022"
    cash = {x["party"]: x["note"] for x in f["cash_payment"]["rows"]}
    assert "₹19,600" in cash["Ganesh Hardware"] and "Shiv Transport" in cash  # two ₹9,800 the same day add up
    notes = [x["note"] for x in f["tax_type"]["rows"]]
    assert any("other state (29)" in n for n in notes) and any("same state (27)" in n for n in notes)
    assert f["tax_rate"]["rows"][0]["party"] == "Patel Enterprises"  # 7%
    assert f["gstin_invalid"]["rows"][0]["party"] == "Om Sai Traders"
    assert f["out_of_period"]["rows"][0]["date"] == "2027-04-05"
    assert f["holiday"]["rows"][0]["note"] == "Gandhi Jayanti" and any(x["date"] == "2026-10-04" for x in f["sunday"]["rows"])
    assert f["outlier"]["rows"][0]["party"] == "Gupta Stationers"
    assert r["benford"]["verdict"] == "fits" and "benford" not in f
    sev = [x["severity"] for x in r["findings"]]
    assert sev == sorted(sev, key=anomalies.SEVERITY.get)  # most serious first


def test_rules():
    rows = [["Date", "Voucher No", "Party", "GSTIN", "Taxable", "IGST", "CGST", "SGST", "Amount", "Mode"],
            ["01/05/2026", "R-1", "Walk-in Ravi", "", "", "", "", "", "2,10,000", "Cash receipt"],
            ["02/05/2026", "B-1", "Kaveri Mills", "29AAFCB7707D1ZQ", "1000", "", "90", "90", "1180", "Bank"]]
    f = _by_key(anomalies.find(rows, firm_gstin="27AAKFM1234L1Z5"))
    assert "269ST" in f["cash_receipt"]["why"]
    assert "other state (29)" in f["tax_type"]["rows"][0]["note"]
    f = _by_key(anomalies.find(rows, firm_gstin="29AAKFM1234L1Z5"))  # a Karnataka firm: CGST + SGST is right
    assert "tax_type" not in f
    lopsided = [["Date", "Party", "Amount"], *[[f"0{1 + i % 9}/06/2026", f"P{i}", str(900 + i)] for i in range(120)]]
    r = anomalies.find(lopsided)
    assert r["benford"]["verdict"] == "does not fit" and _by_key(r)["benford"]["severity"] == "medium"  # every amount starts with 9 or 1
    assert any("voucher" in s for s in anomalies.find(lopsided)["skipped"])


async def test_api_desk_client_and_sheet(client, team_org):
    _oid, h = await team_org(["excel_desk", "ca_filing_tracker"])
    assert (await client.post("/org/ca/excel/anomalies/sample", headers=h["viewer"])).status_code == 403
    s = await client.post("/org/ca/excel/anomalies/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    assert s.json()["agent"] == "ca_anomaly_finder" and s.json()["result"]["summary"]["high"] >= 10
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Traders", "kind": "firm", "gstin": "27AAKFM1234L1Z5"})).json()["id"]
    c = await client.post(f"/org/ca/clients/{cid}/anomalies", headers=h["finance"], files={"file": ("daybook.csv", DAYBOOK, "text/csv")})
    assert c.status_code == 201, c.text
    work = (await client.get(f"/org/ca/clients/{cid}/work", headers=h["owner"])).json()["items"]
    assert work[0]["agent"] == "ca_anomaly_finder"
    assert len((await client.get("/org/ca/excel", headers=h["owner"])).json()["items"]) == 1  # the client's run stays on the client
    x = await client.get(f"/org/ca/work/{c.json()['id']}/sheet.xlsx", headers=h["owner"])
    from openpyxl import load_workbook
    assert load_workbook(io.BytesIO(x.content)).sheetnames == ["Findings", "Rows", "Benford"]


async def test_website_box(client):
    s = (await client.get("/public/playground/anomalies/sample")).json()
    assert s["rows"] == 167 and s["preview"][2][0] == "Date"
    r = (await client.post("/public/playground/anomalies", headers={"x-forwarded-for": "203.0.113.78"}, json={"input": {"use_sample": True}})).json()
    assert r["summary"]["high"] >= 10
    src = (await client.get("/public/sources/ca-anomaly-finder")).json()
    assert src["official"] and any("40A(3)" in i["label"] for i in src["items"]) and any("IGST" in i["label"] for i in src["items"])
