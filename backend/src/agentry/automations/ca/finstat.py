"""Financial statements (CA desk part 2, docs/PLAN-CA-DESK-2.md #5): a trial balance (this year, and last year when the
sheet has it) -> the Schedule III balance sheet and statement of profit and loss, the ratios Schedule III asks for, and the
year-on-year review with a question for the client wherever a figure moved a lot.

    read       the trial balance through the Excel cleaner; columns found by name: ledger, group, Debit / Credit (or one
               closing balance with Dr / Cr), and the same for the previous year (a "previous / PY / last year" heading, or
               the earlier year in the heading)
    map        each ledger to a Schedule III line, in order: the firm's learned corrections (app.ca_ledger_map) -> rules
               on the ledger name (salary, interest, depreciation, GST, opening / closing stock…) -> rules on the Tally
               group (Sundry Debtors, Duties & Taxes, Indirect Expenses…) -> the AI for what's left, marked "AI: check".
               A ledger nothing places is listed as unmapped and kept out of the totals until placed.
    sense      a bank account with a credit balance is shown as a short-term borrowing (overdraft); GST / TDS ledgers go to
               other current liabilities or other current assets by their balance
    stock      "Opening stock" is part of the change in inventories; closing stock is the inventories line and is
               credited to the change in inventories (Tally leaves it out of the trial balance totals, so it's kept out of
               the balancing check)
    profit     the year's profit after tax is added to reserves & surplus (a company) or to capital (a firm,
               proprietor, LLP), so the balance sheet balances when the trial balance does
    ratios     current, debt-equity, return on equity, inventory / receivables / payables turnover, net capital turnover,
               net profit, return on capital employed; a change over 25% is flagged (Schedule III asks for the reason)
    review     a line that moved over 25% and over the materiality amount (1% of revenue, at least ₹50,000) gets a plain
               question for the client
    checks     the trial balance doesn't balance · a suspense balance · debtors in credit / creditors in debit ·
               cash in credit · unmapped ledgers
"""
import json
import re
from collections import defaultdict

from sqlalchemy import text

from agentry.automations.ca import cleaner, core
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

