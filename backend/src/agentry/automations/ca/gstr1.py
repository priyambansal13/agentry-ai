"""GSTR-1 preparation (CA desk part 2, docs/PLAN-CA-DESK-2.md #4): a client's sales register for a month -> the GSTR-1
tables, checked, in the layout of the GST offline tool's Excel workbook. All by rules (no AI).

    read        the register through the Excel cleaner (header, totals, amounts, dates); columns found by name: date,
                invoice no, voucher type, customer, GSTIN, place of supply, HSN, description, quantity, UQC, taxable value,
                rate, IGST / CGST / SGST / cess, invoice value, port code, shipping bill no / date
    classify    credit / debit notes (voucher type, or a CN / DN number) -> CDNR (registered) or CDNUR (unregistered
                inter-state above the B2CL limit; otherwise they reduce B2CS) · exports (place of supply 96 / other country, or
                a port code / shipping bill) -> EXP, WPAY when IGST is charged · a valid GSTIN -> B2B · unregistered
                inter-state invoice above the B2CL limit (official figure gst.b2cl_limit) -> B2CL · the rest -> B2CS,
                summed by place of supply and rate
    rate        the Rate column, else the tax worked out from the taxable value; one row per invoice per rate
    hsn         summary by HSN and rate, split B2B / B2C (Table 12 from April 2025); UQC as given, OTH when blank
    docs        Table 13: invoice and note series (first, last, count, cancelled = numbers missing from a series)
    checks      GSTIN (format, check digit, not the client's own) · tax type against place of supply (the client's state
                from their GSTIN) · CGST = SGST · rate is a GST rate (12% / 28% flagged from 22 Sep 2025) · invoice value = taxable + tax · invoice numbers
                repeated or over 16 characters / not allowed characters · dates outside the month · HSN under 4 digits (6
                needed above ₹5 crore turnover) · exports without a port or shipping bill
Rows with a serious problem are still placed (as the register says) and listed: the CA decides, the tool doesn't drop data.
"""
import re
from collections import Counter, defaultdict
from datetime import date
from itertools import pairwise

from agentry import official_rules as rules
from agentry.automations.ca import cleaner, core
from agentry.automations.ca.anomalies import GST_RATES, _state

