"""Excel desk (CA Firm pack): PDF to Excel, reconcile two sheets, and questions answered from a sheet.

    to excel   a PDF or photo with a table (a statement, a ledger, an invoice list) -> rows and columns in Excel, in the
               firm's own column layout when given; a number that isn't in the source text is marked (photos can't be
               checked: they're marked for a glance)
    reconcile  two sheets (books vs bank, debtors vs confirmations, a client's list vs the portal's): matched on the key
               columns (found automatically or chosen), amounts compared within a tolerance -> matched, amounts differ,
               only in the first, only in the second
    ask        "total TDS for Kumar Logistics", "top 5 parties by amount", "how many invoices above 1 lakh": the model only
               turns the question into a filter / group / sum; the numbers are worked out by code over the sheet
"""
import base64
import json
import re
from collections import defaultdict

from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


class ExcelConfig(BaseModel):
    tolerance: float = Field(1, ge=0, le=1000, title="Treat amounts as equal within (₹)", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="excel_desk", name="Excel desk",
    description="Any PDF to Excel in your layout, reconciliations, and questions answered from your sheets.",
    config_model=ExcelConfig, metrics=(),
))


# ---------- PDF / photo to Excel ----------

def _split(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.strip().strip("|").split("|")]
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}", line.strip())]


def table_from_text(txt: str) -> dict:
    """Lines with the most common number of columns (>= 2) make the table; the first of them is the header."""
    lines = [_split(ln) for ln in txt.splitlines() if ln.strip()]
    counts: dict[int, int] = defaultdict(int)
    for ln in lines:
        if len(ln) >= 2:
            counts[len(ln)] += 1
    if not counts:
        return {"columns": [], "rows": []}
    width = max(counts, key=lambda k: (counts[k], k))
    rows = [ln for ln in lines if len(ln) == width]
    return {"columns": rows[0], "rows": rows[1:]}


def _numbers(s: str) -> list[str]:
    return [n.replace(",", "").lstrip("0") or "0" for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")]


def check_numbers(rows: list[list[str]], source: str | None) -> list[bool]:
    """Each row: every number in it appears in the source text (photos can't be checked)."""
    if source is None:
        return [False] * len(rows)
    have = set(_numbers(source))
    have |= {n[:-3] for n in have if n.endswith(".00")}
    return [all(n in have or n.removesuffix(".00") in have for c in r for n in _numbers(c)) for r in rows]


async def to_excel(org_id: str, data: bytes, mime: str, columns: list[str] | None = None) -> dict:
    txt = core.text_of(data, mime, 60000)
    if mime in ("text/csv",) or mime.endswith("spreadsheetml.sheet"):
        rows = core.table_rows(data, mime)
        return {"columns": rows[0] if rows else [], "rows": rows[1:], "checked": [True] * max(0, len(rows) - 1), "photo": False}
    guess = table_from_text(txt) if txt else {"columns": columns or [], "rows": []}
    prompt = load("ca_excel_table")
    messages = prompt.render(columns=", ".join(columns) if columns else "(use the table's own headings)",
                             text=f"The document's text:\n{txt}" if txt else "The document is attached as an image.")
    if not txt:
        if not mime.startswith("image/"):
            raise core.CaError("this PDF has no text: upload a clear photo or the original file")
        messages[-1] = {"role": "user", "content": [{"type": "text", "text": messages[-1]["content"]},
                                                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}]}
    try:
        res = await complete(prompt.tier, messages, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(guess), temperature=0)
        t = res.data if isinstance(res.data, dict) and res.data.get("rows") is not None else guess
    except AllModelsFailed:
        t = guess
    cols = [str(c) for c in t.get("columns") or []]
    rows = [[str(c) if c is not None else "" for c in r] for r in t.get("rows") or [] if isinstance(r, list)]
    return {"columns": cols, "rows": rows, "checked": check_numbers(rows, txt), "photo": txt is None}


# ---------- reconcile ----------