# key -> (statement, section, label)
LINES = {
    "share_capital": ("bs_el", "Shareholders' funds", "Share capital / partners' or proprietor's capital"),
    "reserves": ("bs_el", "Shareholders' funds", "Reserves and surplus"),
    "lt_borrowings": ("bs_el", "Non-current liabilities", "Long-term borrowings"),
    "deferred_tax_liab": ("bs_el", "Non-current liabilities", "Deferred tax liabilities (net)"),
    "lt_provisions": ("bs_el", "Non-current liabilities", "Long-term provisions"),
    "st_borrowings": ("bs_el", "Current liabilities", "Short-term borrowings"),
    "trade_payables": ("bs_el", "Current liabilities", "Trade payables"),
    "other_cl": ("bs_el", "Current liabilities", "Other current liabilities"),
    "st_provisions": ("bs_el", "Current liabilities", "Short-term provisions"),
    "ppe": ("bs_a", "Non-current assets", "Property, plant and equipment"),
    "intangibles": ("bs_a", "Non-current assets", "Intangible assets"),
    "cwip": ("bs_a", "Non-current assets", "Capital work-in-progress"),
    "nc_investments": ("bs_a", "Non-current assets", "Non-current investments"),
    "deferred_tax_asset": ("bs_a", "Non-current assets", "Deferred tax assets (net)"),
    "lt_loans_adv": ("bs_a", "Non-current assets", "Long-term loans and advances"),
    "other_nca": ("bs_a", "Non-current assets", "Other non-current assets"),
    "current_investments": ("bs_a", "Current assets", "Current investments"),
    "inventories": ("bs_a", "Current assets", "Inventories"),
    "trade_receivables": ("bs_a", "Current assets", "Trade receivables"),
    "cash_bank": ("bs_a", "Current assets", "Cash and cash equivalents"),
    "st_loans_adv": ("bs_a", "Current assets", "Short-term loans and advances"),
    "other_ca": ("bs_a", "Current assets", "Other current assets"),
    "revenue": ("pl_i", "Income", "Revenue from operations"),
    "other_income": ("pl_i", "Income", "Other income"),
    "purchases": ("pl_e", "Expenses", "Purchases of stock-in-trade / materials consumed"),
    "opening_stock": ("pl_e", "Expenses", "Changes in inventories (opening stock)"),
    "employee": ("pl_e", "Expenses", "Employee benefits expense"),
    "finance": ("pl_e", "Expenses", "Finance costs"),
    "depreciation": ("pl_e", "Expenses", "Depreciation and amortisation expense"),
    "other_expenses": ("pl_e", "Expenses", "Other expenses"),
    "tax": ("pl_t", "Tax expense", "Tax expense (current and deferred)"),
    "suspense": ("check", "To clear", "Suspense"),
}
CREDIT_SIDE = {"bs_el", "pl_i"}
NAME_RULES: list[tuple[str, str]] = [  # (regex on the ledger name, line); first match wins
    (r"suspense", "suspense"), (r"opening stock|stock.*opening", "opening_stock"), (r"closing stock|stock.in.hand|stock.*closing|inventor", "inventories"),
    (r"accumulated depreciation|provision for depreciation", "ppe"), (r"depreciation|amorti[sz]ation", "depreciation"),
    (r"deferred tax", "deferred_tax_liab"), (r"provision for (income )?tax(ation)?", "st_provisions"),
    (r"income.?tax expense|current tax|tax expense|income.?tax (for|of) the year", "tax"),
    (r"salar|wages|bonus|staff welfare|employer.*(pf|esi)|(pf|esi|provident fund).*(contribution|employer)|gratuity|leave encashment|stipend", "employee"),
    (r"interest (received|income|on (fd|fixed deposit|deposit|savings))|dividend|discount received|rent received|profit on sale|commission received", "other_income"),
    (r"interest|loan processing|finance charges", "finance"),
    (r"^(sales?|revenue|turnover)\b|sales? (account|a/?c|local|interstate|inter-state|export|@)|service income|fees received|professional (receipts|income)", "revenue"),
    (r"purchases?\b", "purchases"),
    (r"\b(c|s|i|ut)?gst\b|gst (payable|input|output|credit)|\btds\b|\btcs\b|duties|professional tax|esi payable|pf payable", "_tax_ledger"),
    (r"advance tax|self.assessment tax", "other_ca"),
    (r"profit (&|and) loss|p ?& ?l a/?c|surplus|retained earnings|general reserve|securities premium", "reserves"),
    (r"share capital|equity shares|partner.*capital|capital a/?c|proprietor.*capital|^capital\b|drawings", "share_capital"),
    (r"\b(od|cc)\b|overdraft|cash credit", "st_borrowings"),
    (r"security deposit|rent deposit|electricity deposit", "other_nca"),
    (r"prepaid|advance to (supplier|staff|employee)|staff advance", "st_loans_adv"),
    (r"outstanding|expenses payable|audit fees? payable|salary payable", "other_cl"),
    (r"land|building|furniture|machinery|plant|vehicle|car\b|computer|laptop|equipment|fixtures|air.?condition", "ppe"),
    (r"software|goodwill|trademark|patent", "intangibles"),
    (r"cash\b|cash in hand|petty cash", "cash_bank"),
]
GROUP_RULES: list[tuple[str, str]] = [
    (r"suspense", "suspense"), (r"capital account|partners.? capital", "share_capital"), (r"reserves? (&|and) surplus|reserve", "reserves"),
    (r"secured loans|unsecured loans|loans \(liability\)|long.term borrow", "lt_borrowings"), (r"bank o\.?d|bank occ|overdraft|cash credit", "st_borrowings"),
    (r"sundry creditors|trade payable", "trade_payables"), (r"duties (&|and) taxes", "_tax_ledger"), (r"provisions", "st_provisions"),
    (r"current liabilities", "other_cl"), (r"fixed assets", "ppe"), (r"investments", "nc_investments"), (r"stock.in.hand", "inventories"),
    (r"sundry debtors|trade receivable", "trade_receivables"), (r"cash.in.hand|bank accounts", "cash_bank"), (r"deposits \(asset\)", "other_nca"),
    (r"loans (&|and) advances \(asset\)", "st_loans_adv"), (r"misc.*expenses \(asset\)", "other_nca"), (r"current assets", "other_ca"),
    (r"sales accounts", "revenue"), (r"purchase accounts", "purchases"), (r"direct incomes|indirect incomes|other income", "other_income"),
    (r"direct expenses|indirect expenses|expenses", "other_expenses"),
]
COMPANY_KINDS = ("company",)
QUESTIONS = {
    "revenue": "Sales moved {pct} ({amt}): new customers or products, price changes, or a large order? Any sales of the next year booked early?",
    "other_income": "Other income moved {pct} ({amt}): what is it (interest, a one-off gain, a sale of an asset)?",
    "purchases": "Purchases moved {pct} ({amt}) while sales moved {rev}: is all the stock bought counted in closing stock?",
    "employee": "Staff costs moved {pct} ({amt}): new hires, raises, a bonus paid this year?",
    "finance": "Interest moved {pct} ({amt}): a new loan or overdraft, or a higher rate?",
    "depreciation": "Depreciation moved {pct} ({amt}): assets bought or sold during the year? We'll need the bills.",
    "other_expenses": "Other expenses moved {pct} ({amt}): which expenses grew (rent, repairs, travel, professional fees)?",
    "trade_receivables": "Amounts due from customers moved {pct} ({amt}) while sales moved {rev}: are any customers paying late, or any amounts not recoverable?",
    "inventories": "Closing stock moved {pct} ({amt}): how was it counted and valued (cost or market value, whichever is lower)?",
    "trade_payables": "Amounts due to suppliers moved {pct} ({amt}): any suppliers paid late (MSME suppliers must be paid within 45 days)?",
    "lt_borrowings": "Long-term loans moved {pct} ({amt}): new loans or repayments? Please send the loan statements.",
    "st_borrowings": "Short-term borrowings / overdraft moved {pct} ({amt}): please send the year-end bank statement and sanction letter.",
    "ppe": "Fixed assets moved {pct} ({amt}): please send the bills for additions and details of anything sold or scrapped.",
    "cash_bank": "Cash and bank moved {pct} ({amt}): please confirm the year-end bank balances (statements).",
    "other_cl": "Other liabilities moved {pct} ({amt}): what's outstanding at year end (GST, TDS, salaries, expenses)?",
    "st_loans_adv": "Advances given moved {pct} ({amt}): to whom, and are they recoverable?",
}