STATE = {"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
         "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland",
         "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand",
         "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
         "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
         "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "96": "Other Countries", "97": "Other Territory"}
INV_NO = re.compile(r"^[A-Za-z0-9/\-]{1,16}$")
NEW_SLABS = date(2025, 9, 22)  # GST rates rationalised to 5% / 18% / 40%: the 12% and 28% slabs went (28% stays for tobacco until cess ends)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def pos_label(code: str | None) -> str:
    return f"{code}-{STATE.get(code, '')}" if code else ""


def _col(cols: list[str], pattern: str, avoid: str | None = None) -> int | None:
    return next((j for j, c in enumerate(cols) if re.search(pattern, c, re.IGNORECASE) and not (avoid and re.search(avoid, c, re.IGNORECASE))), None)


def columns(cols: list[str], kinds: list[str]) -> dict[str, int | None]:
    return {
        "date": next((j for j, k in enumerate(kinds) if k == "date" and not re.search(r"shipping|bill date|sb date|due", cols[j], re.IGNORECASE)), None),
        "number": _col(cols, r"invoice\s*(no|num|#)|inv\s*no|bill\s*no|voucher\s*no|doc(ument)?\s*no|note\s*no|^no\.?$|number", r"gstin|shipping|hsn|phone"),
        "type": _col(cols, r"voucher\s*type|doc(ument)?\s*type|\btype\b"),
        "customer": _col(cols, r"customer|buyer|party|recipient|receiver|name|particulars", r"gstin"),
        "gstin": next((j for j, k in enumerate(kinds) if k == "gstin"), None) or _col(cols, r"gstin|gst\s*no"),
        "pos": _col(cols, r"place of supply|\bpos\b|state"),
        "hsn": _col(cols, r"hsn|sac"), "desc": _col(cols, r"description|item|product|goods"),
        "qty": _col(cols, r"\bqty\b|quantity"), "uqc": _col(cols, r"\buqc\b|\bunit\b|\buom\b"),
        "taxable": _col(cols, r"taxable|assessable"), "rate": _col(cols, r"\brate\b|gst\s*%|tax\s*%", r"amount"),
        "igst": _col(cols, r"\bigst\b|integrated"), "cgst": _col(cols, r"\bcgst\b|central tax"),
        "sgst": _col(cols, r"\bsgst\b|\butgst\b|state tax|state/ut"), "cess": _col(cols, r"\bcess\b"),
        "value": _col(cols, r"invoice value|bill value|total|gross|^amount|net amount|^value"),
        "port": _col(cols, r"port"), "sb_no": _col(cols, r"shipping bill\s*(no|num)|\bsb\s*no"),
        "sb_date": _col(cols, r"shipping bill\s*date|\bsb\s*date"),
    }


def _f(v: object) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return (cleaner._num(v) or 0.0) if isinstance(v, str) and v.strip() else 0.0


def _period(text_: str | None) -> tuple[int, int] | None:
    m = re.search(r"([a-z]{3})[a-z]*[\s\-']*(\d{2,4})", (text_ or "").lower())
    if m and m[1] in MONTHS:
        y = int(m[2])
        return (2000 + y if y < 100 else y), MONTHS[m[1]]
    m = re.search(r"(\d{1,2})[/\-](\d{4})", text_ or "")
    return (int(m[2]), int(m[1])) if m and 1 <= int(m[1]) <= 12 else None


def _dmy(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d-%b-%Y") if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else (iso or "")


def prepare(rows: list[list[str]], *, client_gstin: str | None, period: str | None = None) -> dict:
    from agentry.documents import gstin_ok
    c = cleaner.clean(rows, drop_duplicates=False)
    cols, kinds, data, src = c["columns"], c["kinds"], c["rows"], c["source_rows"]
    k = columns(cols, kinds)
    for need, label in (("number", "an invoice number"), ("taxable", "a taxable value")):
        if k[need] is None:
            raise core.CaError(f"no column for {label} found: name it e.g. \"Invoice No\" / \"Taxable Value\"")

    def val(r: list, key: str) -> object:
        return r[k[key]] if k[key] is not None else None

    def s(r: list, key: str) -> str:
        v = val(r, key)
        return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)).strip()

    home = (client_gstin or "")[:2] or None
    if not home:
        cnt = Counter(_state(s(r, "pos")) or _state(s(r, "gstin")) for r in data if _f(val(r, "cgst")) > 0)
        cnt.pop(None, None)
        home = cnt.most_common(1)[0][0] if cnt else None
    dates = [s(r, "date") for r in data]
    ym = _period(period) or (Counter(d[:7] for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)).most_common(1) or [(None, 0)])[0][0]
    if isinstance(ym, str):
        ym = (int(ym[:4]), int(ym[5:7]))
    limit = rules.num("gst.b2cl_limit")
    issues: list[dict] = []

    def issue(i: int | None, sev: str, what: str, value: str = "") -> None:
        issues.append({"row": src[i] if i is not None else None, "severity": sev, "problem": what, "value": value,
                       "invoice": s(data[i], "number") if i is not None else ""})

    # ---- one record per register row ----
    recs = []
    seen_no: dict[str, int] = {}
    for i, r in enumerate(data):
        no, typ = s(r, "number"), s(r, "type").lower()
        taxable, ig, cg, sg, cess = (_f(val(r, x)) for x in ("taxable", "igst", "cgst", "sgst", "cess"))
        tax = ig + cg + sg
        rate = _f(val(r, "rate")) if k["rate"] is not None and val(r, "rate") not in (None, "") else (round(tax / taxable * 100, 2) if taxable else 0.0)
        if 0 < rate < 1 and k["rate"] is not None and abs(rate * taxable - tax) < 2:
            rate *= 100  # 0.18 written for 18%
        value = _f(val(r, "value")) or round(taxable + tax + cess, 2)
        gstin = s(r, "gstin").upper().replace(" ", "")
        pos = _state(s(r, "pos")) or (_state(gstin) if gstin else None) or home
        note = "credit" if re.search(r"credit|\bcn\b|sales return", typ) or re.match(r"^cn\b|^cn[/\-]", no, re.IGNORECASE) else \
               "debit" if re.search(r"debit|\bdn\b", typ) or re.match(r"^dn[/\-]", no, re.IGNORECASE) else None
        export = pos == "96" or bool(re.search(r"export|other countr|outside india", s(r, "pos").lower() + " " + typ)) or bool(s(r, "port") or s(r, "sb_no"))
        if export:
            pos = "96"
        registered = bool(gstin) and gstin_ok(gstin)
        inter = pos is not None and home is not None and pos != home
        rec = {"i": i, "no": no, "date": s(r, "date"), "customer": s(r, "customer"), "gstin": gstin, "pos": pos, "taxable": taxable,
               "igst": ig, "cgst": cg, "sgst": sg, "cess": cess, "value": value, "rate": rate, "note": note, "export": export,
               "hsn": re.sub(r"\D", "", s(r, "hsn")), "desc": s(r, "desc"), "qty": _f(val(r, "qty")), "uqc": (s(r, "uqc") or "OTH").upper()[:3],
               "port": s(r, "port"), "sb_no": s(r, "sb_no"), "sb_date": s(r, "sb_date"), "registered": registered}
        # checks
        if not no:
            issue(i, "high", "no invoice number")
        elif not INV_NO.match(no):
            issue(i, "high", "invoice number over 16 characters or with characters the portal refuses (only letters, digits, / and -)", no)
        if no and (note or "inv", no.upper()) in seen_no:
            issue(i, "high", f"invoice number used twice (also row {src[seen_no[(note or 'inv', no.upper())]]})", no)
        seen_no.setdefault((note or "inv", no.upper()), i)
        if gstin and not gstin_ok(gstin):
            issue(i, "high", "GSTIN not valid: treated as unregistered (B2C) until corrected", gstin)
        if gstin and client_gstin and gstin == client_gstin.upper():
            issue(i, "high", "the client's own GSTIN as the customer", gstin)
        if not export and home and pos:
            if inter and (cg or sg):
                issue(i, "high", f"supply to another state ({pos_label(pos)}) but CGST + SGST charged: should be IGST")
            if not inter and ig:
                issue(i, "high", f"supply within the state ({pos_label(pos)}) but IGST charged: should be CGST + SGST")
        if abs(cg - sg) > 1:
            issue(i, "high", f"CGST {core.inr(cg)} and SGST {core.inr(sg)} differ")
        if taxable and tax and min(abs(rate - g) for g in GST_RATES) > 0.6:
            issue(i, "medium", f"rate {rate:g}% isn't a GST rate")
        elif rate in (12, 28) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s(r, "date")) and date.fromisoformat(s(r, "date")) >= NEW_SLABS:
            issue(i, "medium", f"{rate:g}%: the 12% and 28% slabs were removed from 22 Sep 2025 (28% only for tobacco products): check the rate")
        if taxable and val(r, "value") is not None and abs(value - (taxable + tax + cess)) > 1:
            issue(i, "medium", f"invoice value {core.inr(value)} isn't taxable + tax ({core.inr(taxable + tax + cess)})")
        if rec["date"] and ym and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["date"]) and (int(rec["date"][:4]), int(rec["date"][5:7])) != ym:
            issue(i, "high", f"dated {_dmy(rec['date'])}, outside {date(ym[0], ym[1], 1):%b %Y}: belongs in another month's return (or an amendment)")
        if k["hsn"] is not None and (len(rec["hsn"]) < 4):
            issue(i, "medium", "HSN missing or under 4 digits (6 digits needed above ₹5 crore turnover)", s(r, "hsn"))
        if export and not (rec["port"] and rec["sb_no"]):
            issue(i, "low", "export without a port code / shipping bill: add them when available (can be amended)")
        recs.append(rec)

    # ---- tables ----
    b2cl_buyers = {x["customer"].lower() for x in recs if not x["note"] and not x["registered"] and not x["export"] and x["pos"] != home
                   and x["value"] > limit and x["customer"]}
    b2b, b2cl, b2cs, cdnr, cdnur, exp = [], [], defaultdict(lambda: [0.0, 0.0]), [], [], []
    table_of: dict[int, str] = {}
    for x in recs:
        pos_l = pos_label(x["pos"])
        if x["note"]:
            nt = "C" if x["note"] == "credit" else "D"
            if x["registered"]:
                cdnr.append([x["gstin"], x["customer"], x["no"], _dmy(x["date"]), nt, pos_l, "N", "Regular B2B", x["value"], "", x["rate"], x["taxable"], x["cess"]])
                table_of[x["i"]] = "cdnr"
            elif x["export"] or (x["pos"] != home and (x["value"] > limit or x["customer"].lower() in b2cl_buyers)):
                # a note against a B2CL invoice goes to CDNUR whatever its own value
                ur = ("EXPWP" if x["igst"] else "EXPWOP") if x["export"] else "B2CL"
                cdnur.append([ur, x["no"], _dmy(x["date"]), nt, pos_l, x["value"], "", x["rate"], x["taxable"], x["cess"]])
                table_of[x["i"]] = "cdnur"
            else:  # a note to a small unregistered buyer reduces (or adds to) B2CS
                sign = -1 if nt == "C" else 1
                b = b2cs[(pos_l, x["rate"])]
                b[0] += sign * x["taxable"]
                b[1] += sign * x["cess"]
                table_of[x["i"]] = "b2cs"
        elif x["export"]:
            exp.append(["WPAY" if x["igst"] else "WOPAY", x["no"], _dmy(x["date"]), x["value"], x["port"], x["sb_no"], _dmy(x["sb_date"]) if x["sb_date"] else "",
                        x["rate"], x["taxable"], x["cess"]])
            table_of[x["i"]] = "exp"
        elif x["registered"]:
            b2b.append([x["gstin"], x["customer"], x["no"], _dmy(x["date"]), x["value"], pos_l, "N", "", "Regular B2B", "", x["rate"], x["taxable"], x["cess"]])
            table_of[x["i"]] = "b2b"
        elif x["pos"] != home and x["value"] > limit:
            b2cl.append([x["no"], _dmy(x["date"]), x["value"], pos_l, "", x["rate"], x["taxable"], x["cess"], ""])
            table_of[x["i"]] = "b2cl"
        else:
            b = b2cs[(pos_l, x["rate"])]
            b[0] += x["taxable"]
            b[1] += x["cess"]
            table_of[x["i"]] = "b2cs"
    b2cs_rows = [["OE", p, "", r, round(t, 2), round(cs, 2), ""] for (p, r), (t, cs) in sorted(b2cs.items())]

    # ---- HSN summary, B2B and B2C (notes reduce / add) ----
    hsn: dict[str, dict[tuple, list[float]]] = {"b2b": defaultdict(lambda: [0.0] * 7), "b2c": defaultdict(lambda: [0.0] * 7)}
    desc: dict[str, str] = {}
    for x in recs:
        part = "b2b" if x["registered"] and not x["export"] else "b2c"
        sign = -1 if x["note"] == "credit" else 1
        key = (x["hsn"] or "", x["uqc"], x["rate"])
        h = hsn[part][key]
        for n, v in enumerate((x["qty"], x["value"], x["taxable"], x["igst"], x["cgst"], x["sgst"], x["cess"])):
            h[n] += sign * v
        desc.setdefault(x["hsn"], x["desc"])
    hsn_rows = {p: [[h, desc.get(h, ""), u, round(v[0], 3), round(v[1], 2), r, round(v[2], 2), round(v[3], 2), round(v[4], 2), round(v[5], 2), round(v[6], 2)]
                    for (h, u, r), v in sorted(hsn[p].items())] for p in hsn}

    # ---- Table 13: documents issued ----
    docs = []
    for nature, pick in (("Invoices for outward supply", lambda x: not x["note"]), ("Credit Note", lambda x: x["note"] == "credit"),
                         ("Debit Note", lambda x: x["note"] == "debit")):
        series: dict[str, list[int]] = defaultdict(list)
        raw: dict[str, list[str]] = defaultdict(list)
        for x in recs:
            if pick(x) and x["no"]:
                m = re.match(r"^(.*?)(\d+)$", x["no"])
                pre, n = (m[1], int(m[2])) if m else (x["no"], 0)
                series[pre].append(n)
                raw[pre].append(x["no"])
        for pre, ns in series.items():
            uniq = sorted(set(ns))
            first, last = min(raw[pre], key=lambda v: (len(v), v)), max(raw[pre], key=lambda v: (len(v), v))
            cancelled = (uniq[-1] - uniq[0] + 1 - len(uniq)) if uniq[0] else 0
            docs.append([nature, first, last, len(uniq) + cancelled, cancelled])
            if cancelled:
                gaps = [f"{pre}{n}" for a, b in pairwise(uniq) for n in range(a + 1, b)]
                issues.append({"row": None, "severity": "low", "problem": f"{cancelled} number(s) missing from the {nature.lower()} series: counted as "
                               "cancelled in Table 13; check none is an unrecorded sale", "value": ", ".join(gaps[:10]), "invoice": ""})

    # ---- totals ----
    def tot(pick) -> dict:
        xs = [x for x in recs if pick(x)]
        sg = lambda x: -1 if x["note"] == "credit" else 1
        return {"count": len(xs), **{f: round(sum(sg(x) * x[f] for x in xs), 2) for f in ("taxable", "igst", "cgst", "sgst", "cess")}}
    totals = {t: tot(lambda x, t=t: table_of.get(x["i"]) == t) for t in ("b2b", "b2cl", "b2cs", "exp", "cdnr", "cdnur")}
    totals["all"] = tot(lambda x: True)
    sev = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: (sev[x["severity"]], x["row"] or 0))
    return {"period": f"{date(ym[0], ym[1], 1):%b %Y}" if ym else None, "client_state": pos_label(home), "b2cl_limit": limit,
            "columns": {key: cols[j] if j is not None else None for key, j in k.items()},
            "tables": {"b2b": b2b, "b2cl": b2cl, "b2cs": b2cs_rows, "cdnr": cdnr, "cdnur": cdnur, "exp": exp,
                       "hsn_b2b": hsn_rows["b2b"], "hsn_b2c": hsn_rows["b2c"], "docs": docs},
            "totals": totals, "issues": issues[:500], "issue_count": len(issues),
            "summary": {"rows": len(recs), "high": sum(1 for x in issues if x["severity"] == "high"),
                        "medium": sum(1 for x in issues if x["severity"] == "medium"), "low": sum(1 for x in issues if x["severity"] == "low")}}


