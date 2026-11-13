"""GSTR-1 preparation (docs/PLAN-CA-DESK-2.md #4): the sample October register into B2B / B2CL / B2CS / CDNR / CDNUR / EXP /
HSN (B2B, B2C) / docs, every planted problem found, the offline tool layout, the API on a client, the website box."""
import io

from openpyxl import load_workbook

from agentry.automations.ca import gstr1
from agentry.automations.ca.taxdocs import SAMPLES

REG = (SAMPLES / "sales_register_oct_sample.csv").read_bytes()
MEHTA = "27AAKFM1234L1Z5"


def test_sample_register_into_tables():
    r = gstr1.compute(REG, "text/csv", client_gstin=MEHTA)
    t = r["tables"]
    assert r["period"] == "Oct 2026" and r["client_state"] == "27-Maharashtra"
    assert {row[2] for row in t["b2b"]} >= {"MT/26-27/101", "MT/26-27/103", "MT/26-27/111"}
    assert [row[0] for row in t["b2cl"]] == ["MT/26-27/106"]  # Tamil Nadu, unregistered, above ₹1 lakh
    b2cs = {(row[1], row[3]): row[4] for row in t["b2cs"]}
    assert b2cs[("07-Delhi", 18.0)] == 4200 and b2cs[("27-Maharashtra", 18.0)] == 27500  # walk-in + the invalid-GSTIN buyer
    assert {row[0] for row in t["exp"]} == {"WOPAY", "WPAY"} and all(row[4] == "INNSA1" for row in t["exp"])
    assert [(row[2], row[4]) for row in t["cdnr"]] == [("CN/26-27/07", "C"), ("DN/26-27/02", "D")]
    assert t["cdnur"][0][:2] == ["B2CL", "CN/26-27/08"]  # a note against a B2CL invoice, though its own value is small
    assert t["docs"][0] == ["Invoices for outward supply", "MT/26-27/100", "MT/26-27/118", 19, 1]  # 110 missing: cancelled
    assert any(h[0] == "73181500" and h[2] == "NOS" for h in t["hsn_b2b"]) and any(h[5] == 0.0 for h in t["hsn_b2c"])  # export at 0%
    problems = {(i["invoice"], i["severity"]): i["problem"] for i in r["issues"]}
    assert "IGST" in problems[("MT/26-27/112", "high")]
    assert "GSTIN not valid" in problems[("MT/26-27/114", "high")]
    assert "used twice" in problems[("MT/26-27/116", "high")]
    assert "outside Oct 2026" in problems[("MT/26-27/100", "high")]
    assert "isn't taxable + tax" in problems[("MT/26-27/116", "medium")]
    assert "removed from 22 Sep 2025" in problems[("MT/26-27/113", "medium")]
    assert any("MT/26-27/110" in i["value"] for i in r["issues"])
    a = r["totals"]["all"]
    assert a["count"] == 22 and a["cgst"] == a["sgst"]


def test_layout_and_rules():
    r = gstr1.compute(REG, "text/csv", client_gstin=MEHTA, period="October 2026")
    wb = load_workbook(io.BytesIO(gstr1.sheet(r)))
    assert wb.sheetnames[:9] == ["b2b", "b2cl", "b2cs", "cdnr", "cdnur", "exp", "hsn(b2b)", "hsn(b2c)", "docs"]
    assert wb["b2b"]["A4"].value == "GSTIN/UIN of Recipient" and wb["b2b"]["C5"].value == "MT/26-27/101"
    rows = [["Date", "Invoice No", "Customer", "GSTIN", "Place of Supply", "Taxable Value", "IGST", "CGST", "SGST"],
            ["05/11/2026", "A-1", "X", "", "Karnataka", "150000", "27000", "", ""],
            ["06/11/2026", "A-2", "Y", "", "29", "50000", "9000", "", ""],
            ["07/11/2026", "A/1234567890123456", "Z", "", "Maharashtra", "100", "", "9", "9"]]
    r = gstr1.prepare(rows, client_gstin=MEHTA)
    assert [x[0] for x in r["tables"]["b2cl"]] == ["A-1"] and {x[1] for x in r["tables"]["b2cs"]} == {"27-Maharashtra", "29-Karnataka"}
    assert any("16 characters" in i["problem"] for i in r["issues"])


async def test_api_on_a_client(client, team_org):
    _oid, h = await team_org(["ca_gst_reconciliation", "ca_filing_tracker"])
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Traders", "kind": "firm", "gstin": MEHTA})).json()["id"]
    assert (await client.post(f"/org/ca/clients/{cid}/gstr1/sample", headers=h["viewer"])).status_code == 403
    s = await client.post(f"/org/ca/clients/{cid}/gstr1/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    assert s.json()["agent"] == "ca_gstr1" and s.json()["title"] == "GSTR-1 Oct 2026"
    up = await client.post(f"/org/ca/clients/{cid}/gstr1", headers=h["finance"], data={"period": "Oct 2026"}, files={"file": ("sales.csv", REG, "text/csv")})
    assert up.status_code == 201, up.text
    x = await client.get(f"/org/ca/work/{up.json()['id']}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200 and "b2cs" in load_workbook(io.BytesIO(x.content)).sheetnames
    _o2, h2 = await team_org(["ca_filing_tracker"])
    assert (await client.post(f"/org/ca/clients/{cid}/gstr1/sample", headers=h2["owner"])).status_code in (403, 404)


async def test_website_box(client):
    s = (await client.get("/public/playground/gstr1/sample")).json()
    r = await client.post("/public/playground/gstr1", headers={"x-forwarded-for": "203.0.113.80"}, json={"input": s})
    assert r.status_code == 200, r.text
    assert r.json()["tables"]["b2cl"] and r.json()["summary"] == gstr1.compute(REG, "text/csv", client_gstin=MEHTA)["summary"]
    src = (await client.get("/public/sources/ca-gstr1")).json()
    assert src["official"] and any("B2CL" in i["label"] for i in src["items"])
