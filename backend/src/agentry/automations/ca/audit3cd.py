"""Tax audit, Form 3CD (CA Firm pack): the clauses that can be tested from the ledger, with every exception listed.

    read      a ledger / day book export (Excel / CSV): date, party, amount, mode (cash, bank, UPI…), type (expense,
              purchase, receipt, loan taken, loan repaid, statutory due, employee contribution), and where known: MSME,
              invoice date, payment date, due date, transporter, TDS section and TDS deducted
    clauses   21(d)  40A(3): cash payments to a party over ₹10,000 in a day (₹35,000 to transporters) are disallowed
              26     43B: statutory dues (GST, employer PF / ESI, bonus, leave encashment) not paid by the return due date
              20(b)  36(1)(va): employees' PF / ESI contribution paid after the due date under the PF / ESI law (15th)
              22     43B(h): MSME suppliers not paid within 45 days (15 without a written agreement) and still unpaid on 31
                     March (or paid after it, late)
              31     269SS / 269T: loans taken or repaid in cash of ₹20,000 or more; 269ST: cash receipts of ₹2 lakh or more
              21(b)  40(a)(ia): 30% of payments where TDS was due but not deducted
The auditor decides; this lists what the books show for each clause.
"""
import re
from collections import defaultdict
from datetime import date, timedelta

from pydantic import BaseModel, Field

from agentry import official_rules as rules
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core


class AuditConfig(BaseModel):
    msme_default_days: int = Field(15, ge=15, le=45, title="MSME payment limit when there's no written agreement (days)",
                                   json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_tax_audit", name="Tax audit (3CD)",
    description="3CD clauses tested from the ledger, exceptions flagged for the auditor.",
    config_model=AuditConfig, metrics=(),
))

CASH = re.compile(r"\bcash\b", re.IGNORECASE)
CLAUSES = {"40A(3)": "21(d) · 40A(3) cash payments", "43B": "26 · 43B statutory dues", "36(1)(va)": "20(b) · 36(1)(va) employees' PF / ESI",
           "43B(h)": "22 · 43B(h) MSME payments", "269SS/269T": "31(a)/(b) · 269SS / 269T cash loans", "269ST": "31(ba) · 269ST cash receipts",
           "40(a)(ia)": "21(b) · 40(a)(ia) TDS not deducted"}


def _type(t: str, head: str) -> str:
    s = f"{t} {head}".lower()
    if re.search(r"loan.*(repaid|repay)|repayment", s):
        return "loan_repaid"
    if re.search(r"loan|deposit taken|unsecured", s):
        return "loan_taken"
    if re.search(r"employee.*(pf|esi|contribution)|(pf|esi).*employee", s):
        return "employee_contribution"
    if re.search(r"\bgst\b|employer.*(pf|esi)|\bpf\b|\besi\b|bonus|leave encash|statutory|professional tax", s):
        return "statutory"
    if re.search(r"receipt|sales|income|received", s):
        return "receipt"
    return "expense"


def parse(rows: list[list[str]]) -> list[dict]:
    h = core.header_row(rows, ("date", "amount|debit|credit", "party|ledger|particulars|name"))
    head, body = rows[h], rows[h + 1:]
    col = {"date": core.find_col(head, "Date", "Voucher date", "Txn date", avoid=("invoice", "due", "paid", "payment")),
           "party": core.find_col(head, "Party", "Party name", "Ledger", "Particulars", "Name", "Vendor"),
           "amount": core.find_col(head, "Amount", "Debit", "Value", avoid=("tds",)),
           "mode": core.find_col(head, "Mode", "Payment mode", "Paid via", "Cash/Bank"), "type": core.find_col(head, "Type", "Voucher type", "Nature"),
           "head": core.find_col(head, "Head", "Expense head", "Group", "Account"), "msme": core.find_col(head, "MSME", "MSME registered", "Udyam"),
           "invoice_date": core.find_col(head, "Invoice date", "Bill date", "Acceptance date"), "paid_on": core.find_col(head, "Paid on", "Payment date", "Date paid"),
           "due_on": core.find_col(head, "Due date", "Due on"), "agreement_days": core.find_col(head, "Agreed credit days", "Agreement days", "Credit days"),
           "transporter": core.find_col(head, "Transporter", "Goods carriage"), "tds_section": core.find_col(head, "TDS section"),
           "tds": core.find_col(head, "TDS deducted", "TDS amount", "TDS")}
    if col["date"] is None or col["amount"] is None or col["party"] is None:
        raise core.CaError("couldn't find the date, party and amount columns")
    out = []
    for n, r in enumerate(body, start=h + 2):
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        d, amt = core.parse_date(g["date"]), core.money(g["amount"])
        if not d or not amt:
            continue
        out.append({"row": n, "date": d, "party": g["party"], "amount": abs(amt), "cash": bool(CASH.search(g["mode"])), "mode": g["mode"],
                    "type": _type(g["type"], g["head"]), "head": g["head"] or g["type"], "msme": g["msme"].lower() in ("y", "yes", "true", "1", "msme"),
                    "invoice_date": core.parse_date(g["invoice_date"]) or d, "paid_on": core.parse_date(g["paid_on"]), "due_on": core.parse_date(g["due_on"]),
                    "agreement_days": int(core.money(g["agreement_days"]) or 0) or None, "transporter": g["transporter"].lower() in ("y", "yes", "true", "1"),
                    "tds_section": g["tds_section"], "tds": core.money(g["tds"]) if g["tds"] else None})
    if not out:
        raise core.CaError("no entries found in this ledger")
    return out


