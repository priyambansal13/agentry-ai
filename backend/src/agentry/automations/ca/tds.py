"""TDS returns (CA Firm pack): a client's payments register -> checks, interest, and the 24Q / 26Q deductee lines.

    read      Excel / CSV: deductee, PAN, section, payment (or credit) date, amount, TDS deducted, deduction date,
              deposit (challan) date, challan number; an optional nature column for 194I (rent of plant vs building)
    check     PAN format (no valid PAN: 20% under 206AA), the rate for the section (FY 2025-26 rates and thresholds),
              TDS not deducted above the threshold, interest under 201(1A): 1% a month for deducting late and 1.5% a
              month for depositing after the due date (7th of the next month; 30 April for March)
    out       per quarter and section: deductees, amount, TDS; 24Q (salary, 192) and 26Q lines ready for the return
              preparation utility; the interest to pay with the return
Thresholds are per payment where the law says so; yearly aggregates (194C ₹1 lakh) are checked across the file.
"""
import re
from collections import defaultdict
from datetime import date

from pydantic import BaseModel

from agentry import official_rules as rules
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core


def rates() -> dict[str, tuple[float | None, float | None, float, str]]:
    """Section -> (rate for individuals / HUF, rate for others, threshold, label), as in force (official_rules)."""
    return rules.tds_rates()


class TdsConfig(BaseModel):
    pass


register(AutomationTemplate(
    key="ca_tds_returns", name="TDS returns",
    description="24Q/26Q data, PAN checks, late-deduction interest, ready for the return.",
    config_model=TdsConfig, metrics=(),
))


def norm_section(s: str, nature: str = "") -> str:
    s = re.sub(r"\s+", "", str(s or "").upper()).replace("SECTION", "").replace("U/S", "")
    n = (nature or "").lower()
    if s.startswith("194I") and s not in rates():
        return "194I(a)" if re.search(r"plant|machin|equipment|vehicle", n) else "194I(b)"
    if s.startswith("194J") and s not in rates():
        return "194J(a)" if re.search(r"technical|call cent|royalty", n) else "194J(b)"
    if s in ("194IA", "194-IA"):
        return "194-IA"
    return s


def due_date(d: date) -> date:
    return date(d.year, 4, 30) if d.month == 3 else date(d.year + (d.month == 12), d.month % 12 + 1, 7)


def months_part(a: date, b: date) -> int:
    """Months or part of a month from a to b, as 201(1A) counts them (a part month is a full month)."""
    if b <= a:
        return 0
    n = (b.year - a.year) * 12 + b.month - a.month
    return n + 1 if b.day >= a.day else max(n, 1)


def quarter(d: date) -> str:
    fy = d.year if d.month >= 4 else d.year - 1
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[d.month]
    return f"Q{q} FY {fy}-{str(fy + 1)[2:]}"


