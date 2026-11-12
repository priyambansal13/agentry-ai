"""Bank statement classifier (CA Firm pack): a client's statement -> every line tagged, totals, presumptive income.

    read      Excel / CSV from net banking (HDFC, ICICI, SBI, Axis, Kotak layouts and similar): date, narration,
              withdrawal, deposit, balance; the account details above the table are skipped
    tag       the firm's own rules first (learned from every correction: "a line with SWIGGY is Meals"), then built-in
              patterns (salary, GST / income-tax payments, EMIs, interest, ATM cash, transfers between own accounts…),
              then the model for what's left, in batches; a model's tag is marked so the CA knows to glance at it
    totals    by category; business receipts (deposits that aren't transfers, loans, refunds or interest); cash
              deposits and withdrawals (SFT / 269ST attention); 44AD at 6% of digital + 8% of cash receipts and 44ADA
              at 50%, as a floor to compare with the books
    correct   changing a line's category can teach a rule for the next statements
"""
import json
import re
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import official_rules as rules
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

CATEGORIES = ["Sales / receipts", "Professional fees received", "Salary received", "Interest received", "Dividend", "Refund", "Loan received",
              "Transfer (own accounts)", "Cash deposit", "Cash withdrawal", "Purchases / suppliers", "Salaries paid", "Rent", "Utilities & phone",
              "Travel & fuel", "Meals & entertainment", "Software & subscriptions", "Professional fees paid", "Bank charges",
              "Loan EMI", "GST paid", "Income tax / TDS paid", "Insurance", "Investments", "Drawings / personal", "Other"]
NOT_TURNOVER = {"Transfer (own accounts)", "Loan received", "Refund", "Interest received", "Dividend", "Salary received"}
RULES = [  # (regex on the narration, category, applies to "in" / "out" / None for both)
    (r"\bsal(ary)?\b|payroll", "Salary received", "in"), (r"\bsal(ary)?\b|payroll", "Salaries paid", "out"),
    (r"int\.?\s*pd|interest|int\.? cr|\bint\b.*\bcredit", "Interest received", "in"), (r"\bdiv(idend)?\b", "Dividend", "in"),
    (r"refund|reversal|cashback", "Refund", "in"), (r"\bgst\b|gstn|cbic|cpin", "GST paid", "out"),
    (r"cbdt|itns|income ?tax|\btds\b|advance tax|oltas|e-?pay tax", "Income tax / TDS paid", "out"),
    (r"\bemi\b|loan|nach.*(finance|bajaj|hdfc ltd|capital)", "Loan EMI", "out"), (r"\batm\b|cash wdl|cash withdrawal|\bcwdr\b|\bnwd\b", "Cash withdrawal", "out"),
    (r"cash dep|by cash|cash deposit|\bcdm\b", "Cash deposit", "in"), (r"self|own a/?c|sweep|\bto fd\b|fd booked|fd closure", "Transfer (own accounts)", None),
    (r"charges|chrgs|\bfee\b.*bank|sms alert|annual fee|gst on charges", "Bank charges", "out"),
    (r"rent\b", "Rent", "out"), (r"electricity|bescom|msedcl|tata power|airtel|jio|vodafone|\bvi\b|bsnl|broadband", "Utilities & phone", "out"),
    (r"uber|ola|irctc|indigo|air india|vistara|makemytrip|petrol|fuel|hpcl|bpcl|iocl|fastag", "Travel & fuel", "out"),
    (r"swiggy|zomato|restaurant|cafe|starbucks|dominos", "Meals & entertainment", "out"),
    (r"google|microsoft|aws|amazon web|zoho|adobe|github|notion|slack|openai", "Software & subscriptions", "out"),
    (r"lic\b|insurance|policy|premium|mediclaim", "Insurance", "out"), (r"zerodha|groww|upstox|mutual fund|\bmf\b|sip|ppf|nps", "Investments", "out"),
]


class BankConfig(BaseModel):
    use_model: bool = Field(True, title="Ask the AI for lines no rule covers", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_bank_classifier", name="Bank statement classifier",
    description="Statement lines tagged and summed into a trial balance or 44AD/44ADA working.",
    config_model=BankConfig, metrics=(),
))


