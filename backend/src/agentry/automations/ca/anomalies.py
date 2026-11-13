"""Anomaly finder (CA desk part 2, docs/PLAN-CA-DESK-2.md #2): a ledger, day book or sales / purchase register scanned for
what a reviewer looks for before the partner (or the auditor) does. All by rules (no AI); each finding lists its rows and why.

The sheet is first read by the Excel cleaner (header found, totals and page-break headers dropped, amounts and dates made
usable), keeping duplicate rows so they can be reported. Columns are found by their names (date, voucher, party, GSTIN,
amount, taxable value, IGST / CGST / SGST, place of supply); a check whose columns aren't there is skipped and said so.

    high    possible duplicates (same party, amount and date; or the same row twice) · a voucher / invoice number used twice ·
            cash paid to one person in a day above the 40A(3) limit (split entries added up) · cash received above the
            269ST limit · IGST charged on a same-state supply or CGST + SGST on an other-state one · an invalid GSTIN ·
            dates outside the year, or in the future
    medium  amounts just under a limit (cash, 194C, ₹50,000, ₹2 lakh) · an amount far above that party's usual ·
            tax not at a GST rate · entries on national holidays
    low     round amounts · Sunday entries · gaps in a voucher series · Benford first-digit test of the amounts
Limits are official figures (official_rules audit.*, tds.*).
"""
import math
import re
from collections import Counter, defaultdict
from datetime import date
from itertools import pairwise

from agentry import official_rules as rules
from agentry.automations.ca import cleaner, core

ROWS_PER_FINDING = 200
# total GST as % of the taxable value (within 0.6 points): the 2025 slabs 5 / 18 / 40, the older 12 / 28 still in books, and the
# special ones (0.1 merchant exporters, 0.25 rough diamonds, 1 / 1.5 / 3 housing, jewellery and metals)
GST_RATES = (0, 0.1, 0.25, 1, 1.5, 3, 5, 12, 18, 28, 40)
HOLIDAYS = {(1, 26): "Republic Day", (8, 15): "Independence Day", (10, 2): "Gandhi Jayanti"}
SEVERITY = {"high": 0, "medium": 1, "low": 2}
BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
STATES = {"andhra": "37", "arunachal": "12", "assam": "18", "bihar": "10", "chhattisgarh": "22", "goa": "30", "gujarat": "24", "haryana": "06",
          "himachal": "02", "jharkhand": "20", "karnataka": "29", "kerala": "32", "madhya pradesh": "23", "maharashtra": "27", "manipur": "14",
          "meghalaya": "17", "mizoram": "15", "nagaland": "13", "odisha": "21", "orissa": "21", "punjab": "03", "rajasthan": "08", "sikkim": "11",
          "tamil nadu": "33", "telangana": "36", "tripura": "16", "uttar pradesh": "09", "uttarakhand": "05", "west bengal": "19", "delhi": "07",
          "jammu": "01", "ladakh": "38", "chandigarh": "04", "puducherry": "34", "pondicherry": "34", "lakshadweep": "31", "andaman": "35",
          "dadra": "26", "daman": "26"}


def _col(cols: list[str], kinds: list[str], pattern: str, kind: str | None = None, avoid: str | None = None) -> int | None:
    for j, c in enumerate(cols):
        if re.search(pattern, c, re.IGNORECASE) and (kind is None or kinds[j] == kind) and not (avoid and re.search(avoid, c, re.IGNORECASE)):
            return j
    return None