def ledger_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _f(v: object) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return (cleaner._num(v) or 0.0) if isinstance(v, str) and v.strip() else 0.0


def _years(c: str) -> int:
    ys = [int(y) for y in re.findall(r"20(\d{2})", c)]
    return max(ys) if ys else 0


def read(rows: list[list[str]]) -> tuple[list[dict], dict, bool]:
    """(ledgers [{name, group, cy, py}], columns used, has previous year). Balances are signed: debit +, credit −."""
    c = cleaner.clean(rows, drop_duplicates=False)
    cols, kinds, data = c["columns"], c["kinds"], c["rows"]
    lc = [x.lower() for x in cols]
    name = next((j for j, x in enumerate(lc) if re.search(r"particulars|ledger|account|head|name", x) and kinds[j] == "text"), None)
    if name is None:
        name = next((j for j, k in enumerate(kinds) if k == "text"), None)
    group = next((j for j, x in enumerate(lc) if re.search(r"group|under|schedule|classification|parent", x) and j != name), None)
    prev = lambda x: bool(re.search(r"previous|prior|\bpy\b|last year|preceding", x))
    nums = [j for j, k in enumerate(kinds) if k == "number"]
    dr = [j for j in nums if re.search(r"debit|\bdr\b", lc[j])]
    cr = [j for j in nums if re.search(r"credit|\bcr\b", lc[j])]
    bal = [j for j in nums if j not in dr and j not in cr]

    def split(js: list[int]) -> tuple[int | None, int | None]:
        if not js:
            return None, None
        if len(js) == 1:
            return (None, js[0]) if prev(lc[js[0]]) else (js[0], None)
        p = [j for j in js if prev(lc[j])]
        if p:
            return next((j for j in js if j not in p), None), p[0]
        yrs = sorted(js, key=lambda j: _years(lc[j]), reverse=True)
        return (yrs[0], yrs[1]) if _years(lc[yrs[0]]) != _years(lc[yrs[1]]) else (js[0], js[1])
    (dcy, dpy), (ccy, cpy) = split(dr), split(cr)
    (bcy, bpy) = split(bal) if not dr else (None, None)
    if name is None or (dcy is None and bcy is None):
        raise core.CaError("this doesn't look like a trial balance: it needs a ledger column and Debit / Credit (or closing balance) columns")
    out = []
    for r in data:
        n = str(r[name] or "").strip()
        if not n or cleaner.TOTAL.match(n) or re.match(r"^(grand )?total|^difference in", n, re.IGNORECASE):
            continue
        cy = (_f(r[dcy]) - _f(r[ccy] if ccy is not None else 0)) if dcy is not None else _f(r[bcy])
        py = (_f(r[dpy]) - _f(r[cpy] if cpy is not None else 0)) if dpy is not None else (_f(r[bpy]) if bpy is not None else 0.0)
        if cy == 0 and py == 0:
            continue
        out.append({"name": n, "group": str(r[group] or "").strip() if group is not None else "", "cy": round(cy, 2), "py": round(py, 2)})
    used = {"ledger": cols[name], "group": cols[group] if group is not None else None,
            "this_year": " / ".join(cols[j] for j in (dcy, ccy, bcy) if j is not None),
            "previous_year": " / ".join(cols[j] for j in (dpy, cpy, bpy) if j is not None) or None}
    return out, used, bool(used["previous_year"])