def _key_cols(a: list[str], b: list[str]) -> tuple[list[int], list[int]]:
    pref = ("invoice", "inv", "bill", "ref", "voucher", "document", "doc", "cheque", "utr", "gstin", "pan", "party", "name", "customer", "vendor")
    na = [re.sub(r"[^a-z]", "", x.lower()) for x in a]
    nb = [re.sub(r"[^a-z]", "", x.lower()) for x in b]
    for p in pref:
        ia = next((i for i, h in enumerate(na) if p in h), None)
        ib = next((i for i, h in enumerate(nb) if p in h), None)
        if ia is not None and ib is not None:
            return [ia], [ib]
    raise core.CaError("couldn't find a common key column (invoice / reference / party): choose the columns")


def _amount_col(h: list[str]) -> int | None:
    return core.find_col(h, "Amount", "Total", "Invoice value", "Balance", "Debit", "Credit", "Value", avoid=("date",))


def reconcile(a_rows: list[list[str]], b_rows: list[list[str]], tolerance: float = 1, keys: tuple[list[str], list[str]] | None = None,
              amounts: tuple[str | None, str | None] | None = None) -> dict:
    ha, hb = a_rows[0], b_rows[0]
    if keys:
        ka = [ha.index(k) for k in keys[0] if k in ha]
        kb = [hb.index(k) for k in keys[1] if k in hb]
        if not ka or len(ka) != len(kb):
            raise core.CaError("the key columns weren't found in both sheets")
    else:
        ka, kb = _key_cols(ha, hb)
    aa = ha.index(amounts[0]) if amounts and amounts[0] in ha else _amount_col(ha)
    ab = hb.index(amounts[1]) if amounts and amounts[1] in hb else _amount_col(hb)

    def key(r: list[str], cols: list[int]) -> str:
        return "|".join(re.sub(r"[^A-Z0-9]", "", re.sub(r"(?<![0-9])0+(?=[0-9])", "", (r[i] if i < len(r) else "").upper())) for i in cols)

    def amt(r: list[str], i: int | None) -> float | None:
        return core.money(r[i]) if i is not None and i < len(r) else None
    right: dict[str, list[list[str]]] = defaultdict(list)
    for r in b_rows[1:]:
        right[key(r, kb)].append(r)
    out = {"matched": [], "amount_differs": [], "only_first": [], "only_second": []}
    for r in a_rows[1:]:
        k = key(r, ka)
        if not k.strip("|"):
            continue
        if right.get(k):
            other = right[k].pop(0)
            x, y = amt(r, aa), amt(other, ab)
            if x is not None and y is not None and abs(abs(x) - abs(y)) > tolerance:
                out["amount_differs"].append({"key": k, "first": r, "second": other, "difference": round(abs(x) - abs(y), 2)})
            else:
                out["matched"].append({"key": k, "first": r, "second": other})
        else:
            out["only_first"].append({"key": k, "first": r})
    out["only_second"] = [{"key": k, "second": r} for k, rs in right.items() for r in rs if k.strip("|")]
    return {**out, "counts": {k: len(v) for k, v in out.items()}, "key_columns": [[ha[i] for i in ka], [hb[i] for i in kb]],
            "amount_columns": [ha[aa] if aa is not None else None, hb[ab] if ab is not None else None], "headers": [ha, hb]}


# ---------- ask ----------

OPS = {"=", "!=", ">", "<", ">=", "<=", "contains"}


def _num(v: object) -> float | None:
    """A number only when the cell looks like one ("194C" is a section, not 194)."""
    if isinstance(v, (int, float)):
        return float(v)
    return core.money(v) if re.fullmatch(r"\s*(rs\.?|₹)?\s*[-+(]?[\d,]*\.?\d+\)?\s*", str(v or ""), re.IGNORECASE) else None