def columns(cols: list[str], kinds: list[str]) -> dict[str, int | None]:
    num = "number"
    amount = (_col(cols, kinds, r"^amount \(dr", num) or _col(cols, kinds, r"^(amount|total|invoice value|gross|net amount|bill amount|value)\b", num, r"tax|gst")
              or _col(cols, kinds, r"amount|total|debit|dr\b", num, r"taxable|igst|cgst|sgst|cess|tds"))
    taxable = _col(cols, kinds, r"taxable|assessable", num)
    if amount is None:  # else the taxable value, else the last number column
        amount = taxable if taxable is not None else next((j for j in range(len(kinds) - 1, -1, -1) if kinds[j] == num), None)
    return {
        "date": next((j for j, k in enumerate(kinds) if k == "date" and not re.search(r"due|paid|invoice date|bill date", cols[j], re.IGNORECASE)), None)
        if any(k == "date" for k in kinds) else None,
        "voucher": _col(cols, kinds, r"voucher|vch|invoice\s*(no|num|#)|inv\s*no|bill\s*no|doc(ument)?\s*no|ref(erence)?\s*no|^no\.?$|number", None, r"gstin|pan|phone|mobile|hsn|account"),
        "party": _col(cols, kinds, r"party|customer|supplier|vendor|name|debtor|creditor|client|buyer|seller", "text") or _col(cols, kinds, r"particulars|ledger", "text"),
        "gstin": next((j for j, k in enumerate(kinds) if k == "gstin"), None),
        "amount": amount, "taxable": taxable,
        "igst": _col(cols, kinds, r"\bigst\b|integrated", num), "cgst": _col(cols, kinds, r"\bcgst\b|central tax", num),
        "sgst": _col(cols, kinds, r"\bsgst\b|\butgst\b|state tax|state/ut", num),
        "pos": _col(cols, kinds, r"place of supply|\bpos\b"),
    }


def _state(v: object) -> str | None:
    s = str(v or "").strip().lower()
    m = re.match(r"^(\d{2})(?!\d)", s)
    if m:
        return m[1]
    return next((code for name, code in STATES.items() if name in s), None)