def rule_line(name: str, group: str, balance: float) -> str | None:
    n, g = name.lower(), group.lower()
    line = next((ln for rx, ln in NAME_RULES if re.search(rx, n)), None)
    by_group = next((ln for rx, ln in GROUP_RULES if re.search(rx, g)), None) if g else None
    pl = lambda ln: ln in LINES and LINES[ln][0].startswith("pl")
    if line is None or (by_group and not pl(by_group) and by_group != "suspense" and pl(line) and line != "opening_stock"):
        line = by_group or line  # a balance-sheet group wins over a P&L-sounding name ("Salary Payable" under Current Liabilities)
    if line is None:
        if re.search(r"debtor|receivable", n):
            line = "trade_receivables"
        elif re.search(r"creditor|payable", n):
            line = "trade_payables"
        elif re.search(r"\bbank\b", n):
            line = "cash_bank"
        elif re.search(r"\bloan\b", n):
            line = "lt_borrowings" if balance < 0 else "st_loans_adv"
    if line == "_tax_ledger":
        line = "other_cl" if balance < 0 else "other_ca"
    if line == "cash_bank" and balance < 0 and re.search(r"bank", n + " " + g):
        line = "st_borrowings"  # an overdrawn bank account is a borrowing
    return line


async def map_ledgers(org_id: str | None, ledgers: list[dict], learned: dict[str, str], use_model: bool = True) -> None:
    """Sets ledger["line"] and ledger["how"] (learned / rule / ai / None) in place."""
    left = []
    for i, x in enumerate(ledgers):
        bal = x["cy"] or x["py"]
        if (ln := learned.get(ledger_key(x["name"]))) in LINES:
            x["line"], x["how"] = ln, "learned"
        elif ln := rule_line(x["name"], x["group"], bal):
            x["line"], x["how"] = ln, "rule"
        else:
            x["line"], x["how"] = None, None
            left.append(i)
    if not left or not use_model:
        return
    prompt = load("ca_ledger_map")
    msgs = prompt.render(lines="\n".join(f"- {k}: {v[2]}" for k, v in LINES.items() if not k.startswith("_")),
                         ledgers="\n".join(f"{i} | {ledgers[i]['name']} | {ledgers[i]['group'] or '-'} | {'Dr' if (ledgers[i]['cy'] or ledgers[i]['py']) > 0 else 'Cr'} | "
                                           f"{abs(ledgers[i]['cy'] or ledgers[i]['py']):,.0f}" for i in left[:150]))
    try:
        res = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps({"ledgers": []}), temperature=0)
        got = res.data.get("ledgers", []) if isinstance(res.data, dict) else []
    except AllModelsFailed:
        got = []
    for g in got:
        try:
            i, ln = int(g["i"]), str(g["line"])
        except (KeyError, TypeError, ValueError):
            continue
        if i in left and ln in LINES and ln != "suspense":
            ledgers[i]["line"], ledgers[i]["how"], ledgers[i]["why"] = ln, "ai", str(g.get("why") or "")[:120]


