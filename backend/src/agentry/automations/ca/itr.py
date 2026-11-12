"""ITR preparation (CA Firm pack): the tax computation for an individual, old regime vs new, for AY 2026-27.

    in        prefilled from the tax documents reader (salary, interest, dividends, TDS, Form 16 deductions) and the
              latest capital gains computation; the CA confirms or changes every figure
    compute   both regimes, income by head, deductions allowed in each, slab tax, special-rate capital gains
              (111A 20%, 112A 12.5% above ₹1.25 lakh), unused basic exemption against them, 87A rebate (new regime: income
              up to ₹12 lakh, with marginal relief; not on special-rate tax), surcharge (capped at 15% on 111A / 112A),
              4% cess, then TDS and taxes paid -> payable or refund
    out       the regime that costs less, which ITR form fits, and an Excel computation for the file
Rules are for FY 2025-26 (AY 2026-27). Marginal relief on surcharge isn't applied (flagged above ₹50 lakh). The CA
files: the department's ITR utility takes these figures; nothing is uploaded from here.
"""
from pydantic import BaseModel, Field

from agentry import official_rules as rules
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core


class ItrConfig(BaseModel):
    assessment_year: str = Field("2026-27", title="Assessment year the rules are for", json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="ca_itr_prep", name="ITR preparation",
    description="Tax computation, old vs new regime, and the figures for the ITR, for the CA to review and file.",
    config_model=ItrConfig, metrics=(),
))

def new_slabs() -> list[tuple[float | None, float]]:
    """The new regime's slabs in force (official_rules: itr.new_slabs)."""
    return [(u, r) for u, r in rules.get("itr.new_slabs")]  # type: ignore[union-attr]


OLD_EXEMPT = {"below60": 250000, "60to80": 300000, "above80": 500000}

FIELDS = {  # key -> label, in the order the form shows them
    "salary_gross": "Gross salary", "exempt_allowances": "Exempt allowances (HRA, LTA…; old regime)", "professional_tax": "Professional tax",
    "employer_nps": "Employer's NPS contribution (80CCD(2))", "self_occupied_interest": "Home loan interest, self-occupied (24(b))",
    "let_out_rent": "Rent received (let-out property)", "let_out_municipal_tax": "Municipal tax paid", "let_out_interest": "Home loan interest, let-out",
    "interest_savings": "Savings bank interest", "interest_deposit": "Deposit and other interest", "dividend": "Dividends",
    "other_income": "Other income", "business_income": "Business / profession income", "stcg_111a": "Short-term gains on listed shares / equity MF (111A)",
    "ltcg_112a": "Long-term gains on listed shares / equity MF (112A)", "stcg_other": "Other short-term gains (at slab rates)",
    "ltcg_other": "Other long-term gains (12.5%)", "d_80c": "80C (PF, PPF, LIC, ELSS, principal…)", "d_80ccd1b": "80CCD(1B) own NPS",
    "d_80d": "80D health insurance", "d_80e": "80E education loan interest", "d_80g": "80G donations (qualifying amount)",
    "tds": "TDS / TCS", "advance_tax": "Advance tax paid", "self_assessment_tax": "Self-assessment tax paid",
}


def _f(p: dict, k: str) -> float:
    return max(0.0, float(core.money(p.get(k)) or 0))


def slab_tax(income: float, slabs: list[tuple[float | None, float]]) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in slabs:
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or income <= upper:
            break
        lower = upper
    return tax


def old_slabs(age: str) -> list[tuple[float | None, float]]:
    ex = OLD_EXEMPT.get(age, 250000)
    return [(ex, 0), *([(500000, 0.05)] if ex < 500000 else []), (1000000, 0.20), (None, 0.30)]