def test(entries: list[dict], fy_start: int, msme_default_days: int = 15) -> dict:
    fy_end, return_due = date(fy_start + 1, 3, 31), date(fy_start + 1, 10, 31)
    found: dict[str, list[dict]] = defaultdict(list)
    day_cash: dict[tuple, list[dict]] = defaultdict(list)
    for e in entries:
        if e["cash"] and e["type"] == "expense":
            day_cash[(e["party"].lower(), e["date"])].append(e)
    for (_party, d), es in day_cash.items():
        total, limit = sum(x["amount"] for x in es), rules.num("audit.cash_limit_transport") if any(x["transporter"] for x in es) else rules.num("audit.cash_limit")
        if total > limit:
            found["40A(3)"].append({"party": es[0]["party"], "date": str(d), "amount": total, "disallow": total,
                                    "why": f"cash payments of {core.inr(total)} in a day (limit {core.inr(limit)})", "rows": [x["row"] for x in es]})
    for e in entries:
        paid = e["paid_on"]
        if e["type"] == "statutory" and (not paid or paid > return_due):
            found["43B"].append({"party": e["party"], "date": str(e["date"]), "amount": e["amount"], "disallow": e["amount"],
                                 "why": f"{e['head'] or 'statutory due'} {'unpaid' if not paid else f'paid {paid:%d %b %Y}'}, after the return due date {return_due:%d %b %Y}",
                                 "rows": [e["row"]]})
        if e["type"] == "employee_contribution":
            due = e["due_on"] or date(e["date"].year + (e["date"].month == 12), e["date"].month % 12 + 1, 15)
            if not paid or paid > due:
                found["36(1)(va)"].append({"party": e["party"], "date": str(e["date"]), "amount": e["amount"], "disallow": e["amount"],
                                           "why": f"employees' contribution due {due:%d %b %Y}, {'unpaid' if not paid else f'paid {paid:%d %b %Y}'}", "rows": [e["row"]]})
        if e["msme"] and e["type"] == "expense" and e["invoice_date"] <= fy_end:
            days = min(int(rules.num("audit.msme_days")), e["agreement_days"] or msme_default_days)
            limit = e["invoice_date"] + timedelta(days=days)
            if (not paid or paid > fy_end) and (not paid or paid > limit):
                found["43B(h)"].append({"party": e["party"], "date": str(e["invoice_date"]), "amount": e["amount"], "disallow": e["amount"],
                                        "why": f"MSME supplier: due within {days} days ({limit:%d %b %Y}), {'unpaid' if not paid else f'paid {paid:%d %b %Y}'} "
                                               "and outstanding on 31 March", "rows": [e["row"]]})
        if e["cash"] and e["type"] in ("loan_taken", "loan_repaid") and e["amount"] >= rules.num("audit.loan_cash"):
            found["269SS/269T"].append({"party": e["party"], "date": str(e["date"]), "amount": e["amount"], "disallow": 0,
                                        "why": f"loan {'taken' if e['type'] == 'loan_taken' else 'repaid'} in cash ({'269SS' if e['type'] == 'loan_taken' else '269T'}); "
                                               "penalty equal to the amount", "rows": [e["row"]]})
        if e["tds_section"] and e["tds"] is not None and e["tds"] == 0 and e["type"] == "expense":
            found["40(a)(ia)"].append({"party": e["party"], "date": str(e["date"]), "amount": e["amount"], "disallow": round(e["amount"] * rules.num("audit.tds_disallow"), 2),
                                       "why": f"TDS under {e['tds_section']} not deducted: {rules.num('audit.tds_disallow') * 100:g}% disallowed", "rows": [e["row"]]})
    day_receipts: dict[tuple, list[dict]] = defaultdict(list)
    for e in entries:
        if e["cash"] and e["type"] == "receipt":
            day_receipts[(e["party"].lower(), e["date"])].append(e)
    for (_p, d), es in day_receipts.items():
        total = sum(x["amount"] for x in es)
        if total >= rules.num("audit.cash_receipt"):
            found["269ST"].append({"party": es[0]["party"], "date": str(d), "amount": total, "disallow": 0,
                                   "why": f"cash received {core.inr(total)} from one person in a day; penalty equal to the amount", "rows": [x["row"] for x in es]})
    clauses = [{"clause": k, "label": CLAUSES[k], "items": v, "amount": round(sum(i["amount"] for i in v), 2),
                "disallow": round(sum(i["disallow"] for i in v), 2)} for k, v in found.items()]
    order = list(CLAUSES)
    clauses.sort(key=lambda c: order.index(c["clause"]))
    return {"fy": f"{fy_start}-{str(fy_start + 1)[2:]}", "clauses": clauses, "entries": len(entries),
            "disallowance": round(sum(c["disallow"] for c in clauses), 2)}


def compute(data: bytes, mime: str, fy_start: int, msme_default_days: int = 15) -> dict:
    return test(parse(core.table_rows(data, mime)), fy_start, msme_default_days)


def sheet(result: dict) -> bytes:
    summary = [["Clause", "Exceptions", "Amount", "Disallowance"]] + [[c["label"], len(c["items"]), c["amount"], c["disallow"]] for c in result["clauses"]] + \
        [[], ["Total disallowance", "", "", result["disallowance"]], ["Entries tested", result["entries"]], ["Financial year", result["fy"]]]
    items = [["Clause", "Party", "Date", "Amount", "Disallowance", "Why", "Ledger rows"]]
    items += [[c["label"], i["party"], i["date"], i["amount"], i["disallow"], i["why"], ", ".join(map(str, i["rows"]))] for c in result["clauses"] for i in c["items"]]
    return core.xlsx_bytes({"3CD summary": summary, "Exceptions": items})