def _match(cell: str, op: str, value: object) -> bool:
    if op == "contains":
        return str(value).lower() in cell.lower()
    x, y = _num(cell), _num(value)
    if x is not None and y is not None and op in (">", "<", ">=", "<="):
        return {">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}[op]
    eq = (x == y) if x is not None and y is not None else cell.strip().lower() == str(value).strip().lower()
    return eq if op == "=" else not eq


def run_query(rows: list[list[str]], spec: dict) -> dict:
    head, body = rows[0], rows[1:]
    idx = {h: i for i, h in enumerate(head)}

    def col(name: object) -> int | None:
        if name in idx:
            return idx[name]
        return core.find_col(head, str(name)) if name else None
    for f in spec.get("filter") or []:
        c = col(f.get("column"))
        if c is None or f.get("op") not in OPS:
            raise core.CaError(f"can't filter on {f.get('column')!r}")
        body = [r for r in body if c < len(r) and _match(r[c], f["op"], f.get("value"))]
    agg, mc, gc = spec.get("agg") or "count", col(spec.get("measure")), col(spec.get("group_by"))
    if agg not in ("sum", "count", "avg", "min", "max", "list"):
        raise core.CaError("unknown calculation")
    if agg not in ("count", "list") and mc is None:
        raise core.CaError(f"no column {spec.get('measure')!r} to {agg}")

    def calc(rs: list[list[str]]) -> float:
        if agg == "count":
            return len(rs)
        vals = [v for r in rs if mc < len(r) and (v := core.money(r[mc])) is not None]
        if not vals:
            return 0.0
        return round({"sum": sum(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[agg], 2)
    if agg == "list":
        return {"rows": [head, *body[:200]], "count": len(body)}
    if gc is None:
        return {"value": calc(body), "count": len(body)}
    groups: dict[str, list[list[str]]] = defaultdict(list)
    for r in body:
        groups[r[gc] if gc < len(r) else ""].append(r)
    res = sorted(([g, calc(rs)] for g, rs in groups.items()), key=lambda x: -x[1])
    top = spec.get("top")
    return {"groups": res[:int(top)] if isinstance(top, int) and top > 0 else res, "count": len(body)}


def guess_spec(question: str, head: list[str]) -> dict:
    q = question.lower()
    agg = "sum" if re.search(r"total|sum", q) else "avg" if "average" in q else "max" if re.search(r"highest|largest|max", q) else "count"
    measure = core.find_col(head, "Amount", "Total", "Value", "TDS") if agg != "count" else None
    return {"agg": agg, "measure": head[measure] if measure is not None else None, "filter": [], "group_by": None}


async def ask(org_id: str, rows: list[list[str]], question: str) -> dict:
    if len(rows) < 2:
        raise core.CaError("the sheet has no rows")
    head = rows[0]
    prompt = load("ca_excel_query")
    sample = "\n".join(" | ".join(r) for r in rows[:6])
    try:
        res = await complete(prompt.tier, prompt.render(columns=" | ".join(head), sample=sample, question=question), org_id=org_id,
                             prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(guess_spec(question, head)), temperature=0)
        spec = res.data if isinstance(res.data, dict) else guess_spec(question, head)
    except AllModelsFailed:
        spec = guess_spec(question, head)
    return {"spec": spec, "answer": run_query(rows, spec)}


def sheet_table(t: dict) -> bytes:
    rows = [t["columns"] + ["Numbers checked"]] + [r + ["yes" if ok else "check"] for r, ok in zip(t["rows"], t["checked"], strict=False)]
    return core.xlsx_bytes({"Table": rows})


def sheet_reco(r: dict) -> bytes:
    ha, hb = r["headers"]
    out = {"Summary": [["Result", "Rows"]] + [[k.replace("_", " "), v] for k, v in r["counts"].items()] +
           [[], ["Key columns", " + ".join(r["key_columns"][0]), " + ".join(r["key_columns"][1])], ["Amount columns", *r["amount_columns"]]]}
    out["Amounts differ"] = [["Key", "Difference", *[f"1: {h}" for h in ha], *[f"2: {h}" for h in hb]]] + \
        [[x["key"], x["difference"], *x["first"], *x["second"]] for x in r["amount_differs"]]
    out["Only in first"] = [ha] + [x["first"] for x in r["only_first"]]
    out["Only in second"] = [hb] + [x["second"] for x in r["only_second"]]
    out["Matched"] = [[*ha, *hb]] + [[*x["first"], *x["second"]] for x in r["matched"]]
    return core.xlsx_bytes(out)