def compute(p: dict, regime: str) -> dict:
    age = p.get("age", "below60")
    new = regime == "new"
    lines: list[tuple[str, float]] = []
    std = rules.num("itr.std_new") if new else rules.num("itr.std_old")
    gross = _f(p, "salary_gross")
    salary = max(0.0, gross - (0 if new else _f(p, "exempt_allowances")) - (min(std, gross)) - (0 if new else _f(p, "professional_tax")))
    lines += [("Income from salary", salary)]
    let_out = max(0.0, _f(p, "let_out_rent") - _f(p, "let_out_municipal_tax"))
    hp = let_out * 0.7 - _f(p, "let_out_interest") - (0 if new else min(rules.num("itr.home_loan"), _f(p, "self_occupied_interest")))
    hp = max(hp, 0.0) if new else max(hp, -rules.num("itr.home_loan"))  # new regime: a house property loss can't reduce other income
    lines += [("Income from house property", hp)]
    other = _f(p, "interest_savings") + _f(p, "interest_deposit") + _f(p, "dividend") + _f(p, "other_income")
    lines += [("Income from other sources", other), ("Business / profession", _f(p, "business_income"))]
    normal_gti = max(0.0, salary + hp + other + _f(p, "business_income") + _f(p, "stcg_other"))
    special = {"111A": _f(p, "stcg_111a"), "112A": _f(p, "ltcg_112a"), "112": _f(p, "ltcg_other")}
    lines += [("Short-term gains (111A)", special["111A"]), ("Long-term gains (112A)", special["112A"]), ("Other long-term gains", special["112"]),
              ("Other short-term gains", _f(p, "stcg_other"))]
    if new:
        ded = {"80CCD(2)": _f(p, "employer_nps")}
    else:
        senior = age != "below60"
        interest_ded = min(50000, _f(p, "interest_savings") + _f(p, "interest_deposit")) if senior else min(10000, _f(p, "interest_savings"))
        ded = {"80C": min(rules.num("itr.ded_80c"), _f(p, "d_80c")), "80CCD(1B)": min(rules.num("itr.ded_80ccd1b"), _f(p, "d_80ccd1b")), "80CCD(2)": _f(p, "employer_nps"),
               "80D": min(100000, _f(p, "d_80d")), "80E": _f(p, "d_80e"), "80G": _f(p, "d_80g"), "80TTB" if senior else "80TTA": interest_ded}
    total_ded = min(sum(ded.values()), normal_gti)  # Chapter VI-A deductions don't reduce special-rate gains
    normal = max(0.0, normal_gti - total_ded)
    slabs = new_slabs() if new else old_slabs(age)
    exemption = slabs[0][0] or 0
    # a resident's unused basic exemption is set against special-rate gains (111A first, then 112A, then 112)
    room = max(0.0, exemption - normal)
    taxed_special = dict(special)
    for k in ("111A", "112A", "112"):
        use = min(room, taxed_special[k])
        taxed_special[k] -= use
        room -= use
    ltcg_exempt = min(rules.num("itr.ltcg_exempt"), taxed_special["112A"])
    r111a, r112a = rules.num("itr.rate_111a"), rules.num("itr.rate_112a")
    special_tax = taxed_special["111A"] * r111a + (taxed_special["112A"] - ltcg_exempt) * r112a + taxed_special["112"] * r112a
    normal_tax = slab_tax(normal, slabs)
    total_income = normal + sum(special.values())
    rebate = 0.0
    lim_new, lim_old = rules.num("itr.rebate_limit_new"), rules.num("itr.rebate_limit_old")
    if new and total_income <= lim_new:
        rebate = min(rules.num("itr.rebate_max_new"), normal_tax)
    elif new and normal_tax > 0 and total_income - lim_new < normal_tax and sum(special.values()) == 0:
        rebate = normal_tax - (total_income - lim_new)  # marginal relief just above the limit
    elif not new and total_income <= lim_old:
        rebate = min(rules.num("itr.rebate_max_old"), normal_tax + taxed_special["111A"] * r111a)
    tax = max(0.0, normal_tax + special_tax - rebate)
    rate = 0.0
    for limit, r in ((50000000, 0.37 if not new else 0.25), (20000000, 0.25), (10000000, 0.15), (5000000, 0.10)):
        if total_income > limit:
            rate = r
            break
    special_share = special_tax / (normal_tax + special_tax) if normal_tax + special_tax else 0
    surcharge = max(0.0, tax * (1 - special_share) * rate + tax * special_share * min(rate, 0.15))
    cess = (tax + surcharge) * rules.num("itr.cess")
    liability = round(tax + surcharge + cess)
    paid = _f(p, "tds") + _f(p, "advance_tax") + _f(p, "self_assessment_tax")
    return {"regime": regime, "heads": [{"label": k, "amount": round(v)} for k, v in lines if v],
            "gross_total_income": round(normal_gti + sum(special.values())), "deductions": {k: round(v) for k, v in ded.items() if v},
            "total_deductions": round(total_ded), "total_income": round(total_income), "normal_income": round(normal),
            "slab_tax": round(normal_tax), "special_rate_tax": round(special_tax), "ltcg_exempt": round(ltcg_exempt), "rebate_87a": round(rebate),
            "surcharge": round(surcharge), "cess": round(cess), "tax_liability": liability, "taxes_paid": round(paid),
            "payable": max(0, liability - round(paid)), "refund": max(0, round(paid) - liability),
            "notes": ["Surcharge shown without marginal relief: check it by hand."] if total_income > 5000000 else []}