def parse(rows: list[list[str]]) -> list[dict]:
    h = core.header_row(rows, ("pan", "section|sec", "amount|paid|credit"))
    head, body = rows[h], rows[h + 1:]
    col = {"name": core.find_col(head, "Deductee name", "Name of deductee", "Party name", "Deductee", "Name", "Party"),
           "pan": core.find_col(head, "PAN of deductee", "Deductee PAN", "PAN"),
           "section": core.find_col(head, "Section", "Section code", "TDS section", "Sec"),
           "nature": core.find_col(head, "Nature of payment", "Nature", "Description", "Particulars"),
           "paid_on": core.find_col(head, "Date of payment/credit", "Payment date", "Credit date", "Date of payment", "Invoice date", "Date"),
           "amount": core.find_col(head, "Amount paid/credited", "Amount paid", "Amount credited", "Gross amount", "Amount", avoid=("tds", "tax")),
           "tds": core.find_col(head, "TDS deducted", "Tax deducted", "TDS amount", "TDS"),
           "deducted_on": core.find_col(head, "Date of deduction", "Deduction date", "TDS date"),
           "deposited_on": core.find_col(head, "Date of deposit", "Deposit date", "Challan date", "Date of challan"),
           "challan": core.find_col(head, "Challan no", "Challan serial", "BSR", "CIN")}
    missing = [k for k in ("name", "pan", "section", "amount", "paid_on") if col[k] is None]
    if missing:
        raise core.CaError(f"couldn't find these columns: {', '.join(missing)}")
    out = []
    for n, r in enumerate(body, start=h + 2):
        g = {k: (str(r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        amt, paid = core.money(g["amount"]), core.parse_date(g["paid_on"])
        if not g["name"] or amt is None or not paid:
            continue
        out.append({"row": n, "name": g["name"], "pan": g["pan"].upper(), "section": norm_section(g["section"], g["nature"]), "nature": g["nature"],
                    "amount": amt, "tds": core.money(g["tds"]) or 0.0, "paid_on": paid, "deducted_on": core.parse_date(g["deducted_on"]),
                    "deposited_on": core.parse_date(g["deposited_on"]), "challan": g["challan"]})
    if not out:
        raise core.CaError("no payments found in this file")
    return out


def check(rows: list[dict]) -> dict:
    yearly = defaultdict(float)
    for r in rows:
        yearly[(r["pan"] or r["name"], r["section"])] += r["amount"]
    issues, interest = [], 0.0
    table = rates()
    for r in rows:
        sec = table.get(r["section"])
        problems = []
        pan_valid = core.pan_ok(r["pan"])
        if not pan_valid:
            problems.append(f"no valid PAN: TDS at {rules.num('tds.no_pan_rate') * 100:g}% (206AA)")
        rate = None
        if sec and sec[0] is not None:
            individual = pan_valid and r["pan"][3] in "PH"
            rate = sec[0] if individual else sec[1]
            if not pan_valid:
                rate = max(rate or 0, rules.num("tds.no_pan_rate"))
            over = r["amount"] > sec[2] or (r["section"] == "194C" and yearly[(r["pan"] or r["name"], "194C")] > rules.num("tds.194C.yearly"))
            expected = round(r["amount"] * rate, 0) if over else 0.0
            if over and r["tds"] + 1 < expected:
                problems.append(f"TDS {core.inr(r['tds'])}, should be {core.inr(expected)} ({rate * 100:g}% under {r['section']}); "
                                f"interest at {rules.num('tds.late_deduction') * 100:g}% a month runs from the payment date until the shortfall is deducted")
                r["short"] = round(expected - r["tds"], 2)
        elif not sec:
            problems.append(f"section {r['section'] or '(blank)'} not recognised: check it")
        deducted = r["deducted_on"] or (r["paid_on"] if r["tds"] else None)
        r["interest"] = 0.0
        if r["tds"] and deducted and deducted > r["paid_on"]:
            m = months_part(r["paid_on"], deducted)
            late = rules.num("tds.late_deduction")
            r["interest"] += round(r["tds"] * late * m, 2)
            problems.append(f"deducted {m} month(s) late: interest {core.inr(r['tds'] * late * m)} at {late * 100:g}%")
        if r["tds"] and deducted:
            due = due_date(deducted)
            if not r["deposited_on"]:
                problems.append(f"no deposit date: due by {due:%d %b %Y}")
            elif r["deposited_on"] > due:
                m = months_part(deducted, r["deposited_on"])
                late = rules.num("tds.late_deposit")
                r["interest"] += round(r["tds"] * late * m, 2)
                problems.append(f"deposited after {due:%d %b}: interest {core.inr(r['tds'] * late * m)} at {late * 100:g}% for {m} month(s)")
        interest += r["interest"]
        r["form"] = "24Q" if r["section"] == "192" else "26Q"
        r["quarter"] = quarter(r["paid_on"])
        r["rate"] = rate
        if problems:
            issues.append({"row": r["row"], "name": r["name"], "section": r["section"], "problems": problems})
    summary: dict[tuple, dict] = defaultdict(lambda: {"deductees": set(), "amount": 0.0, "tds": 0.0, "interest": 0.0})
    for r in rows:
        s = summary[(r["form"], r["quarter"], r["section"])]
        s["deductees"].add(r["pan"] or r["name"])
        s["amount"] += r["amount"]
        s["tds"] += r["tds"]
        s["interest"] += r["interest"]
    return {"rows": [{**r, "paid_on": str(r["paid_on"]), "deducted_on": str(r["deducted_on"] or ""), "deposited_on": str(r["deposited_on"] or "")} for r in rows],
            "issues": issues, "interest": round(interest, 2),
            "summary": [{"form": f, "quarter": q, "section": s, "label": table.get(s, (0, 0, 0, s))[3], "deductees": len(v["deductees"]),
                         "amount": round(v["amount"], 2), "tds": round(v["tds"], 2), "interest": round(v["interest"], 2)}
                        for (f, q, s), v in sorted(summary.items())]}


def compute(data: bytes, mime: str) -> dict:
    return check(parse(core.table_rows(data, mime)))


def sheet(result: dict) -> bytes:
    summ = [["Form", "Quarter", "Section", "Nature", "Deductees", "Amount", "TDS", "Interest 201(1A)"]] + \
        [[s["form"], s["quarter"], s["section"], s["label"], s["deductees"], s["amount"], s["tds"], s["interest"]] for s in result["summary"]] + \
        [[], ["Interest to pay with the return", "", "", "", "", "", "", result["interest"]]]
    lines = [["Form", "Quarter", "Section", "Deductee", "PAN", "Date of payment", "Amount", "TDS", "Rate", "Date of deduction", "Date of deposit", "Challan", "Interest"]]
    lines += [[r["form"], r["quarter"], r["section"], r["name"], r["pan"], r["paid_on"], r["amount"], r["tds"], r["rate"], r["deducted_on"], r["deposited_on"],
               r["challan"], r["interest"]] for r in result["rows"]]
    issues = [["Row", "Deductee", "Section", "Check"]] + [[i["row"], i["name"], i["section"], "; ".join(i["problems"])] for i in result["issues"]]
    return core.xlsx_bytes({"Summary": summ, "Deductee lines": lines, "Checks": issues})
