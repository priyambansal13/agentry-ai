"""GST reconciliation (CA Firm pack): GSTR-2B against the client's purchase register.

    read      GSTR-2B as the portal's JSON download, or its Excel / CSV; the purchase register as Excel / CSV (Tally's
              purchase register export works): supplier GSTIN, invoice number, date, taxable value, tax
    match     same supplier GSTIN and the same invoice number (ignoring case, spaces, slashes, leading zeros and a
              trailing year like /24-25); amounts within the tolerance count as matched
    result    matched · amount differs · in the books but not in 2B (the supplier hasn't filed: ITC at risk) · in 2B
              but not in the books (record it or check it) · the same invoice under another GSTIN (a typo somewhere)
    suppliers a message per supplier whose invoices are missing from 2B, ready to send
Numbers come from the files, never from a model.
"""
import json
import re
from collections import defaultdict

from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core

GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class GstConfig(BaseModel):
    tolerance: float = Field(10, ge=0, le=1000, title="Treat amounts as equal within (₹)", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_gst_reconciliation", name="GST reconciliation",
    description="GSTR-2B vs the purchase register, with messages to suppliers who haven't filed.",
    config_model=GstConfig, metrics=(),
))


def inv_norm(s: str) -> str:
    s = re.sub(r"[/\-](20)?\d{2}[/\-](20)?\d{2}$", "", str(s or "").strip().upper())  # a trailing financial year
    s = re.sub(r"(?<![0-9])0+(?=[0-9])", "", s)  # BST-0457 = BST-457
    return re.sub(r"[^A-Z0-9]", "", s)


def _rec(gstin: object, name: object, inv: object, dt: object, taxable: object, tax: float, total: object, row: int) -> dict:
    t = core.money(taxable) or 0.0
    return {"gstin": str(gstin or "").strip().upper(), "name": str(name or "").strip(), "invoice": str(inv or "").strip(),
            "key": inv_norm(str(inv or "")), "date": str(core.parse_date(dt) or dt or ""), "taxable": round(t, 2), "tax": round(tax, 2),
            "total": round(core.money(total) or t + tax, 2), "row": row}