def itr_form(p: dict) -> str:
    if _f(p, "business_income"):
        return "ITR-3 (ITR-4 if the business income is presumptive under 44AD / 44ADA / 44AE)"
    if any(_f(p, k) for k in ("stcg_111a", "stcg_other", "ltcg_other")) or _f(p, "ltcg_112a") > rules.num("itr.ltcg_exempt") or p.get("foreign"):
        return "ITR-2"
    total = _f(p, "salary_gross") + _f(p, "interest_savings") + _f(p, "interest_deposit") + _f(p, "dividend") + _f(p, "other_income")
    return "ITR-1 (Sahaj)" if total <= 5000000 else "ITR-2"


def prepare(p: dict) -> dict:
    old, new = compute(p, "old"), compute(p, "new")
    better = "new" if new["tax_liability"] <= old["tax_liability"] else "old"
    return {"inputs": {k: p.get(k) for k in [*FIELDS, "age"]}, "old": old, "new": new, "better": better,
            "saving": abs(old["tax_liability"] - new["tax_liability"]), "itr_form": itr_form(p)}


def prefill(docs: list[dict], capital_gains: dict | None) -> dict:
    """From the tax documents reader's lines (Form 16 first for salary and deductions; AIS / 26AS for other income and
    TDS) and the latest capital gains computation."""
    p: dict[str, float] = {}
    f16 = [i for d in docs if d["extracted"]["doc_type"] in ("form16", "form16a") for i in d["extracted"]["items"] if i["traced"]]
    dept = [i for d in docs if d["extracted"]["doc_type"] in ("ais", "26as", "tis") for i in d["extracted"]["items"] if i["traced"]]
    for i in f16:
        sec = (i.get("section") or "").upper().replace(" ", "")
        if i["category"] == "salary":
            p["salary_gross"] = p.get("salary_gross", 0) + i["amount"]
        elif i["category"] == "deduction" and sec.startswith("10"):
            p["exempt_allowances"] = p.get("exempt_allowances", 0) + i["amount"]
        elif i["category"] == "deduction" and "16(III)" in sec:
            p["professional_tax"] = i["amount"]
        elif i["category"] == "deduction" and sec.startswith("80C") and "CCD" not in sec:
            p["d_80c"] = i["amount"]
        elif i["category"] == "deduction" and sec.startswith("80D"):
            p["d_80d"] = i["amount"]
        elif i["category"] == "deduction" and "80CCD(1B)" in sec:
            p["d_80ccd1b"] = i["amount"]
    src = dept or f16
    salary_from_f16 = "salary_gross" in p
    for i in src:
        if i["category"] == "salary" and not salary_from_f16:
            p["salary_gross"] = p.get("salary_gross", 0) + i["amount"]
        for cat, key in (("interest_savings", "interest_savings"), ("interest_deposit", "interest_deposit"), ("interest_other", "interest_deposit"),
                         ("dividend", "dividend"), ("rent", "let_out_rent"), ("other_income", "other_income")):
            if i["category"] == cat:
                p[key] = p.get(key, 0) + i["amount"]
    p["tds"] = sum(i["tds"] for i in src if i["tds"]) or sum(i["tds"] for i in f16 if i["tds"])
    p.update({k: v for k, v in (capital_gains or {}).items() if k in ("stcg_111a", "ltcg_112a", "stcg_other", "ltcg_other") and v})
    return {k: round(v) for k, v in p.items()}


def sheet(client: str, r: dict) -> bytes:
    rows = [["", "Old regime", "New regime"]]
    o, n = r["old"], r["new"]
    heads = {h["label"] for h in o["heads"]} | {h["label"] for h in n["heads"]}
    for h in heads:
        rows.append([h, next((x["amount"] for x in o["heads"] if x["label"] == h), 0), next((x["amount"] for x in n["heads"] if x["label"] == h), 0)])
    for k, label in (("gross_total_income", "Gross total income"), ("total_deductions", "Deductions (Chapter VI-A)"), ("total_income", "Total income"),
                     ("slab_tax", "Tax at slab rates"), ("special_rate_tax", "Tax on special-rate gains"), ("rebate_87a", "Rebate u/s 87A"),
                     ("surcharge", "Surcharge"), ("cess", "Health & education cess (4%)"), ("tax_liability", "Tax liability"),
                     ("taxes_paid", "TDS and taxes paid"), ("payable", "Payable"), ("refund", "Refund")):
        rows.append([label, o[k], n[k]])
    rows += [[], ["Better regime", r["better"], f"saves ₹{r['saving']:,}"], ["ITR form", r["itr_form"]]]
    ded = [["Deduction", "Old regime", "New regime"]] + [[k, o["deductions"].get(k, 0), n["deductions"].get(k, 0)]
                                                         for k in sorted(set(o["deductions"]) | set(n["deductions"]))]
    inputs = [["Figure", "Amount"]] + [[FIELDS.get(k, k), v] for k, v in r["inputs"].items() if v]
    return core.xlsx_bytes({"Computation": [[client], [], *rows], "Deductions": ded, "Inputs": inputs})