def parse(rows: list[list[str]]) -> list[dict]:
    h = core.header_row(rows, ("date", "narration|description|particulars|remarks|details", "withdrawal|debit|dr"), within=30)
    head, body = rows[h], rows[h + 1:]
    col = {"date": core.find_col(head, "Txn Date", "Transaction Date", "Date", "Value Date"),
           "narration": core.find_col(head, "Narration", "Description", "Particulars", "Transaction Remarks", "Remarks", "Details"),
           "ref": core.find_col(head, "Chq./Ref.No.", "Ref No", "Cheque No", "Reference", "Chq No"),
           "out": core.find_col(head, "Withdrawal Amt.", "Withdrawal Amount", "Withdrawal", "Debit Amount", "Debit", "Dr"),
           "in": core.find_col(head, "Deposit Amt.", "Deposit Amount", "Deposit", "Credit Amount", "Credit", "Cr"),
           "balance": core.find_col(head, "Closing Balance", "Balance")}
    if col["date"] is None or col["narration"] is None or (col["out"] is None and col["in"] is None):
        raise core.CaError("couldn't find the date, narration and withdrawal / deposit columns")
    out = []
    for n, r in enumerate(body, start=h + 2):
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        d = core.parse_date(g["date"])
        if not d:
            continue
        wd, dep = core.money(g["out"]) or 0.0, core.money(g["in"]) or 0.0
        if not wd and not dep:
            continue
        out.append({"row": n, "date": str(d), "narration": g["narration"], "ref": g["ref"], "out": abs(wd), "in": abs(dep),
                    "balance": core.money(g["balance"])})
    if not out:
        raise core.CaError("no transactions found in this statement")
    return out


def counterparty(narration: str) -> str:
    """The distinctive part of a narration to learn a rule from: UPI/NEFT payee names, else the first words."""
    s = narration.upper()
    m = re.search(r"UPI[/-](?:[A-Z]+[/-])?\d*[/-]?([A-Z][A-Z .&]{2,40}?)[/-]", s) or re.search(r"(?:NEFT|IMPS|RTGS)[/-][A-Z0-9]+[/-]([A-Z][A-Z .&]{2,40}?)[/-]", s)
    if m:
        return m.group(1).strip()
    words = [w for w in re.split(r"[^A-Z]+", s) if len(w) > 2 and w not in ("UPI", "NEFT", "IMPS", "RTGS", "ACH", "NACH", "POS", "TO", "BY", "FROM", "TRANSFER")]
    return " ".join(words[:2])


def by_rules(line: dict, learned: list[tuple[str, str]]) -> tuple[str, str] | None:
    s = line["narration"].lower()
    for pattern, cat in learned:
        if pattern.lower() in s:
            return cat, "rule"
    side = "in" if line["in"] else "out"
    for rx, cat, only in RULES:
        if (only is None or only == side) and re.search(rx, s):
            return cat, "pattern"
    return None


async def classify(org_id: str, lines: list[dict], learned: list[tuple[str, str]], use_model: bool) -> list[dict]:
    todo = []
    for ln in lines:
        hit = by_rules(ln, learned)
        if hit:
            ln["category"], ln["by"] = hit
        else:
            ln["category"], ln["by"] = ("Sales / receipts" if ln["in"] else "Other"), "default"
            todo.append(ln)
    if use_model and todo:
        prompt = load("ca_bank_classify")
        for start in range(0, len(todo), 60):
            batch = todo[start:start + 60]
            listing = "\n".join(f"{i}|{'IN' if ln['in'] else 'OUT'}|{ln['in'] or ln['out']:.2f}|{ln['narration'][:120]}" for i, ln in enumerate(batch))
            mock = {"lines": [{"i": i, "category": ln["category"]} for i, ln in enumerate(batch)]}
            try:
                res = await complete(prompt.tier, prompt.render(categories="\n".join(CATEGORIES), lines=listing), org_id=org_id, prompt_key=prompt.key,
                                     prompt_version=prompt.version, json_output=True, mock_response=json.dumps(mock), temperature=0)
            except AllModelsFailed:
                break
            for x in (res.data or {}).get("lines", []) if isinstance(res.data, dict) else []:
                i = x.get("i")
                if isinstance(i, int) and 0 <= i < len(batch) and x.get("category") in CATEGORIES:
                    batch[i]["category"], batch[i]["by"] = x["category"], "ai"
    return lines