def compute(data: bytes, mime: str, **kw) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("GSTR-1 preparation works on a sales register in CSV or Excel (.xlsx)")
    return prepare(core.table_rows(data, mime), **kw)


HEADS = {  # the offline tool's Excel workbook: sheet -> (summary title, column headings)
    "b2b": ("Summary For B2B, SEZ, DE (4A, 4B, 6B, 6C)", ["GSTIN/UIN of Recipient", "Receiver Name", "Invoice Number", "Invoice date", "Invoice Value",
            "Place Of Supply", "Reverse Charge", "Applicable % of Tax Rate", "Invoice Type", "E-Commerce GSTIN", "Rate", "Taxable Value", "Cess Amount"]),
    "b2cl": ("Summary For B2CL(5)", ["Invoice Number", "Invoice date", "Invoice Value", "Place Of Supply", "Applicable % of Tax Rate", "Rate",
             "Taxable Value", "Cess Amount", "E-Commerce GSTIN"]),
    "b2cs": ("Summary For B2CS(7)", ["Type", "Place Of Supply", "Applicable % of Tax Rate", "Rate", "Taxable Value", "Cess Amount", "E-Commerce GSTIN"]),
    "cdnr": ("Summary For CDNR(9B)", ["GSTIN/UIN of Recipient", "Receiver Name", "Note Number", "Note Date", "Note Type", "Place Of Supply", "Reverse Charge",
             "Note Supply Type", "Note Value", "Applicable % of Tax Rate", "Rate", "Taxable Value", "Cess Amount"]),
    "cdnur": ("Summary For CDNUR(9B)", ["UR Type", "Note Number", "Note Date", "Note Type", "Place Of Supply", "Note Value", "Applicable % of Tax Rate",
              "Rate", "Taxable Value", "Cess Amount"]),
    "exp": ("Summary For EXP(6)", ["Export Type", "Invoice Number", "Invoice date", "Invoice Value", "Port Code", "Shipping Bill Number",
            "Shipping Bill Date", "Rate", "Taxable Value", "Cess Amount"]),
    "hsn(b2b)": ("Summary For HSN(12) B2B", ["HSN", "Description", "UQC", "Total Quantity", "Total Value", "Rate", "Taxable Value", "Integrated Tax Amount",
                 "Central Tax Amount", "State/UT Tax Amount", "Cess Amount"]),
    "hsn(b2c)": ("Summary For HSN(12) B2C", ["HSN", "Description", "UQC", "Total Quantity", "Total Value", "Rate", "Taxable Value", "Integrated Tax Amount",
                 "Central Tax Amount", "State/UT Tax Amount", "Cess Amount"]),
    "docs": ("Summary of documents issued during the tax period (13)", ["Nature of Document", "Sr. No. From", "Sr. No. To", "Total Number", "Cancelled"]),
}
KEY = {"hsn(b2b)": "hsn_b2b", "hsn(b2c)": "hsn_b2c"}


def sheet(result: dict) -> bytes:
    """Each table as the offline tool's sheet: the summary title on row 1, headings on row 4, data from row 5."""
    t = result["tables"]
    out: dict[str, list[list]] = {}
    for name, (title, head) in HEADS.items():
        rows = t[KEY.get(name, name)]
        out[name] = [[title], [f"{len(rows)} rows"], [], head, *rows]
    out["checks"] = [["Severity", "Row", "Invoice", "Problem", "Value"], *[[i["severity"], i["row"], i["invoice"], i["problem"], i["value"]] for i in result["issues"]]]
    out["totals"] = [["Table", "Documents", "Taxable value", "IGST", "CGST", "SGST", "Cess"],
                     *[[k.upper(), v["count"], v["taxable"], v["igst"], v["cgst"], v["sgst"], v["cess"]] for k, v in result["totals"].items()]]
    return core.xlsx_bytes(out)