def from_2b_json(data: dict) -> list[dict]:
    out: list[dict] = []

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("b2b"), list):
                for s in o["b2b"]:
                    for n, i in enumerate(s.get("inv") or []):
                        items = i.get("items") or [i]
                        tax = sum((core.money(x.get(k)) or 0) for x in items for k in ("igst", "cgst", "sgst", "cess"))
                        taxable = sum((core.money(x.get("txval")) or 0) for x in items)
                        out.append(_rec(s.get("ctin"), s.get("trdnm"), i.get("inum"), i.get("dt"), taxable, tax, i.get("val"), n + 1))
            for v in o.values():
                if v is not None and not isinstance(v, (str, int, float)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def from_table(rows: list[list[str]]) -> list[dict]:
    h = core.header_row(rows, ("gstin|gst no", "invoice|bill|inv"))
    head, body = rows[h], rows[h + 1:]
    col = {
        "gstin": core.find_col(head, "GSTIN of supplier", "Supplier GSTIN", "GSTIN/UIN", "GSTIN", "GST No", "Party GSTIN"),
        "name": core.find_col(head, "Trade/Legal name", "Trade name", "Legal name", "Supplier name", "Party name", "Particulars", "Name"),
        "inv": core.find_col(head, "Invoice number", "Invoice No", "Supplier invoice no", "Bill No", "Voucher Ref", "Inv No", "Document number",
                             avoid=("date", "value", "type")),
        "date": core.find_col(head, "Invoice date", "Bill date", "Date"),
        "taxable": core.find_col(head, "Taxable value", "Taxable amount", "Assessable value", "Taxable"),
        "igst": core.find_col(head, "Integrated tax", "IGST"), "cgst": core.find_col(head, "Central tax", "CGST"),
        "sgst": core.find_col(head, "State/UT tax", "SGST", "UTGST"), "tax": core.find_col(head, "Total tax", "Tax amount", "GST amount"),
        "total": core.find_col(head, "Invoice value", "Invoice amount", "Total", "Gross total", "Bill amount"),
    }
    if col["gstin"] is None or col["inv"] is None:
        raise core.CaError("couldn't find the GSTIN and invoice number columns")
    out = []
    for n, r in enumerate(body, start=h + 2):
        get = {k: (r[i] if i is not None and i < len(r) else "") for k, i in col.items()}
        if not str(get["gstin"]).strip() or not str(get["inv"]).strip():
            continue
        tax = core.money(get["tax"]) if col["tax"] is not None else sum(core.money(get[k]) or 0 for k in ("igst", "cgst", "sgst"))
        out.append(_rec(get["gstin"], get["name"], get["inv"], get["date"], get["taxable"], tax or 0.0, get["total"], n))
    return out


def records(data: bytes, mime: str) -> list[dict]:
    if mime == "application/json" or data[:1] in (b"{", b"["):
        try:
            return from_2b_json(json.loads(data.decode("utf-8-sig")))
        except ValueError as e:
            raise core.CaError("this JSON file can't be read") from e
    return from_table(core.table_rows(data, mime))


def reconcile(b2b: list[dict], books: list[dict], tolerance: float = 10) -> dict:
    by_key = {(r["gstin"], r["key"]): r for r in b2b}
    used, rows = set(), []
    for b in books:
        k = (b["gstin"], b["key"])
        g = by_key.get(k)
        if g:
            used.add(k)
            diff = round(b["tax"] - g["tax"], 2)
            ok = abs(diff) <= tolerance and abs(b["taxable"] - g["taxable"]) <= max(tolerance, 1)
            rows.append({"status": "matched" if ok else "amount_differs", "books": b, "gstr2b": g, "tax_difference": diff})
        else:
            rows.append({"status": "missing_in_2b", "books": b, "gstr2b": None, "tax_difference": b["tax"]})
    extra = [g for k, g in by_key.items() if k not in used]
    # the same invoice under another GSTIN: a typo in the books or the supplier's return
    for row in [r for r in rows if r["status"] == "missing_in_2b"]:
        b = row["books"]
        twin = next((g for g in extra if g["key"] == b["key"] and abs(g["tax"] - b["tax"]) <= tolerance), None)
        if twin:
            extra.remove(twin)
            row.update(status="gstin_differs", gstr2b=twin, tax_difference=round(b["tax"] - twin["tax"], 2))
    rows += [{"status": "missing_in_books", "books": None, "gstr2b": g, "tax_difference": -g["tax"]} for g in extra]
    totals: dict[str, dict] = defaultdict(lambda: {"count": 0, "tax": 0.0})
    for r in rows:
        totals[r["status"]]["count"] += 1
        totals[r["status"]]["tax"] = round(totals[r["status"]]["tax"] + (r["books"] or r["gstr2b"])["tax"], 2)
    bad = {"missing_in_2b", "amount_differs", "gstin_differs"}
    order = {"missing_in_2b": 0, "amount_differs": 1, "gstin_differs": 2, "missing_in_books": 3, "matched": 4}
    return {"rows": sorted(rows, key=lambda r: (order[r["status"]], (r["books"] or r["gstr2b"])["name"])), "totals": dict(totals),
            "itc_at_risk": round(sum(r["books"]["tax"] for r in rows if r["status"] in bad and r["books"]), 2),
            "itc_in_2b": round(sum(g["tax"] for g in b2b), 2), "itc_in_books": round(sum(b["tax"] for b in books), 2)}


def supplier_messages(result: dict, client: str, client_gstin: str | None, period: str) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in result["rows"]:
        if r["status"] in ("missing_in_2b", "amount_differs"):
            by[r["books"]["gstin"]].append(r)
    out = []
    for gstin, rs in by.items():
        name = rs[0]["books"]["name"] or gstin
        lines = "\n".join(f"• Invoice {r['books']['invoice']} dated {r['books']['date']}: ₹{r['books']['total']:,.2f}"
                          + (" (shows a different amount in GSTR-2B)" if r["status"] == "amount_differs" else "") for r in rs)
        out.append({"gstin": gstin, "supplier": name, "invoices": len(rs), "tax": round(sum(r["books"]["tax"] for r in rs), 2),
                    "message": f"Dear {name},\n\nThe following invoices you issued to {client}{f' (GSTIN {client_gstin})' if client_gstin else ''} "
                               f"are not showing correctly in our GSTR-2B for {period}:\n{lines}\n\nPlease file or correct them in your GSTR-1 so the "
                               "input tax credit can be claimed. Thank you."})
    return sorted(out, key=lambda m: -m["tax"])


LABEL = {"matched": "Matched", "amount_differs": "Amount differs", "missing_in_2b": "Not in GSTR-2B (supplier hasn't filed)",
         "missing_in_books": "In GSTR-2B, not in the books", "gstin_differs": "Same invoice, different GSTIN"}


def sheet(result: dict) -> bytes:
    rows = [["Status", "Supplier GSTIN", "Supplier", "Invoice", "Date", "Taxable (books)", "Tax (books)", "Taxable (2B)", "Tax (2B)", "Tax difference"]]
    for r in result["rows"]:
        b, g = r["books"] or {}, r["gstr2b"] or {}
        rows.append([LABEL[r["status"]], b.get("gstin") or g.get("gstin"), b.get("name") or g.get("name"), b.get("invoice") or g.get("invoice"),
                     b.get("date") or g.get("date"), b.get("taxable"), b.get("tax"), g.get("taxable"), g.get("tax"), r["tax_difference"]])
    summary = [["", "Invoices", "Tax"]] + [[LABEL[k], v["count"], v["tax"]] for k, v in result["totals"].items()] + \
        [[], ["ITC in books", "", result["itc_in_books"]], ["ITC in GSTR-2B", "", result["itc_in_2b"]], ["ITC at risk", "", result["itc_at_risk"]]]
    msgs = [["Supplier", "GSTIN", "Invoices", "Tax", "Message"]] + [[m["supplier"], m["gstin"], m["invoices"], m["tax"], m["message"]]
                                                                     for m in result.get("messages", [])]
    return core.xlsx_bytes({"Summary": summary, "Invoices": rows, "Supplier messages": msgs})