def build(ledgers: list[dict], *, has_py: bool, kind: str = "company", client: str = "") -> dict:
    """The statements, ratios, review and checks from mapped ledgers (re-run after every correction)."""
    amt: dict[str, dict[str, float]] = defaultdict(lambda: {"cy": 0.0, "py": 0.0})
    closing = {"cy": 0.0, "py": 0.0}
    tb = {"cy": 0.0, "py": 0.0}
    checks: list[dict] = []
    for x in ledgers:
        ln = x.get("line")
        is_closing = ln == "inventories" and re.search(r"closing|stock.in.hand|inventor", x["name"].lower())
        for y in ("cy", "py"):
            if not is_closing:
                tb[y] += x[y]
            else:
                closing[y] += x[y]
            if ln:
                amt[ln][y] += x[y]
    # sign: assets / expenses as debit (+), liabilities / income as credit (shown +)
    shown = {k: {y: round(-v[y] if LINES[k][0] in CREDIT_SIDE else v[y], 2) for y in v} for k, v in amt.items() if k in LINES}

    def g(k: str, y: str) -> float:
        return shown.get(k, {}).get(y, 0.0)
    pl = {}
    for y in ("cy", "py"):
        income = g("revenue", y) + g("other_income", y)
        change = g("opening_stock", y) - closing[y]
        exp = g("purchases", y) + change + g("employee", y) + g("finance", y) + g("depreciation", y) + g("other_expenses", y)
        pbt = income - exp
        pl[y] = {"revenue": g("revenue", y), "other_income": g("other_income", y), "total_income": round(income, 2), "purchases": g("purchases", y),
                 "change_inventory": round(change, 2), "employee": g("employee", y), "finance": g("finance", y), "depreciation": g("depreciation", y),
                 "other_expenses": g("other_expenses", y), "total_expenses": round(exp, 2), "pbt": round(pbt, 2), "tax": g("tax", y),
                 "pat": round(pbt - g("tax", y), 2)}
    profit_to = "reserves" if kind in COMPANY_KINDS else "share_capital"
    bs_lines = {}
    for k, (st, _sec, _lbl) in LINES.items():
        if st in ("bs_el", "bs_a"):
            bs_lines[k] = {y: g(k, y) + (pl[y]["pat"] if k == profit_to else 0.0) for y in ("cy", "py")}
    for y in ("cy", "py"):
        bs_lines["inventories"][y] = round(closing[y] + (g("inventories", y) - closing[y]), 2)

    def side(st: str) -> list[dict]:
        secs: dict[str, list] = defaultdict(list)
        for k, (s_, sec, lbl) in LINES.items():
            if s_ == st and (bs_lines[k]["cy"] or bs_lines[k]["py"]):
                secs[sec].append({"key": k, "label": lbl, "cy": round(bs_lines[k]["cy"], 2), "py": round(bs_lines[k]["py"], 2)})
        return [{"section": s, "lines": ls, "cy": round(sum(x["cy"] for x in ls), 2), "py": round(sum(x["py"] for x in ls), 2)} for s, ls in secs.items()]
    el, assets = side("bs_el"), side("bs_a")
    tot = {y: {"el": round(sum(s[y] for s in el), 2), "a": round(sum(s[y] for s in assets), 2)} for y in ("cy", "py")}

    # ---- checks ----
    for y, label in (("cy", "this year"), ("py", "last year")):
        if y == "py" and not has_py:
            continue
        if abs(tb[y]) > 1:
            checks.append({"severity": "high", "what": f"The trial balance doesn't balance {label}: debits exceed credits by {core.inr(tb[y])}" if tb[y] > 0
                           else f"The trial balance doesn't balance {label}: credits exceed debits by {core.inr(-tb[y])}"})
        if abs(tot[y]["el"] - tot[y]["a"]) > 1 and abs(tb[y]) <= 1:
            left_out = sum(x[y] for x in ledgers if not x.get("line") or x["line"] == "suspense")
            why = ("the suspense balance and the ledgers not placed yet" if abs(left_out + tot[y]["a"] - tot[y]["el"]) <= 1 else "check the ledgers' placing")
            checks.append({"severity": "high", "what": f"The balance sheet is out by {core.inr(abs(tot[y]['a'] - tot[y]['el']))} {label}: {why}"})
    unmapped = [x for x in ledgers if not x.get("line")]
    if unmapped:
        checks.append({"severity": "high", "what": f"{len(unmapped)} ledger(s) not placed yet (kept out of the statements): "
                       + ", ".join(f"{x['name']} ({core.inr(x['cy'])})" for x in unmapped[:8])})
    if g("suspense", "cy"):
        checks.append({"severity": "high", "what": f"Suspense account has {core.inr(amt['suspense']['cy'])}: clear it before finalising"})
    ai = [x for x in ledgers if x.get("how") == "ai"]
    if ai:
        checks.append({"severity": "medium", "what": f"{len(ai)} ledger(s) placed by the AI: check them (" + ", ".join(x["name"] for x in ai[:6]) + ")"})
    for x in ledgers:
        if x.get("line") == "trade_receivables" and x["cy"] < -1:
            checks.append({"severity": "medium", "what": f"{x['name']} (a debtor) has a credit balance {core.inr(-x['cy'])}: an advance from a customer? show it under other current liabilities"})
        elif x.get("line") == "trade_payables" and x["cy"] > 1:
            checks.append({"severity": "medium", "what": f"{x['name']} (a creditor) has a debit balance {core.inr(x['cy'])}: an advance to a supplier? show it under loans and advances"})
        elif x.get("line") == "cash_bank" and x["cy"] < -1 and re.search(r"cash", x["name"].lower()):
            checks.append({"severity": "high", "what": f"{x['name']} is negative ({core.inr(x['cy'])}): cash can't be in credit; entries are missing or wrongly dated"})

    # ---- ratios (Schedule III, Division I note: explain a change over 25%) ----
    def ratio(y: str) -> dict[str, float | None]:
        b = {k: bs_lines[k][y] for k in bs_lines}
        p = pl[y]
        ca = sum(b[k] for k in ("current_investments", "inventories", "trade_receivables", "cash_bank", "st_loans_adv", "other_ca"))
        cl = sum(b[k] for k in ("st_borrowings", "trade_payables", "other_cl", "st_provisions"))
        equity = b["share_capital"] + b["reserves"]
        debt = b["lt_borrowings"] + b["st_borrowings"]
        cogs = p["purchases"] + p["change_inventory"]
        div = lambda a, z: round(a / z, 2) if z else None
        return {"Current ratio": div(ca, cl), "Debt-equity ratio": div(debt, equity), "Return on equity (%)": div(p["pat"] * 100, equity),
                "Inventory turnover (times)": div(cogs, b["inventories"]), "Trade receivables turnover (times)": div(p["revenue"], b["trade_receivables"]),
                "Trade payables turnover (times)": div(p["purchases"], b["trade_payables"]), "Net capital turnover (times)": div(p["revenue"], ca - cl),
                "Net profit ratio (%)": div(p["pat"] * 100, p["revenue"]),
                "Return on capital employed (%)": div((p["pbt"] + p["finance"]) * 100, equity + debt)}
    rc, rp = ratio("cy"), ratio("py") if has_py else {}
    ratios = []
    for k, v in rc.items():
        pv = rp.get(k)
        ch = round((v - pv) / abs(pv) * 100, 1) if v is not None and pv not in (None, 0) else None
        ratios.append({"name": k, "cy": v, "py": pv, "change_pct": ch, "explain": ch is not None and abs(ch) > 25})

    # ---- year-on-year review ----
    review = []
    if has_py:
        mat = max(50000.0, abs(pl["cy"]["revenue"]) * 0.01)
        rev_pct = (pl["cy"]["revenue"] - pl["py"]["revenue"]) / abs(pl["py"]["revenue"]) * 100 if pl["py"]["revenue"] else None
        figs = {**{k: (v["cy"], v["py"]) for k, v in bs_lines.items()},
                **{k: (pl["cy"][k], pl["py"][k]) for k in ("revenue", "other_income", "purchases", "employee", "finance", "depreciation", "other_expenses")}}
        for k, (cy, py) in figs.items():
            if k in ("share_capital", "reserves") or not py:
                continue
            pct = (cy - py) / abs(py) * 100
            if abs(pct) > 25 and abs(cy - py) >= mat:
                q = QUESTIONS.get(k, "{label} moved {pct} ({amt}): what changed?").format(
                    label=LINES[k][2], pct=f"{pct:+.0f}%", amt=f"{core.inr(py)} to {core.inr(cy)}", rev=f"{rev_pct:+.0f}%" if rev_pct is not None else "-")
                review.append({"key": k, "label": LINES[k][2], "cy": round(cy, 2), "py": round(py, 2), "change_pct": round(pct, 1), "question": q})
        for x in ledgers:  # a P&L ledger that moved a lot, inside a line that may not have
            if LINES.get(x.get("line") or "", ("",))[0] in ("pl_i", "pl_e") and x["py"] and abs(x["cy"] - x["py"]) >= mat:
                pct = (x["cy"] - x["py"]) / abs(x["py"]) * 100
                if abs(pct) > 25:
                    review.append({"key": f"ledger:{x['name']}", "label": x["name"], "cy": abs(x["cy"]), "py": abs(x["py"]), "change_pct": round(pct, 1),
                                   "question": f"{x['name']} moved {pct:+.0f}% ({core.inr(abs(x['py']))} to {core.inr(abs(x['cy']))}): what changed? "
                                               "Please send the agreement or bills behind it."})
        review.sort(key=lambda r: -abs(r["cy"] - r["py"]))
    sev = {"high": 0, "medium": 1, "low": 2}
    checks.sort(key=lambda c: sev[c["severity"]])
    return {"client": client, "kind": kind, "has_py": has_py, "ledgers": ledgers, "balance_sheet": {"equity_liabilities": el, "assets": assets, "totals": tot,
            "balanced": all(abs(tot[y]["el"] - tot[y]["a"]) <= 1 for y in ("cy", "py"))}, "profit_and_loss": pl, "profit_to": LINES[profit_to][2],
            "ratios": ratios, "review": review, "checks": checks,
            "summary": {"ledgers": len(ledgers), "rules": sum(1 for x in ledgers if x.get("how") == "rule"), "learned": sum(1 for x in ledgers if x.get("how") == "learned"),
                        "ai": len(ai), "unmapped": len(unmapped), "questions": len(review)}}