def totals(lines: list[dict]) -> dict:
    by: dict[str, dict] = defaultdict(lambda: {"in": 0.0, "out": 0.0, "count": 0})
    for ln in lines:
        b = by[ln["category"]]
        b["in"] += ln["in"]
        b["out"] += ln["out"]
        b["count"] += 1
    receipts = [ln for ln in lines if ln["in"] and ln["category"] not in NOT_TURNOVER]
    cash_in = sum(ln["in"] for ln in receipts if ln["category"] == "Cash deposit")
    digital_in = sum(ln["in"] for ln in receipts) - cash_in
    cash_out = sum(ln["out"] for ln in lines if ln["category"] == "Cash withdrawal")
    flags = []
    sft = rules.num("bank.sft_cash")
    if cash_in > sft:
        flags.append(f"Cash deposits of {core.inr(cash_in)}: over {core.inr(sft)} in a year is reported to the department (SFT).")
    big_cash = [ln for ln in lines if ln["category"] == "Cash deposit" and ln["in"] >= rules.num("audit.cash_receipt")]
    if big_cash:
        flags.append(f"{len(big_cash)} cash deposit(s) of ₹2 lakh or more: check 269ST (cash receipts from one person).")
    unsure = sum(1 for ln in lines if ln["by"] in ("ai", "default"))
    return {"by_category": {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in sorted(by.items())},
            "receipts": round(digital_in + cash_in, 2), "digital_receipts": round(digital_in, 2), "cash_receipts": round(cash_in, 2),
            "cash_withdrawn": round(cash_out, 2), "total_in": round(sum(ln["in"] for ln in lines), 2), "total_out": round(sum(ln["out"] for ln in lines), 2),
            "presumptive_44ad": round(digital_in * rules.num("bank.44ad_digital") + cash_in * rules.num("bank.44ad_cash"), 2),
            "presumptive_44ada": round((digital_in + cash_in) * rules.num("bank.44ada"), 2),
            "lines": len(lines), "to_glance": unsure, "flags": flags,
            "period": [min(ln["date"] for ln in lines), max(ln["date"] for ln in lines)]}


async def learned_rules(conn: AsyncConnection) -> list[tuple[str, str]]:
    return [(r.pattern, r.category) for r in (await conn.execute(text("select pattern, category from app.ca_bank_rules order by length(pattern) desc"))).all()]


async def run(org_id: str, conn: AsyncConnection, data: bytes, mime: str, use_model: bool) -> dict:
    lines = parse(core.table_rows(data, mime))
    lines = await classify(org_id, lines, await learned_rules(conn), use_model)
    return {"lines": lines, "totals": totals(lines)}


async def correct(conn: AsyncConnection, org_id: str, result: dict, row: int, category: str, learn: bool, user_id: str | None) -> dict:
    if category not in CATEGORIES:
        raise core.CaError("unknown category")
    line = next((ln for ln in result["lines"] if ln["row"] == row), None)
    if not line:
        raise core.CaError("line not found")
    pattern = counterparty(line["narration"])
    for ln in result["lines"]:  # the same counterparty elsewhere in this statement too
        if ln is line or (learn and pattern and pattern.lower() in ln["narration"].lower()):
            ln["category"], ln["by"] = category, "you"
    if learn and len(pattern) >= 3:
        await conn.execute(text("""insert into app.ca_bank_rules (org_id, pattern, category, created_by) values (:o, :p, :c, :u)
            on conflict (org_id, pattern) do update set category = excluded.category"""), {"o": org_id, "p": pattern, "c": category, "u": user_id})
    result["totals"] = totals(result["lines"])
    return {"pattern": pattern if learn else None, **result}


def sheet(result: dict) -> bytes:
    t = result["totals"]
    summary = [["Category", "Deposits", "Withdrawals", "Lines"]] + [[k, v["in"], v["out"], v["count"]] for k, v in t["by_category"].items()] + \
        [[], ["Business receipts", t["receipts"]], ["of which digital", t["digital_receipts"]], ["of which cash", t["cash_receipts"]],
         ["44AD presumptive income (6% digital + 8% cash)", t["presumptive_44ad"]], ["44ADA presumptive income (50%)", t["presumptive_44ada"]],
         *[[f] for f in t["flags"]]]
    rows = [["Date", "Narration", "Ref", "Withdrawal", "Deposit", "Balance", "Category", "Tagged by"]] + \
        [[ln["date"], ln["narration"], ln["ref"], ln["out"] or None, ln["in"] or None, ln["balance"], ln["category"], ln["by"]] for ln in result["lines"]]
    return core.xlsx_bytes({"Summary": summary, "Transactions": rows})
