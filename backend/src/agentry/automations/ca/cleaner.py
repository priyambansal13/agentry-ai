"""Excel cleaner (CA desk part 2, docs/PLAN-CA-DESK-2.md #1): the messy sheet a client sends, made clean, with a log of every
change. All by rules (no AI): exact, explainable and the same every time.

    header     the real header row (reports start with the firm's name and the period), two-row headers joined
    rows       blank rows, total / sub-total rows, opening / closing balance lines and repeated headers (page breaks) removed
    numbers    "1,23,456.00", "(1,200)", "-500", "₹5,000", "1,200 Dr", "800 Cr" -> numbers (Cr and brackets negative)
    debit/cr   a Debit and a Credit column become one signed "Amount (Dr +, Cr −)" column (the originals stay)
    dates      one format (YYYY-MM-DD); day-first unless the column itself shows month-first; Excel serial numbers too;
               dates that could be read either way are listed
    codes      GSTIN and PAN upper-cased and checked (GSTIN check digit); invalid ones listed
    phones     Indian mobiles as +91XXXXXXXXXX
    text       spaces trimmed and collapsed
    duplicates exact duplicate rows removed (the first kept)
    names      party names that are the same business written differently ("Sharma Traders Pvt Ltd", "SHARMA TRADERS") grouped;
               standardised to the most used spelling only when asked
"""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher

from agentry.automations.ca import core

MAX_ROWS = 20000
TOTAL = re.compile(r"^\s*(grand\s+total|sub[\s-]?total|total\b|closing\s+balance|opening\s+balance|balance\s+c/?f|balance\s+b/?f|c/f|b/f|"
                   r"carried\s+(forward|over)|brought\s+(forward|over))", re.IGNORECASE)
DRCR = re.compile(r"^\s*(?:₹|rs\.?|inr)?\s*(\(?-?[\d,]*\.?\d+\)?)\s*(dr|cr)?\.?\s*$", re.IGNORECASE)
GSTIN_RX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RX = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
SUFFIX = re.compile(r"\b(m/s|messrs|pvt|private|ltd|limited|llp|and co|& co|co|company|corp|corporation|inc|the)\b\.?", re.IGNORECASE)
NAME_HEAD = re.compile(r"party|name|customer|supplier|vendor|particulars|ledger|debtor|creditor|client|buyer|seller", re.IGNORECASE)


def _num(v: str) -> float | None:
    s = v.strip()
    if not s:
        return None
    m = DRCR.match(s.replace(" ", "") if re.search(r"\d\s*(dr|cr)", s, re.IGNORECASE) else s)
    if not m:
        return None
    raw, side = m.group(1), (m.group(2) or "").lower()
    n = core.money(raw)
    if n is None:
        return None
    return -abs(n) if side == "cr" else (abs(n) if side == "dr" else n)