async def learned_map(conn) -> dict[str, str]:
    return {r.ledger_key: r.line for r in (await conn.execute(text("select ledger_key, line from app.ca_ledger_map"))).all()}


async def prepare(org_id: str | None, conn, data: bytes, mime: str, *, kind: str = "company", client: str = "", use_model: bool = True) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("financial statements work from a trial balance in CSV or Excel (.xlsx), e.g. Tally's trial balance export")
    ledgers, used, has_py = read(core.table_rows(data, mime))
    await map_ledgers(org_id, ledgers, await learned_map(conn) if conn is not None else {}, use_model)
    return build(ledgers, has_py=has_py, kind=kind, client=client) | {"columns": used}


async def correct(conn, org_id: str, result: dict, ledger: str, line: str, learn: bool, user_id: str | None) -> dict:
    if line not in LINES:
        raise core.CaError("unknown line")
    hit = [x for x in result["ledgers"] if x["name"] == ledger]
    if not hit:
        raise core.CaError("no such ledger in this trial balance")
    for x in hit:
        x["line"], x["how"] = line, "corrected"
    if learn:
        await conn.execute(text("""insert into app.ca_ledger_map (org_id, ledger_key, line, created_by) values (:o, :k, :l, :u)
            on conflict (org_id, ledger_key) do update set line = excluded.line, created_by = excluded.created_by"""),
            {"o": org_id, "k": ledger_key(ledger), "l": line, "u": user_id})
    return build(result["ledgers"], has_py=result["has_py"], kind=result["kind"], client=result.get("client", "")) | {"columns": result.get("columns")}


