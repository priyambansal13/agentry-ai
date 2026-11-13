"""Depreciation (docs/PLAN-CA-DESK-2.md #6): the sample register (Mehta Steel, FY 2025-26) worked out for the books
(Schedule II, straight line) and for tax (WDV by block, half rate under 180 days, cash over ₹10,000 kept out), a sale in
the year, capital work in progress, the deferred tax, a block sold out (section 50), the opening tax WDV entered on the
result page, the hub routing a register here, the website box."""
import io

import pytest
from openpyxl import load_workbook

from agentry.automations.ca import core, depreciation
from agentry.automations.ca.taxdocs import SAMPLES

FAR = (SAMPLES / "fixed_asset_register_sample.csv").read_bytes()


def _run(data: bytes = FAR, **kw) -> dict:
    return depreciation.compute(data, "text/csv", **kw)


def test_sample_register():
    r = _run()
    assert r["year"]["label"] == "FY 2025-26"  # from the title line, not the April 2026 put-to-use date
    a = {x["name"]: x for x in r["assets"]}
    assert a["Factory land, Taloja MIDC"]["block"] is None and a["Factory land, Taloja MIDC"]["book"]["depreciation"] == 0
    inn = a["Toyota Innova MH46 AB 2211"]
    assert inn["book"]["days"] == 263 and inn["book"]["depreciation"] == round(1950000 * 0.95 / 8 * 263 / 365, 2)
    assert inn["book"]["profit_on_sale"] == round(950000 - (1109338 - inn["book"]["depreciation"]), 2) and inn["book"]["closing"] == 0
    assert a["Powder coating line"]["cwip"] and r["summary"]["cwip"] == 1650000  # put to use after the year end
    assert a["Rooftop solar plant 50 kW"]["tax"]["half"] and a["Server rack and NAS"]["tax"]["half"]
    assert not a["Mahindra Bolero pick-up"]["tax"]["half"]  # 193 days
    assert a["Office chairs (8)"]["tax"]["cash_disallowed"] and a["Office chairs (8)"]["tax"]["addition"] == 0
    assert a["Platform weighing scale"]["assumed"]
    assert a["Dell laptops (5)"]["book"]["closing"] == 18750  # stops at the 5% residual value
    b = {x["key"]: x for x in r["blocks"]}
    pm = b["pm"]
    assert (pm["opening"], pm["additions_full"], pm["sales"]) == (2497118, 3775000, 950000)
    assert pm["depreciation"] == round((2497118 + 3775000 - 950000) * 0.15, 2)
    assert b["energy"]["depreciation"] == 2100000 * 0.40 / 2 and b["energy"]["opening_from"] == "new block this year"
    assert b["computer"]["depreciation"] == round(100440 * 0.4 + 420000 * 0.2, 2)
    t = r["book_total"]
    assert round(t["opening"] + t["additions"] - t["depreciation"] - t["disposals"], 2) == t["closing"]
    d = r["deferred_tax"]
    assert d["position"] == "liability" and d["charge"] == round((d["difference_closing"] - d["difference_opening"]) * 0.25168, 2)
    checks = " | ".join(c["what"] for c in r["checks"])
    assert r["checks"][0]["severity"] == "serious" and "section 43(1)" in r["checks"][0]["what"]
    assert "capital work in progress" in checks and "additional depreciation" in checks and "Tally Prime licence" in checks
    wb = load_workbook(io.BytesIO(depreciation.sheet(r)))
    assert wb.sheetnames == ["Books (Schedule II)", "Income-tax blocks", "Asset-wise", "Deferred tax", "Checks"]


def test_block_sold_out_and_firm_rate():
    reg = (b"Asset,Category,Date of Purchase,Cost,Opening WDV,Opening Tax WDV,Sale Date,Sale Value\n"
           b"Old car,Motor car,01/05/2019,800000,300000,200000,10/06/2025,350000\n"
           b"Old PC,Computer,01/05/2021,60000,5000,4000,10/06/2025,1000\n"
           b"New laptop,Computer,01/02/2026,90000,,,,\n")
    r = _run(reg, kind="firm")
    b = {x["key"]: x for x in r["blocks"]}
    assert b["pm"]["stcg"] == 150000 and b["pm"]["depreciation"] == 0  # sale money above the block: section 50 gain
    assert b["computer"]["additions_half"] == 90000 and b["computer"]["stcl"] == 0  # a new asset left in the block: no loss
    assert r["deferred_tax"]["tax_rate"] == 0.312
    with pytest.raises(core.CaError):
        _run(b"Name,City\nA,B\n")


async def test_api_and_tax_opening(client, team_org):
    _oid, h = await team_org(["ca_filing_tracker"])
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Steel Pvt Ltd", "kind": "company"})).json()["id"]
    assert (await client.post(f"/org/ca/clients/{cid}/depreciation/sample", headers=h["viewer"])).status_code == 403
    s = await client.post(f"/org/ca/clients/{cid}/depreciation/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    wid, before = s.json()["id"], s.json()["result"]["summary"]["tax_depreciation"]
    r = await client.post(f"/org/ca/work/{wid}/tax-opening", headers=h["owner"], json={"opening": {"pm": 2600000}})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["tax_depreciation"] == round(before + (2600000 - 2497118) * 0.15, 2)
    w = (await client.get(f"/org/ca/work/{wid}", headers=h["owner"])).json()["result"]
    assert next(b for b in w["blocks"] if b["key"] == "pm")["opening_from"] == "entered"
    assert (await client.post(f"/org/ca/work/{wid}/tax-opening", headers=h["owner"], json={"opening": {"nope": 1}})).status_code == 422
    assert (await client.get(f"/org/ca/work/{wid}/sheet.xlsx", headers=h["owner"])).status_code == 200
    up = await client.post(f"/org/ca/clients/{cid}/hub", headers=h["owner"],
                           files=[("files", ("FAR 25-26.csv", FAR.replace(b"Mehta Steel", b"Mehta Steels"), "text/csv"))])
    assert up.status_code == 201, up.text
    row = up.json()["files"][0]
    assert row["recognised"] == "Fixed asset register" and row["ran"]["agent"] == "ca_depreciation"


async def test_website_box(client):
    s = (await client.get("/public/playground/depreciation/sample")).json()
    r = await client.post("/public/playground/depreciation", headers={"x-forwarded-for": "203.0.113.82"}, json={"input": s})
    assert r.status_code == 200, r.text
    assert r.json()["year"]["label"] == "FY 2025-26" and r.json()["blocks"]
    assert "Schedule II" in (await client.get("/public/sources/ca-depreciation")).json()["basis"]