def _f(v: object) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def find(rows: list[list[str]], *, firm_gstin: str | None = None, fy_start: int | None = None, as_of: date | None = None) -> dict:
    """The findings for one sheet. firm_gstin: the client's own (for same-state vs other-state); else worked out from the
    rows. fy_start: the financial year (2026 = FY 2026-27); else the year most dates fall in."""
    c = cleaner.clean(rows, drop_duplicates=False)
    cols, kinds, data, src = c["columns"], c["kinds"], c["rows"], c["source_rows"]
    k = columns(cols, kinds)
    as_of = as_of or date.today()
    findings: list[dict] = []
    skipped: list[str] = []

    def val(r: list, key: str) -> object:
        return r[k[key]] if k[key] is not None else None

    def line(i: int, note: str = "") -> dict:
        r = data[i]
        return {"row": src[i], "date": val(r, "date"), "voucher": val(r, "voucher"), "party": val(r, "party"),
                "amount": val(r, "amount"), "note": note}

    def add(key: str, severity: str, title: str, why: str, hits: list[dict]) -> None:
        if hits:
            findings.append({"key": key, "severity": severity, "title": title, "why": why, "count": len(hits), "rows": hits[:ROWS_PER_FINDING]})

    dates = [date.fromisoformat(v) if isinstance(v := val(r, "date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None for r in data]
    amounts = [_f(val(r, "amount")) for r in data]
    parties = [str(val(r, "party") or "").strip() for r in data]
    is_cash = [any(isinstance(x, str) and re.search(r"\bcash\b", x, re.IGNORECASE) for j, x in enumerate(r) if j != k["party"]) for r in data]
    is_receipt = [any(isinstance(x, str) and re.search(r"\breceipt|\bsales?\b|received", x, re.IGNORECASE) for j, x in enumerate(r) if j != k["party"]) for r in data]
    for need, label in (("date", "a date column"), ("amount", "an amount column"), ("party", "a party column")):
        if k[need] is None:
            skipped.append(f"No {label} found: checks that need it were skipped")

    # --- duplicates ---
    exact: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(data):
        exact[tuple(r)].append(i)
    hits = [line(i, f"same as row {src[ix[0]]}") for ix in exact.values() if len(ix) > 1 for i in ix[1:]]
    add("exact_duplicate", "high", "The same row entered twice", "Every column is identical: usually an entry posted twice.", hits)
    if k["party"] is not None and k["amount"] is not None and k["date"] is not None:
        same: dict[tuple, list[int]] = defaultdict(list)
        for i in range(len(data)):
            if parties[i] and amounts[i] and dates[i]:
                same[(parties[i].lower(), round(amounts[i], 2), dates[i])].append(i)
        dup_rows = {i for ix in exact.values() if len(ix) > 1 for i in ix[1:]}
        hits = [line(i, f"{len(ix)} entries: rows " + ", ".join(str(src[x]) for x in ix)) for ix in same.values()
                if len(ix) > 1 and not set(ix[1:]) <= dup_rows for i in ix]
        add("possible_duplicate", "high", "Same party, same amount, same day",
            "Different voucher numbers but the same party, amount and date: check it isn't one bill booked twice.", hits)

    # --- voucher numbers ---
    if k["voucher"] is not None:
        used: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(data):
            v = str(val(r, "voucher") or "").strip()
            if v:
                used[v.upper()].append(i)
        dup_rows = {i for ix in exact.values() if len(ix) > 1 for i in ix[1:]}
        hits = [line(i, f"{v} used {len(ix)} times") for v, ix in used.items() if len([x for x in ix if x not in dup_rows]) > 1 for i in ix]
        add("voucher_repeated", "high", "A voucher / invoice number used twice",
            "A number in a series should appear once: a second bill from the same supplier, or a typing slip.", hits)
        series: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for v, ix in used.items():
            m = re.match(r"^(.*?)(\d+)$", v)
            if m and len(m[2]) <= 8:
                series[m[1]].append((int(m[2]), ix[0]))
        gaps = []
        for prefix, nums in series.items():
            ns = sorted({n for n, _ in nums})
            if len(ns) < 10:
                continue
            missing = [n for a, b in pairwise(ns) if 1 < b - a <= 50 for n in range(a + 1, b)]
            if missing and len(missing) <= max(5, len(ns) // 5):  # a real series with a few holes, not sparse numbering
                runs, start = [], missing[0]
                for a, b in zip(missing, [*missing[1:], None], strict=False):
                    if b != a + 1:
                        runs.append(f"{prefix}{start}" if start == a else f"{prefix}{start} to {prefix}{a}")
                        start = b
                gaps += [{"row": None, "date": None, "voucher": run, "party": None, "amount": None, "note": "missing from the series"} for run in runs]
        add("voucher_gap", "low", "Gaps in a voucher series",
            "Numbers missing from the series: cancelled vouchers should be on record; otherwise an entry may be missing.", gaps)
    else:
        skipped.append("No voucher / invoice number column: repeat and gap checks skipped")

    # --- cash limits (40A(3) a person a day, 269ST receipts) ---
    if k["amount"] is not None:
        pay_limit, rec_limit = rules.num("audit.cash_limit"), rules.num("audit.cash_receipt")
        by_day: dict[tuple, list[int]] = defaultdict(list)
        for i in range(len(data)):
            if is_cash[i] and amounts[i]:
                by_day[(parties[i].lower(), dates[i], is_receipt[i])].append(i)
        hits, rec_hits = [], []
        for (p, d, receipt), ix in by_day.items():
            total = sum(abs(amounts[i]) for i in ix)
            if receipt and total >= rec_limit:
                rec_hits += [line(i, f"cash received {core.inr(total)} that day") for i in ix]
            elif not receipt and total > pay_limit:
                note = f"{len(ix)} cash entries adding to {core.inr(total)} that day" if len(ix) > 1 else f"cash {core.inr(total)}"
                hits += [line(i, note) for i in ix]
        add("cash_payment", "high", f"Cash paid to one person in a day above {core.inr(pay_limit)}",
            f"Section 40A(3): an expense paid in cash above {core.inr(pay_limit)} to one person in a day is disallowed "
            f"({core.inr(rules.num('audit.cash_limit_transport'))} for transporters). Split entries on one day are added up.", hits)
        add("cash_receipt", "high", f"Cash received from one person in a day of {core.inr(rec_limit)} or more",
            f"Section 269ST: receiving {core.inr(rec_limit)} or more in cash is not allowed; the penalty equals the amount.", rec_hits)

    # --- GST: tax type vs place of supply, rate, GSTIN ---
    tax_cols = k["igst"] is not None or k["cgst"] is not None
    if tax_cols:
        firm = (firm_gstin or "")[:2] if firm_gstin else None
        if not firm:  # the state most CGST / SGST rows are in is the firm's own
            local = Counter(_state(val(r, "pos")) or _state(val(r, "gstin")) for r in data if _f(val(r, "cgst")) > 0)
            local.pop(None, None)
            firm = local.most_common(1)[0][0] if local else None
        hits = []
        for i, r in enumerate(data):
            st = _state(val(r, "pos")) or _state(val(r, "gstin"))
            if not firm or not st:
                continue
            ig, cg = _f(val(r, "igst")), _f(val(r, "cgst")) + _f(val(r, "sgst"))
            if st == firm and ig > 0:
                hits.append(line(i, f"same state ({st}) but IGST {core.inr(ig)}"))
            elif st != firm and cg > 0:
                hits.append(line(i, f"other state ({st}) but CGST + SGST {core.inr(cg)}"))
        add("tax_type", "high", "Wrong tax type for the place of supply",
            "IGST is for a supply to another state, CGST + SGST within the state. Charged the wrong way, the tax must be paid again the "
            "right way and the wrong one claimed back.", hits)
        if k["taxable"] is not None:
            hits = []
            for i, r in enumerate(data):
                base = _f(val(r, "taxable"))
                tax = _f(val(r, "igst")) + _f(val(r, "cgst")) + _f(val(r, "sgst"))
                if base > 0 and tax > 0:
                    pct = tax / base * 100
                    if min(abs(pct - g) for g in GST_RATES) > 0.6:
                        hits.append(line(i, f"tax is {pct:.1f}% of the taxable value"))
            add("tax_rate", "medium", "Tax not at a GST rate", "The tax isn't 5%, 18%, 40% (or an older 12% / 28%) of the taxable value: a "
                "wrong rate, a typing slip or a mixed bill to split.", hits)
    if k["gstin"] is not None:
        from agentry.documents import gstin_ok
        hits = [line(i, str(val(r, "gstin"))) for i, r in enumerate(data) if val(r, "gstin") and not gstin_ok(str(val(r, "gstin")))]
        add("gstin_invalid", "high", "GSTIN not valid", "The format or check digit is wrong: input tax credit on it will fail. Ask the "
            "party for the GSTIN on their certificate.", hits)

    # --- dates ---
    if k["date"] is not None and any(dates):
        if fy_start is None:
            fy_start = Counter(d.year if d.month >= 4 else d.year - 1 for d in dates if d).most_common(1)[0][0]
        lo, hi = date(fy_start, 4, 1), date(fy_start + 1, 3, 31)
        hits = [line(i, "in the future" if d > as_of else f"outside FY {fy_start}-{str(fy_start + 1)[2:]}") for i, d in enumerate(dates)
                if d and (d < lo or d > hi or d > as_of)]
        add("out_of_period", "high", "Dated outside the year", f"The rows are for FY {fy_start}-{str(fy_start + 1)[2:]}: these fall outside "
            "it (or in the future). A wrong year typed, or an entry in the wrong books.", hits)
        add("holiday", "medium", "Entries on a national holiday",
            "Business is rarely done on Republic Day, Independence Day or Gandhi Jayanti: worth a look.",
            [line(i, HOLIDAYS[(d.month, d.day)]) for i, d in enumerate(dates) if d and (d.month, d.day) in HOLIDAYS])
        add("sunday", "low", "Entries on a Sunday", "Fine for a shop open on Sundays; otherwise check the date.",
            [line(i, "Sunday") for i, d in enumerate(dates) if d and d.weekday() == 6])

    # --- amounts: just under limits, round, outliers, Benford ---
    if k["amount"] is not None:
        limits = sorted({rules.num("audit.cash_limit"), float(rules.tds_rates()["194C"][2]),
                         50000.0, rules.num("audit.cash_receipt")})
        hits = []
        for i, a in enumerate(amounts):
            x = abs(a)
            lim = next((m for m in limits if m * 0.97 <= x < m and (is_cash[i] or m != limits[0])), None)
            if lim:
                hits.append(line(i, f"{core.inr(lim - x)} under {core.inr(lim)}"))
        add("just_under", "medium", "Just under a limit", "Amounts a little under a limit (cash, TDS, ₹50,000, ₹2 lakh) can mean a bill "
            "split or sized to stay under it.", hits)
        hits = [line(i, "round amount") for i, a in enumerate(amounts) if abs(a) >= 10000 and abs(a) % 1000 == 0]
        if hits and len(hits) <= max(10, len(amounts) // 10):  # only when round amounts stand out
            add("round", "low", "Round amounts", "Real bills rarely come to an exact thousand: check these are backed by a bill, not an estimate.", hits)
        if k["party"] is not None:
            by_party: dict[str, list[int]] = defaultdict(list)
            for i, p in enumerate(parties):
                if p and amounts[i]:
                    by_party[p.lower()].append(i)
            hits = []
            for ix in by_party.values():
                if len(ix) < 5:
                    continue
                vals = sorted((abs(amounts[i]) for i in ix), reverse=True)
                top, nxt, med = vals[0], vals[1], vals[len(vals) // 2]
                if top >= 25000 and top > 4 * nxt:  # stands alone: far above every other entry for the party
                    i = next(i for i in ix if abs(amounts[i]) == top)
                    hits.append(line(i, f"{top / med:.0f}× this party's usual {core.inr(med)}; the next largest is {core.inr(nxt)}"))
            add("outlier", "medium", "Far above the party's usual", "Much larger than this party's other entries: check the bill (an extra "
                "zero is common).", hits)
    benford = None
    firsts = [int(str(f"{abs(a):.2f}").lstrip("0.")[0]) for a in amounts if abs(a) >= 10]
    if len(firsts) >= 100:
        n = len(firsts)
        got = Counter(firsts)
        digits = [{"digit": d, "expected": round(BENFORD[d] * 100, 1), "actual": round(got[d] / n * 100, 1)} for d in range(1, 10)]
        mad = sum(abs(got[d] / n - BENFORD[d]) for d in range(1, 10)) / 9
        chi2 = sum((got[d] - n * BENFORD[d]) ** 2 / (n * BENFORD[d]) for d in range(1, 10))
        # chi-square with 8 degrees of freedom: 15.51 at 5%, 20.09 at 1% (the MAD bands alone are for thousands of amounts)
        verdict = "fits" if chi2 < 15.51 else "marginal" if chi2 < 20.09 else "does not fit"
        benford = {"n": n, "digits": digits, "mad": round(mad, 4), "chi2": round(chi2, 2), "verdict": verdict}
        if verdict == "does not fit":
            far = max(digits, key=lambda x: x["actual"] - x["expected"])
            add("benford", "medium" if chi2 > 40 else "low", "First digits don't follow Benford's law",
                f"In natural amounts about 30% start with 1 and 5% with 9; here {far['actual']}% start with {far['digit']} "
                f"(expected {far['expected']}%). Not proof of anything: a sign to look at how the amounts were made.",
                [line(i, f"starts with {far['digit']}") for i, a in enumerate(amounts) if abs(a) >= 10 and str(f"{abs(a):.2f}").lstrip("0.")[0] == str(far["digit"])])
    elif amounts:
        skipped.append(f"Benford test needs 100 amounts or more ({len(firsts)} here)")

    findings.sort(key=lambda f: (SEVERITY[f["severity"]], -f["count"]))
    return {"findings": findings, "skipped": skipped, "columns": {key: cols[j] if j is not None else None for key, j in k.items()},
            "benford": benford, "fy_start": fy_start,
            "summary": {"rows": len(data), "header_row": c["summary"]["header_row"], "total": round(sum(amounts), 2),
                        "high": sum(f["count"] for f in findings if f["severity"] == "high"),
                        "medium": sum(f["count"] for f in findings if f["severity"] == "medium"),
                        "low": sum(f["count"] for f in findings if f["severity"] == "low")}}


def compute(data: bytes, mime: str, **kw) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("the anomaly finder works on CSV or Excel (.xlsx) files; turn a PDF into Excel first with PDF to Excel")
    return find(core.table_rows(data, mime), **kw)


def sheet(result: dict) -> bytes:
    f = result["findings"]
    out = {
        "Findings": [["Severity", "Finding", "How many", "Why it matters"], *[[x["severity"], x["title"], x["count"], x["why"]] for x in f]],
        "Rows": [["Finding", "Row", "Date", "Voucher", "Party", "Amount", "Note"],
                 *[[x["title"], r["row"], r["date"], r["voucher"], r["party"], r["amount"], r["note"]] for x in f for r in x["rows"]]],
    }
    if result.get("benford"):
        out["Benford"] = [["First digit", "Expected %", "Actual %"], *[[d["digit"], d["expected"], d["actual"]] for d in result["benford"]["digits"]],
                          [], ["Mean absolute deviation", result["benford"]["mad"]], ["Verdict", result["benford"]["verdict"]]]
    if result.get("skipped"):
        out["Not checked"] = [["Why"], *[[s] for s in result["skipped"]]]
    return core.xlsx_bytes(out)
