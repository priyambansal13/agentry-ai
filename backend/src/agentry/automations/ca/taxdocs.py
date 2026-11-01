"""Tax documents reader + mismatch finder (CA Firm pack).

    read       Form 16, Form 16A, AIS, TIS or Form 26AS (PDF text, JSON / text download, or a photo) -> income, TDS and
               tax-paid lines; every line keeps the exact text it came from, and a line whose amount isn't in that text
               (or whose text isn't in the document) is marked untraced and never used silently
    compare    for one client and assessment year: TDS per deductor in Form 16 vs AIS / 26AS, salary per employer, and
               income the department knows about that the employer's Form 16 doesn't cover (deposit and savings
               interest, dividends, sales of shares and property, rent) -> points to check, each with its sources
    sheet      one Excel per client: every line with its source, and the points to check
The CA decides; nothing here files or claims anything.
"""
import base64
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.config import BACKEND
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

SAMPLES = BACKEND / "samples" / "ca"
TAX_DOCS = ("form16", "form16a", "ais", "tis", "26as")
INCOME = {"salary": "Salary", "interest_savings": "Savings bank interest", "interest_deposit": "Deposit interest",
          "interest_other": "Other interest", "dividend": "Dividend", "securities_sale": "Sale of shares / mutual funds",
          "mutual_fund_sale": "Sale of mutual funds", "property_sale": "Sale of property", "rent": "Rent", "other_income": "Other income"}


class TaxDocsConfig(BaseModel):
    tds_tolerance: int = Field(10, ge=0, le=1000, title="Ignore TDS differences up to (₹)", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ca_tax_docs_reader", name="Tax documents reader",
    description="Form 16, AIS, TIS and 26AS into one sheet per client, with mismatches flagged.",
    config_model=TaxDocsConfig, metrics=(),
))


@lru_cache
def _samples() -> dict[str, dict]:
    p = SAMPLES / "samples.json"
    return json.loads(p.read_text()) if p.exists() else {}


