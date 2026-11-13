"""Excel cleaner (docs/PLAN-CA-DESK-2.md #1): header found, junk rows removed, numbers / dates / codes made clean, duplicates
removed, similar names grouped, every change logged; the API, the sample and the Excel download."""
import io

from agentry.automations.ca import cleaner
from agentry.automations.ca.taxdocs import SAMPLES


def test_sample_register():
    r = cleaner.compute((SAMPLES / "messy_sales_register_sample.csv").read_bytes(), "text/csv")
    assert r["summary"]["rows_in"] == 10 and r["summary"]["rows_out"] == 7
    assert r["columns"][0] == "Date" and "Party GSTIN" in r["columns"]
    whats = " | ".join(c["what"] for c in r["changes"])
    assert "Exact duplicate rows removed" in whats and "Numbers stored as text" in whats
    assert any(i["value"] == "27AABCS1429B1ZX" and "GSTIN" in i["problem"] for i in r["issues"])
    assert r["name_groups"][0]["use"] == "Sharma Traders Pvt Ltd" and "SHARMA TRADERS" in r["name_groups"][0]["variants"]
    amount = r["columns"].index("Amount")
    assert -2360 in [row[amount] for row in r["rows"]]  # "2,360.00 Cr" is negative
    assert all(not str(row[0]).lower().startswith("total") for row in r["rows"])


def test_rules():
    rows = [["ABC Traders", "", ""], ["Sales register Apr-Jun", "", ""],
            ["Date", "Party", "Debit", "Credit", "Phone", "PAN"],
            ["13/04/2026", "Kumar & Co", "1,000", "", "98100 00022", "aakfm1234l"],
            ["", "", "", "", "", ""],
            ["Date", "Party", "Debit", "Credit", "Phone", "PAN"],  # page break
            ["46302", "KUMAR AND CO.", "", "(500)", "09810000023", "ABC"],
            ["Grand Total", "", "1,000", "500", "", ""]]
    r = cleaner.clean(rows)
    assert r["summary"]["rows_out"] == 2 and r["summary"]["header_row"] == 3
    c = {n: i for i, n in enumerate(r["columns"])}
    first, second = r["rows"]
    assert first[c["Date"]] == "2026-04-13" and second[c["Date"]] == "2026-10-07"  # Excel serial
    assert first[c["Phone"]] == "+919810000022" and first[c["PAN"]] == "AAKFM1234L"
    assert any(i["column"] == "PAN" and i["value"] == "ABC" for i in r["issues"])
    signed = next(k for k in c if k.startswith("Amount (Dr"))
    assert first[c[signed]] == 1000
    assert cleaner.clean(rows, standardise_names=True)["rows"][1][c["Party"]] == cleaner.clean(rows, standardise_names=True)["rows"][0][c["Party"]]


def test_month_first_column():
    r = cleaner.clean([["Date", "Amt"], ["04/13/2026", "1"], ["05/02/2026", "2"]])
    assert [x[0] for x in r["rows"]] == ["2026-04-13", "2026-05-02"]  # a day above 12 in the second part: month first


async def test_api_sample_and_sheet(client, team_org):
    _oid, h = await team_org(["excel_desk"])
    assert (await client.post("/org/ca/excel/clean/sample", headers=h["viewer"])).status_code == 403
    s = await client.post("/org/ca/excel/clean/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    assert s.json()["agent"] == "excel_cleaner"
    up = await client.post("/org/ca/excel/clean", headers=h["owner"], data={"standardise_names": "true"},
                           files={"file": ("m.csv", (SAMPLES / "messy_sales_register_sample.csv").read_bytes(), "text/csv")})
    assert up.status_code == 201, up.text
    assert (await client.post("/org/ca/excel/clean", headers=h["owner"], files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})).status_code == 422
    items = (await client.get("/org/ca/excel", headers=h["owner"])).json()["items"]
    assert len(items) == 2
    x = await client.get(f"/org/ca/work/{up.json()['id']}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200
    from openpyxl import load_workbook
    assert load_workbook(io.BytesIO(x.content)).sheetnames == ["Cleaned", "Changes", "To check", "Similar names"]


async def test_website_box(client):
    s = (await client.get("/public/playground/excel-clean/sample")).json()
    r = (await client.post("/public/playground/excel-clean", headers={"x-forwarded-for": "203.0.113.77"}, json={"input": {**s, "standardise_names": True}})).json()
    assert r["summary"]["rows_out"] == 7 and r["name_groups"] and r["issue_count"] == 2
    src = (await client.get("/public/sources/ca-excel-cleaner")).json()
    assert "fixed rules" in src["basis"]
