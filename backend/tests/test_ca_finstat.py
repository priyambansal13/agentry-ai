"""Financial statements (docs/PLAN-CA-DESK-2.md #5): the sample two-year trial balance mapped by rules into Schedule III,
both years balancing (last year's closing reserves = this year's opening), stock and tax handled, the checks, ratios and
questions, a correction learned for the next trial balance, the AI only for leftovers, the website box."""
import asyncio
import io

from openpyxl import load_workbook

from agentry.automations.ca import finstat
from agentry.automations.ca.taxdocs import SAMPLES

TB = (SAMPLES / "trial_balance_sample.csv").read_bytes()


def _run(data: bytes = TB, **kw) -> dict:
    return asyncio.run(finstat.prepare(None, None, data, "text/csv", use_model=False, **kw))


def test_sample_trial_balance():
    r = _run()
    assert r["has_py"] and r["columns"]["previous_year"].startswith("Debit FY 2024-25")
    line = {x["name"]: x["line"] for x in r["ledgers"]}
    assert line["Salary Payable"] == "other_cl"  # the Current Liabilities group beats "salary"
    assert line["Provision for Income Tax"] == "st_provisions" and line["Income Tax Expense"] == "tax"
    assert line["Kotak Bank OD A/c 7781"] == "st_borrowings" and line["Input GST Credit"] == "other_ca" and line["GST Payable"] == "other_cl"
    assert line["Interest on OD"] == "finance" and line["Interest Received on FD"] == "other_income" and line["Wages"] == "employee"
    pl = r["profit_and_loss"]
    assert pl["cy"]["change_inventory"] == 1150000 - 1380000 and pl["cy"]["tax"] == 310000
    assert pl["py"]["pat"] == 394200
    res = {y: next(x for s in r["balance_sheet"]["equity_liabilities"] for x in s["lines"] if x["key"] == "reserves")[y] for y in ("cy", "py")}
    assert res["py"] == 982800 and res["cy"] == 982800 + pl["cy"]["pat"]  # opening this year = closing last year
    t = r["balance_sheet"]["totals"]
    assert t["py"]["el"] == t["py"]["a"]  # last year balances
    assert round(t["cy"]["el"] - t["cy"]["a"], 2) == 12500 + 8400  # out by the unplaced ledger and the suspense, and says so
    checks = " | ".join(c["what"] for c in r["checks"])
    assert "suspense balance and the ledgers not placed" in checks and "Misc. Balances W/off" in checks and "Suspense account" in checks
    assert "Patil Fabricators (a debtor) has a credit balance" in checks
    qs = {q["label"]: q["question"] for q in r["review"]}
    assert "while sales moved +16%" in qs["Trade receivables"] and "Factory Rent" in qs
    assert {x["name"] for x in r["ratios"]} >= {"Current ratio", "Debt-equity ratio", "Net profit ratio (%)"}


def test_layout_single_year_and_not_a_tb():
    wb = load_workbook(io.BytesIO(finstat.sheet(_run())))
    assert wb.sheetnames == ["Balance sheet", "Profit and loss", "Ratios", "Questions for client", "Mapping", "Checks"]
    one = b"Ledger,Group,Closing Balance\nCapital,Capital Account,500000 Cr\nCash,Cash-in-Hand,100000 Dr\nFurniture,Fixed Assets,250000 Dr\n" \
          b"Sales,Sales Accounts,900000 Cr\nPurchases,Purchase Accounts,800000 Dr\nRent,Indirect Expenses,250000 Dr\n"
    r = _run(one, kind="firm")
    assert not r["has_py"] and r["balance_sheet"]["balanced"] and r["profit_and_loss"]["cy"]["pat"] == -150000
    assert r["profit_to"].startswith("Share capital")  # a firm's loss goes to capital
    import pytest

    from agentry.automations.ca import core
    with pytest.raises(core.CaError):
        _run(b"Name,City\nA,B\n")


async def test_api_correction_learned(client, team_org):
    _oid, h = await team_org(["ca_filing_tracker"])
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Steel Pvt Ltd", "kind": "company"})).json()["id"]
    assert (await client.post(f"/org/ca/clients/{cid}/financials/sample", headers=h["viewer"])).status_code == 403
    s = await client.post(f"/org/ca/clients/{cid}/financials/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    wid = s.json()["id"]
    assert s.json()["result"]["summary"]["unmapped"] == 1
    r = await client.post(f"/org/ca/work/{wid}/ledger", headers=h["owner"], json={"ledger": "Misc. Balances W/off", "line": "other_expenses", "learn": True})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["unmapped"] == 0
    assert (await client.post(f"/org/ca/work/{wid}/ledger", headers=h["owner"], json={"ledger": "Nope", "line": "other_expenses"})).status_code == 422
    again = (await client.post(f"/org/ca/clients/{cid}/financials/sample", headers=h["owner"])).json()["result"]
    misc = next(x for x in again["ledgers"] if x["name"] == "Misc. Balances W/off")
    assert misc["line"] == "other_expenses" and misc["how"] == "learned"
    x = await client.get(f"/org/ca/work/{wid}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200


async def test_ai_only_for_leftovers(monkeypatch):
    seen = {}

    async def fake(tier, msgs, **kw):
        seen["text"] = msgs[-1]["content"]

        from types import SimpleNamespace
        return SimpleNamespace(data={"ledgers": [{"i": 0, "line": "other_expenses", "why": "a write-off"}, {"i": 1, "line": "made_up"}]})
    monkeypatch.setattr(finstat, "complete", fake)
    ledgers = [{"name": "Misc. Balances W/off", "group": "", "cy": 12500.0, "py": 0.0}, {"name": "Odd thing", "group": "", "cy": 10.0, "py": 0.0},
               {"name": "Salaries", "group": "Indirect Expenses", "cy": 100.0, "py": 0.0}]
    await finstat.map_ledgers("org", ledgers, {})
    assert "Misc. Balances" in seen["text"] and "Salaries" not in seen["text"]  # rules first; only the leftovers go to the model
    assert ledgers[0]["how"] == "ai" and ledgers[1]["line"] is None and ledgers[2]["how"] == "rule"  # an invented key is refused


async def test_website_box(client):
    s = (await client.get("/public/playground/financials/sample")).json()
    r = await client.post("/public/playground/financials", headers={"x-forwarded-for": "203.0.113.81"}, json={"input": s})
    assert r.status_code == 200, r.text
    assert r.json()["profit_and_loss"]["py"]["pat"] == 394200 and r.json()["review"]
    assert "Schedule III" in (await client.get("/public/sources/ca-financial-statements")).json()["basis"]