def sample_files() -> list[Path]:
    return [SAMPLES / n for n in _samples() if (SAMPLES / n).exists()]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _amount_in(quote: str, amount: float) -> bool:
    nums = {core.money(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", quote or "")}
    return any(n is not None and abs(n - amount) < 1 for n in nums)


def trace(items: list[dict], source_text: str | None) -> list[dict]:
    """Each line: traced = its quote is in the document (when there's text to check) and contains its amount."""
    body = _norm(source_text) if source_text else None
    out = []
    for i in items:
        amount = core.money(i.get("amount"))
        if amount is None or i.get("category") not in (*INCOME, "tds", "tcs", "advance_tax", "self_assessment_tax", "refund", "deduction"):
            continue
        q = str(i.get("quote") or "")
        in_doc = body is None or (_norm(q) in body if q else False)
        tds = core.money(i.get("tds")) or 0.0
        # the line's own number must be in its quote (for a TDS line, the TDS is enough), and so must any TDS on it
        shown = _amount_in(q, amount) or (i.get("category") in ("tds", "tcs") and tds > 0 and _amount_in(q, tds))
        traced = bool(q) and in_doc and shown and (tds == 0 or _amount_in(q, tds))
        out.append({"category": i["category"], "description": str(i.get("description") or "")[:160], "payer": i.get("payer"),
                    "payer_id": (i.get("payer_id") or "").upper() or None, "section": i.get("section"), "amount": amount,
                    "tds": tds, "quote": q[:240], "traced": traced})
    return out


async def read_file(org_id: str, file_id: str) -> dict:
    """Read one uploaded file and store the result on it (ca_files.extracted)."""
    async with tenant_session(org_id) as conn:
        f = (await conn.execute(text("select * from app.ca_files where id = cast(:i as uuid)"), {"i": file_id})).mappings().first()
    if not f:
        raise core.CaError("file not found")
    data = core.path_of(f).read_bytes()
    txt = core.text_of(data, f["mime"], 60000)
    mock = _samples().get(f["filename"] or "") or {"doc_type": "other", "items": []}
    prompt = load("ca_tax_document")
    messages = prompt.render(filename=f["filename"] or "", text=f"The document's text:\n{txt}" if txt else "The document is attached as an image.")
    if not txt:
        if not f["mime"].startswith("image/"):
            raise core.CaError("this file has no text to read: upload the PDF with text, the JSON download, or a clear photo")
        messages[-1] = {"role": "user", "content": [{"type": "text", "text": messages[-1]["content"]},
                                                    {"type": "image_url", "image_url": {"url": f"data:{f['mime']};base64,{base64.b64encode(data).decode()}"}}]}
    try:
        res = await complete(prompt.tier, messages, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(mock), temperature=0)
    except AllModelsFailed as e:
        raise core.CaError("the reading service is busy: try again in a minute") from e
    raw = res.data if isinstance(res.data, dict) else {}
    doc_type = raw.get("doc_type") if raw.get("doc_type") in (*TAX_DOCS, "other") else "other"
    out = {"doc_type": doc_type, "assessment_year": raw.get("assessment_year"), "pan": (raw.get("pan") or "").upper() or None,
           "name": raw.get("name"), "items": trace(raw.get("items") or [], txt), "photo": txt is None, "model": res.model}
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.ca_files set extracted = cast(:e as jsonb), doc_type = :d where id = cast(:i as uuid)"),
                           {"e": json.dumps(out), "d": doc_type, "i": file_id})
    return out


def _key(payer_id: str | None, payer: str | None) -> str:
    return (payer_id or "").upper() or _norm(payer or "")[:30]


def compare(docs: list[dict], client_pan: str | None = None, tolerance: float = 10) -> list[dict]:
    """docs: [{file_id, filename, extracted}]. Points to check, most important first."""
    points: list[dict] = []
    lines = [(d, i) for d in docs for i in (d["extracted"] or {}).get("items", []) if i.get("traced")]
    src = lambda d, i: {"file_id": d["file_id"], "file": d["filename"], "quote": i["quote"]}
    for d in docs:
        e = d["extracted"] or {}
        if client_pan and e.get("pan") and e["pan"] != client_pan.upper():
            points.append({"severity": "high", "kind": "pan", "message": f"{d['filename']} is for PAN {e['pan']}, not this client's {client_pan}.",
                           "sources": [{"file_id": d["file_id"], "file": d["filename"], "quote": e["pan"]}]})
        untraced = [i for i in e.get("items", []) if not i.get("traced")]
        if untraced:
            points.append({"severity": "medium", "kind": "untraced", "message": f"{len(untraced)} line(s) in {d['filename']} couldn't be traced to "
                           f"its text{' (it was a photo)' if e.get('photo') else ''}: check them by hand.",
                           "sources": [{"file_id": d["file_id"], "file": d["filename"], "quote": i["quote"]} for i in untraced[:5]]})
    f16 = [(d, i) for d, i in lines if d["extracted"]["doc_type"] in ("form16", "form16a")]
    dept = [(d, i) for d, i in lines if d["extracted"]["doc_type"] in ("ais", "26as", "tis")]
    # TDS per deductor
    tds_f16, tds_dept = defaultdict(list), defaultdict(list)
    for d, i in f16:
        if i["tds"]:
            tds_f16[_key(i["payer_id"], i["payer"])].append((d, i))
    for d, i in dept:
        if i["tds"]:
            tds_dept[_key(i["payer_id"], i["payer"])].append((d, i))
    for k in tds_f16.keys() | tds_dept.keys():
        a = max((i["tds"] for _, i in tds_f16.get(k, [])), default=None)
        b = max((i["tds"] for _, i in tds_dept.get(k, [])), default=None)
        who = next((i["payer"] for _, i in tds_f16.get(k, []) + tds_dept.get(k, []) if i["payer"]), k)
        if a is not None and b is not None and abs(a - b) > tolerance:
            short = a - b
            points.append({"severity": "high", "kind": "tds_mismatch",
                           "message": f"TDS from {who}: Form 16 shows {core.inr(a)}, the department shows {core.inr(b)} "
                                      f"({core.inr(abs(short))} {'less' if short > 0 else 'more'} in AIS / 26AS). "
                                      + ("Only what's in 26AS can be claimed: ask the employer to correct their TDS return." if short > 0 else "Check which is right."),
                           "sources": [src(d, i) for d, i in tds_f16[k][:1] + tds_dept[k][:1]]})
        elif a is not None and b is None and dept:
            points.append({"severity": "high", "kind": "tds_missing", "message": f"TDS of {core.inr(a)} from {who} is in Form 16 but not in AIS / 26AS yet.",
                           "sources": [src(d, i) for d, i in tds_f16[k][:1]]})
    # salary per employer
    sal_f16 = {_key(i["payer_id"], i["payer"]): (d, i) for d, i in f16 if i["category"] == "salary"}
    for d, i in dept:
        if i["category"] != "salary":
            continue
        k = _key(i["payer_id"], i["payer"])
        if k not in sal_f16:
            points.append({"severity": "high", "kind": "salary_unexplained", "message": f"AIS shows salary of {core.inr(i['amount'])} from {i['payer'] or k} "
                           "but there's no Form 16 from them: ask the client (another job this year?).", "sources": [src(d, i)]})
        elif abs(sal_f16[k][1]["amount"] - i["amount"]) > max(tolerance, 1):
            points.append({"severity": "medium", "kind": "salary_mismatch", "message": f"Salary from {i['payer'] or k}: Form 16 {core.inr(sal_f16[k][1]['amount'])}, "
                           f"AIS {core.inr(i['amount'])}.", "sources": [src(*sal_f16[k]), src(d, i)]})
    # income the department knows about beyond salary
    seen = set()
    for d, i in dept:
        if i["category"] in ("salary", "tds", "tcs", "advance_tax", "self_assessment_tax", "refund", "deduction"):
            continue
        k = (i["category"], _key(i["payer_id"], i["payer"]))
        if k in seen:
            continue
        seen.add(k)
        label = INCOME.get(i["category"], i["category"])
        what = {"securities_sale": "Get the capital gains statement (broker tax P&L / CAMS) to compute the gain.",
                "mutual_fund_sale": "Get the CAMS / KFintech capital gains statement.",
                "property_sale": "Get the sale and purchase deeds: capital gains and 194-IA TDS.",
                "interest_savings": "Declare it under other sources (80TTA up to ₹10,000 in the old regime).",
                "rent": "Declare it under house property.",
                }.get(i["category"], "Declare it under other sources" + (f"; claim the TDS of {core.inr(i['tds'])}." if i["tds"] else "."))
        points.append({"severity": "medium", "kind": "income_to_declare",
                       "message": f"{label} of {core.inr(i['amount'])} from {i['payer'] or 'unknown'} is in {d['extracted']['doc_type'].upper()}. {what}",
                       "sources": [src(d, i)], "category": i["category"], "amount": i["amount"], "tds": i["tds"]})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(points, key=lambda p: order[p["severity"]])


async def client_docs(conn: AsyncConnection, client_id: str, ay: str | None = None) -> list[dict]:
    rows = (await conn.execute(text("""select id::text as file_id, filename, extracted, created_at from app.ca_files
        where client_id = cast(:c as uuid) and extracted is not null and doc_type = any(:t) order by created_at"""),
        {"c": client_id, "t": list(TAX_DOCS)})).mappings().all()
    docs = [dict(r) for r in rows]
    return [d for d in docs if not ay or (d["extracted"] or {}).get("assessment_year") in (None, ay)]


def summary(docs: list[dict]) -> dict:
    """Totals by category from the department's statements (AIS / 26AS), else Form 16; traced lines only."""
    dept = [d for d in docs if d["extracted"]["doc_type"] in ("ais", "26as", "tis")]
    use = dept or docs
    totals: dict[str, float] = defaultdict(float)
    tds = 0.0
    for d in use:
        for i in d["extracted"]["items"]:
            if i["traced"] and i["category"] in INCOME:
                totals[i["category"]] += i["amount"]
            if i["traced"] and i["tds"]:
                tds += i["tds"]
    return {"from": "AIS / 26AS" if dept else "Form 16", "income": dict(totals), "tds": tds}


def sheet(client: dict, docs: list[dict], points: list[dict]) -> bytes:
    rows = [["File", "Document", "Category", "Description", "Payer", "Payer TAN/PAN", "Section", "Amount", "TDS", "Traced", "Source text"]]
    for d in docs:
        e = d["extracted"]
        for i in e["items"]:
            rows.append([d["filename"], e["doc_type"].upper(), i["category"], i["description"], i["payer"] or "", i["payer_id"] or "",
                         i["section"] or "", i["amount"], i["tds"], "yes" if i["traced"] else "NO - check", i["quote"]])
    checks = [["Severity", "Point to check", "Sources"]] + [[p["severity"], p["message"], " | ".join(f"{s['file']}: {s['quote']}" for s in p["sources"])]
                                                           for p in points]
    head = [["Client", client["name"]], ["PAN", client.get("pan") or ""]]
    return core.xlsx_bytes({"Points to check": head + [[]] + checks, "All lines": rows})