def sheet(result: dict) -> bytes:
    bs, pl = result["balance_sheet"], result["profit_and_loss"]
    py = result["has_py"]
    head = ["Particulars", "This year", *(["Previous year"] if py else [])]

    def row(label: str, cy: float, pyv: float) -> list:
        return [label, round(cy, 2), *([round(pyv, 2)] if py else [])]
    b = [head, ["EQUITY AND LIABILITIES"]]
    for s in bs["equity_liabilities"]:
        b += [[s["section"]], *[row(f"   {x['label']}", x["cy"], x["py"]) for x in s["lines"]], row(f"Total {s['section'].lower()}", s["cy"], s["py"])]
    b += [row("TOTAL", bs["totals"]["cy"]["el"], bs["totals"]["py"]["el"]), [], ["ASSETS"]]
    for s in bs["assets"]:
        b += [[s["section"]], *[row(f"   {x['label']}", x["cy"], x["py"]) for x in s["lines"]], row(f"Total {s['section'].lower()}", s["cy"], s["py"])]
    b += [row("TOTAL", bs["totals"]["cy"]["a"], bs["totals"]["py"]["a"])]
    labels = [("revenue", "Revenue from operations"), ("other_income", "Other income"), ("total_income", "Total income"), ("purchases", "Purchases / materials"),
              ("change_inventory", "Changes in inventories"), ("employee", "Employee benefits expense"), ("finance", "Finance costs"),
              ("depreciation", "Depreciation and amortisation"), ("other_expenses", "Other expenses"), ("total_expenses", "Total expenses"),
              ("pbt", "Profit before tax"), ("tax", "Tax expense"), ("pat", "Profit for the year")]
    p = [head, *[row(lbl, pl["cy"][k], pl["py"][k]) for k, lbl in labels]]
    return core.xlsx_bytes({
        "Balance sheet": b, "Profit and loss": p,
        "Ratios": [["Ratio", "This year", "Previous year", "Change %", "Explain (over 25%)"],
                   *[[r["name"], r["cy"], r["py"], r["change_pct"], "yes" if r["explain"] else ""] for r in result["ratios"]]],
        "Questions for client": [["Line", "Previous year", "This year", "Change %", "Question"],
                                 *[[q["label"], q["py"], q["cy"], q["change_pct"], q["question"]] for q in result["review"]]],
        "Mapping": [["Ledger", "Group", "This year (Dr +)", "Previous year", "Schedule III line", "Placed by"],
                    *[[x["name"], x["group"], x["cy"], x["py"], LINES[x["line"]][2] if x.get("line") else "NOT PLACED", x.get("how") or ""] for x in result["ledgers"]]],
        "Checks": [["Severity", "Check"], *[[c["severity"], c["what"]] for c in result["checks"]]],
    })