def _date(v: str, month_first: bool) -> date | None:
    s = v.strip()
    if re.fullmatch(r"\d{5}(\.0+)?", s):  # an Excel serial date
        n = int(float(s))
        return date(1899, 12, 30) + timedelta(days=n) if 20000 < n < 80000 else None
    if month_first and (m := re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", s)):
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        try:
            return date(y, int(m[1]), int(m[2]))
        except ValueError:
            return None
    return core.parse_date(s)


def _ambiguous(v: str) -> bool:
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", v.strip())
    return bool(m) and int(m[1]) <= 12 and int(m[2]) <= 12 and m[1] != m[2]


def _key(name: str) -> str:
    s = SUFFIX.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def find_header(rows: list[list[str]]) -> tuple[int, list[str]]:
    """(index of the last header row, header names). The header is the first row, within 30, that is mostly text and has
    at least two-thirds of the widest row's cells filled; a second text row straight after it (e.g. "Amount" / "Dr") is joined."""
    width = max((len(r) for r in rows[:60]), default=0)

    def texty(r: list[str]) -> bool:
        cells = [c for c in r if c.strip()]
        return len(cells) >= max(2, round(width * 0.66)) and sum(_num(c) is None and core.parse_date(c) is None for c in cells) >= len(cells) * 0.8
    for i, r in enumerate(rows[:30]):
        if texty(r):
            head = [c.strip() for c in r] + [""] * (width - len(r))
            nxt = rows[i + 1] if i + 1 < len(rows) else []
            if nxt and texty(nxt) and i + 2 < len(rows) and not texty(rows[i + 2]):
                head = [" ".join(x for x in (a, b.strip()) if x) for a, b in zip(head, [*nxt, *[""] * (width - len(nxt))], strict=False)]
                i += 1
            return i, head
    return 0, [c.strip() for c in rows[0]] + [""] * (width - len(rows[0])) if rows else []


def _names(head: list[str]) -> list[str]:
    out, seen = [], Counter()
    for i, h in enumerate(head):
        h = re.sub(r"\s+", " ", h).strip() or f"Column {i + 1}"
        seen[h] += 1
        out.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return out


def _kind(name: str, values: list[str]) -> str:
    vals = [v for v in values if v.strip()]
    n = name.lower()
    if not vals:
        return "text"
    share = lambda f: sum(1 for v in vals if f(v)) / len(vals)
    if "gstin" in n or "gst no" in n or share(lambda v: bool(GSTIN_RX.match(v.strip().upper()))) >= 0.6:
        return "gstin"
    if re.search(r"\bpan\b", n) or share(lambda v: bool(PAN_RX.match(v.strip().upper()))) >= 0.6:
        return "pan"
    if re.search(r"phone|mobile|whatsapp|contact no|cell", n):
        return "phone"
    if re.search(r"date|dt\b|dated", n) or share(lambda v: _date(v, False) is not None and not re.fullmatch(r"\d+(\.\d+)?", v.strip())) >= 0.7:
        return "date"
    if share(lambda v: _num(v) is not None) >= 0.7 and not re.search(r"\bno\b|number|invoice|voucher|bill|code|hsn|sac|pin|account", n):
        return "number"
    return "text"


def clean(rows: list[list[str]], *, standardise_names: bool = False, drop_duplicates: bool = True) -> dict:
    rows = [[str(c) if c is not None else "" for c in r] for r in rows]
    if len(rows) > MAX_ROWS + 50:
        raise core.CaError(f"up to {MAX_ROWS:,} rows at a time: split the file")
    if not rows:
        raise core.CaError("the file is empty")
    hi, head = find_header(rows)
    cols = _names(head)
    width = len(cols)
    changes: dict[str, dict] = defaultdict(lambda: {"count": 0, "examples": []})
    issues: list[dict] = []

    def note(what: str, example: str | None = None) -> None:
        c = changes[what]
        c["count"] += 1
        if example and len(c["examples"]) < 4:
            c["examples"].append(example[:120])
    if hi:
        note("Lines above the header removed", " | ".join(" ".join(r).strip() for r in rows[:hi])[:120])
    head_key = [h.lower() for h in head]
    body: list[tuple[int, list[str]]] = []
    for n, r in enumerate(rows[hi + 1:], start=hi + 2):
        r = [*r[:width], *[""] * (width - len(r))]
        r = [re.sub(r"\s+", " ", c.replace(" ", " ")).strip() for c in r]
        if not any(r):
            note("Blank rows removed")
            continue
        if [c.lower() for c in r] == head_key:
            note("Repeated header rows removed (page breaks)", f"row {n}")
            continue
        first = next((c for c in r if c), "")
        if TOTAL.match(first) or (sum(1 for c in r if c) <= 2 and TOTAL.match(" ".join(r))):
            note("Total, sub-total and balance lines removed", f"row {n}: {' '.join(c for c in r if c)}")
            continue
        body.append((n, r))

    kinds = [_kind(cols[j], [r[j] for _, r in body]) for j in range(width)]
    # month-first only when the column proves it (a second part above 12), else day-first as in India
    month_first = [kinds[j] == "date" and any(re.match(r"^\d{1,2}[/\-.](1[3-9]|2\d|3[01])[/\-.]", r[j]) for _, r in body) for j in range(width)]
    day_first = [kinds[j] == "date" and any(re.match(r"^(1[3-9]|2\d|3[01])[/\-.]\d{1,2}[/\-.]", r[j]) for _, r in body) for j in range(width)]
    for j in range(width):  # nothing in the column says which way round: one note, not one per row
        if kinds[j] == "date" and not month_first[j] and not day_first[j] and any(_ambiguous(r[j]) for _, r in body):
            issues.append({"row": None, "column": cols[j], "value": "", "problem": "no date in this column has a day above 12: read as day first "
                           "(as in India); check if the file is month first"})
    out_rows: list[tuple[int, list]] = []
    for n, r in body:
        o: list = []
        for j, v in enumerate(r):
            k = kinds[j]
            if not v:
                o.append(None)
            elif k == "number":
                x = _num(v)
                if x is None:
                    issues.append({"row": n, "column": cols[j], "value": v, "problem": "not a number"})
                    o.append(v)
                else:
                    if str(x) != v and v not in (f"{x:g}", f"{x:.2f}"):
                        note(f"Numbers stored as text made numbers ({cols[j]})", f"{v} → {x:g}")
                    o.append(x)
            elif k == "date":
                d = _date(v, month_first[j])
                if d is None:
                    issues.append({"row": n, "column": cols[j], "value": v, "problem": "not a date"})
                    o.append(v)
                else:
                    if d.isoformat() != v:
                        note(f"Dates put in one format ({cols[j]})", f"{v} → {d.isoformat()}")
                    o.append(d.isoformat())
            elif k in ("gstin", "pan"):
                u = re.sub(r"\s", "", v).upper()
                if u != v:
                    note(f"{k.upper()}s upper-cased ({cols[j]})", f"{v} → {u}")
                from agentry.documents import gstin_ok
                if (k == "gstin" and not gstin_ok(u)) or (k == "pan" and not PAN_RX.match(u)):
                    issues.append({"row": n, "column": cols[j], "value": u, "problem": f"not a valid {k.upper()}" + (" (check digit)" if k == "gstin" and GSTIN_RX.match(u) else "")})
                o.append(u)
            elif k == "phone":
                from agentry.leads import normalize_phone
                p = normalize_phone(v)
                if p and p != v:
                    note(f"Phone numbers tidied ({cols[j]})", f"{v} → {p}")
                o.append(p or v)
            else:
                o.append(v)
        out_rows.append((n, o))

    # Debit / Credit columns -> one signed amount
    dr = next((j for j, c in enumerate(cols) if kinds[j] == "number" and re.search(r"\bdebit\b|\bdr\b|withdrawal", c, re.IGNORECASE)), None)
    cr = next((j for j, c in enumerate(cols) if kinds[j] == "number" and re.search(r"\bcredit\b|\bcr\b|deposit", c, re.IGNORECASE)), None)
    if dr is not None and cr is not None and dr != cr:
        cols.append("Amount (Dr +, Cr −)")
        kinds.append("number")
        for _, o in out_rows:
            d, c = o[dr] if isinstance(o[dr], float) else 0.0, o[cr] if isinstance(o[cr], float) else 0.0
            o.append(round(abs(d) - abs(c), 2))
        note("A signed Amount column added from Debit and Credit", f"{cols[dr]} − {cols[cr]}")

    # exact duplicates
    seen: set[tuple] = set()
    unique: list[tuple[int, list]] = []
    for n, o in out_rows:
        key = tuple(o)
        if key in seen and drop_duplicates:
            note("Exact duplicate rows removed (the first kept)", f"row {n}")
            continue
        seen.add(key)
        unique.append((n, o))

    # party names written differently
    groups: list[dict] = []
    name_col = next((j for j, c in enumerate(cols) if kinds[j] == "text" and NAME_HEAD.search(c)), None)
    if name_col is not None:
        counts = Counter(o[name_col] for _, o in unique if o[name_col])
        by_key: dict[str, list[str]] = defaultdict(list)
        for name in counts:
            k = _key(name)
            match = next((kk for kk in by_key if kk == k or (len(k) > 5 and SequenceMatcher(None, kk, k).ratio() >= 0.92)), None)
            by_key[match or k].append(name)
        for names in by_key.values():
            if len(names) > 1:
                best = max(names, key=lambda x: (counts[x], len(x)))
                groups.append({"use": best, "variants": sorted(n for n in names if n != best), "rows": sum(counts[n] for n in names)})
        if standardise_names and groups:
            fix = {v: g["use"] for g in groups for v in g["variants"]}
            for _, o in unique:
                if o[name_col] in fix:
                    note(f"Party names standardised ({cols[name_col]})", f"{o[name_col]} → {fix[o[name_col]]}")
                    o[name_col] = fix[o[name_col]]

    return {"columns": cols, "kinds": kinds, "rows": [o for _, o in unique], "source_rows": [n for n, _ in unique],
            "changes": [{"what": k, **v} for k, v in changes.items()], "issues": issues[:500], "issue_count": len(issues),
            "name_groups": groups[:200], "name_column": cols[name_col] if name_col is not None else None,
            "summary": {"rows_in": len(rows) - hi - 1, "rows_out": len(unique), "columns": len(cols), "header_row": hi + 1,
                        "dates": sum(1 for k in kinds if k == "date"), "numbers": sum(1 for k in kinds if k == "number")}}


def compute(data: bytes, mime: str, standardise_names: bool = False) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("the cleaner works on CSV or Excel (.xlsx) files; turn a PDF into Excel first with PDF to Excel")
    return clean(core.table_rows(data, mime), standardise_names=standardise_names)


def sheet(result: dict) -> bytes:
    return core.xlsx_bytes({
        "Cleaned": [result["columns"], *result["rows"]],
        "Changes": [["What was done", "How many", "Examples"], *[[c["what"], c["count"], " · ".join(c["examples"])] for c in result["changes"]]],
        "To check": [["Row (original)", "Column", "Value", "Problem"], *[[i["row"] or "whole column", i["column"], i["value"], i["problem"]] for i in result["issues"]]],
        "Similar names": [["Use", "Also written as", "Rows"], *[[g["use"], " · ".join(g["variants"]), g["rows"]] for g in result["name_groups"]]],
    })
