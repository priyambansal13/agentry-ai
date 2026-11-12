"""Capital gains (CA Firm pack): a broker's tax P&L or a CAMS / KFintech statement -> STCG / LTCG and Schedule CG.

    read     Excel / CSV with one row per sale: name (or ISIN), quantity, buy date, sell date, buy value, sell value, and
             the 31-Jan-2018 fair market value when the broker gives it (Zerodha, Groww, Upstox, CAMS layouts and similar)
    classify listed shares and equity funds: long-term after 12 months (111A / 112A); debt funds bought from 1 Apr 2023:
             slab rates whatever the holding; other debt funds: long-term after 24 months
    compute  grandfathering for equity bought by 31 Jan 2018 (cost = higher of cost and the lower of FMV and sale value);
             rates by sale date (before 23 Jul 2024: 15% / 10%; from then: 20% / 12.5%); the ₹1.25 lakh 112A exemption
             is applied in the ITR computation
    flags    equity bought before Feb 2018 without an FMV, rows with missing dates or values, unknown asset types
Every figure comes from the file; nothing is estimated.
"""
from collections import defaultdict
from datetime import date

from pydantic import BaseModel

from agentry import official_rules as rules
from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core

CUTOFF = date(2024, 7, 23)  # the registry's default (official_rules: cg.rate_change)


def cutoff() -> date:
    return date.fromisoformat(str(rules.get("cg.rate_change")))
GRANDFATHER = date(2018, 1, 31)
DEBT_WORDS = ("debt", "liquid", "gilt", "bond", "overnight", "money market", "income fund", "corporate", "banking & psu", "banking and psu",
              "short duration", "ultra short", "credit risk", "dynamic bond", "floater", "treasury")


class CapGainsConfig(BaseModel):
    pass


register(AutomationTemplate(
    key="ca_capital_gains", name="Capital gains",
    description="Broker P&L and mutual fund statements to STCG/LTCG and Schedule CG.",
    config_model=CapGainsConfig, metrics=(),
))


def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month - (1 if b.day < a.day else 0)


def asset_type(name: str, given: str | None = None) -> str:
    s = f"{given or ''} {name}".lower()
    if any(w in s for w in DEBT_WORDS):
        return "debt_fund"
    if any(w in s for w in ("gold", "silver", "international", "fof", "fund of fund", "overseas", "nasdaq", "s&p")):
        return "other_fund"
    return "equity"


def parse(rows: list[list[str]]) -> list[dict]:
    h = core.header_row(rows, ("sell|exit|redemption|sale", "buy|entry|purchase|cost"))
    head, body = rows[h], rows[h + 1:]
    col = {
        "name": core.find_col(head, "Symbol", "Stock name", "Scrip", "Scheme name", "Security name", "Instrument", "Name", "Scheme"),
        "isin": core.find_col(head, "ISIN"),
        "qty": core.find_col(head, "Quantity", "Qty", "Units", "Sold units", "Redeemed units", avoid=("price", "value")),
        "buy_date": core.find_col(head, "Buy date", "Entry date", "Purchase date", "Date of purchase", "Acquisition date", "Buy Dt"),
        "sell_date": core.find_col(head, "Sell date", "Exit date", "Redemption date", "Sale date", "Date of sale", "Sell Dt"),
        "buy_value": core.find_col(head, "Buy value", "Purchase value", "Cost of acquisition", "Total buy value", "Entry value", "Purchase amount",
                                   "Buy amount", "Cost", avoid=("price", "date", "indexed")),
        "sell_value": core.find_col(head, "Sell value", "Sale value", "Sale consideration", "Redemption value", "Exit value", "Redemption amount",
                                    "Sell amount", avoid=("price", "date")),
        "fmv": core.find_col(head, "Fair market value", "FMV", "FMV as on 31-01-2018", "Grandfathered price", "Market value 31 Jan 2018",
                             avoid=("price",)) or core.find_col(head, "FMV price", "Grandfathered price"),
        "type": core.find_col(head, "Asset type", "Asset class", "Category", "Type"),
    }
    missing = [k for k in ("name", "sell_date", "buy_value", "sell_value") if col[k] is None]
    if missing:
        raise core.CaError(f"couldn't find these columns: {', '.join(missing)} (need name, buy and sell dates, buy and sell values)")
    out = []
    for n, r in enumerate(body, start=h + 2):
        g = {k: (r[i].strip() if i is not None and i < len(r) and isinstance(r[i], str) else (str(r[i]) if i is not None and i < len(r) else ""))
             for k, i in col.items()}
        if not g["name"] or g["name"].lower().startswith(("total", "grand total")):
            continue
        sell, buy = core.money(g["sell_value"]), core.money(g["buy_value"])
        if sell is None and buy is None:
            continue
        fmv = core.money(g["fmv"])
        qty = core.money(g["qty"]) or 0
        # an FMV column given per unit (a price) when it's much smaller than the values: multiply by quantity
        if fmv and qty and sell and fmv * 50 < sell:
            fmv = fmv * qty
        out.append({"row": n, "name": g["name"], "isin": g["isin"] or None, "qty": qty, "buy_date": core.parse_date(g["buy_date"]),
                    "sell_date": core.parse_date(g["sell_date"]), "buy_value": buy, "sell_value": sell, "fmv_2018": fmv,
                    "type": asset_type(g["name"], g["type"])})
    if not out:
        raise core.CaError("no sales found in this file")
    return out


def classify(t: dict) -> dict:
    flags = []
    if t["sell_value"] is None or t["buy_value"] is None:
        return t | {"term": None, "section": None, "gain": None, "flags": ["buy or sell value missing"]}
    if not t["buy_date"] or not t["sell_date"]:
        return t | {"term": None, "section": None, "gain": round(t["sell_value"] - t["buy_value"], 2), "flags": ["buy or sell date missing"]}
    held = _months(t["buy_date"], t["sell_date"])
    cost = t["buy_value"]
    if t["type"] == "equity":
        months = int(rules.num("cg.equity_long_months"))
        long = held >= months and (t["sell_date"] - t["buy_date"]).days > months * 365 // 12
        if long and t["buy_date"] <= GRANDFATHER:
            if t["fmv_2018"]:
                cost = max(cost, min(t["fmv_2018"], t["sell_value"]))
            else:
                flags.append("bought before Feb 2018: add the 31 Jan 2018 FMV for grandfathering (cost used as is)")
        section = "112A" if long else "111A"
    elif t["type"] == "debt_fund":
        if t["buy_date"] >= date(2023, 4, 1):
            long, section = False, "slab (50AA)"
        else:
            long = held > rules.num("cg.other_long_months") if t["sell_date"] >= cutoff() else held > 36
            section = "112" if long else "slab"
    else:
        long = held > rules.num("cg.other_long_months")
        section = "112" if long else "slab"
        flags.append("not a listed equity share or equity fund: check the asset type")
    gain = round(t["sell_value"] - cost, 2)
    return t | {"term": "long" if long else "short", "section": section, "cost": round(cost, 2), "gain": gain, "held_months": held,
                "after_cutoff": t["sell_date"] >= cutoff(), "flags": flags}


def summarise(rows: list[dict]) -> dict:
    s: dict[str, float] = defaultdict(float)
    for r in rows:
        if r.get("gain") is None or not r.get("section"):
            continue
        tag = "post" if r["after_cutoff"] else "pre"
        if r["section"] == "111A":
            s[f"stcg_111a_{tag}"] += r["gain"]
        elif r["section"] == "112A":
            s[f"ltcg_112a_{tag}"] += r["gain"]
        elif r["section"] == "112":
            s["ltcg_other"] += r["gain"]
        else:
            s["stcg_other"] += r["gain"]
    s = {k: round(v, 2) for k, v in s.items()}
    stcg = s.get("stcg_111a_pre", 0) + s.get("stcg_111a_post", 0)
    ltcg = s.get("ltcg_112a_pre", 0) + s.get("ltcg_112a_post", 0)
    notes = []
    if stcg < 0 or ltcg < 0 or s.get("ltcg_other", 0) < 0 or s.get("stcg_other", 0) < 0:
        notes.append("There are losses: short-term losses set off against any gains, long-term losses only against long-term gains; "
                     "what's left carries forward 8 years if the return is filed on time.")
    if any(r.get("section") == "112A" and r["after_cutoff"] is False for r in rows) and any(r.get("section") == "112A" and r["after_cutoff"] for r in rows):
        notes.append("112A sales on both sides of 23 Jul 2024: show them separately in Schedule 112A (10% before, 12.5% from then).")
    return {"by_section": s, "stcg_111a": round(stcg, 2), "ltcg_112a": round(ltcg, 2), "stcg_other": s.get("stcg_other", 0.0),
            "ltcg_other": s.get("ltcg_other", 0.0), "sales": len(rows), "sale_value": round(sum(r["sell_value"] or 0 for r in rows), 2),
            "flagged": sum(1 for r in rows if r.get("flags")), "notes": notes}


def compute(data: bytes, mime: str) -> dict:
    rows = [classify(t) for t in parse(core.table_rows(data, mime))]
    return {"summary": summarise(rows), "rows": [{**r, "buy_date": str(r["buy_date"] or ""), "sell_date": str(r["sell_date"] or "")} for r in rows]}


def sheet(result: dict) -> bytes:
    s = result["summary"]
    summary = [["Schedule CG", "Amount"], ["STCG 111A before 23 Jul 2024 (15%)", s["by_section"].get("stcg_111a_pre", 0)],
               ["STCG 111A from 23 Jul 2024 (20%)", s["by_section"].get("stcg_111a_post", 0)],
               ["LTCG 112A before 23 Jul 2024 (10%)", s["by_section"].get("ltcg_112a_pre", 0)],
               ["LTCG 112A from 23 Jul 2024 (12.5%)", s["by_section"].get("ltcg_112a_post", 0)],
               ["Other LTCG (112, 12.5%)", s["ltcg_other"]], ["Other STCG (slab rates)", s["stcg_other"]], [],
               ["Sales", s["sales"]], ["Total sale value", s["sale_value"]], ["Rows to check", s["flagged"]], *[[n] for n in s["notes"]]]
    rows = [["Name", "ISIN", "Qty", "Buy date", "Sell date", "Buy value", "FMV 31-Jan-2018", "Cost used", "Sell value", "Gain", "Term", "Section", "Check"]]
    for r in result["rows"]:
        rows.append([r["name"], r["isin"], r["qty"], r["buy_date"], r["sell_date"], r["buy_value"], r["fmv_2018"], r.get("cost"), r["sell_value"],
                     r.get("gain"), r.get("term"), r.get("section"), "; ".join(r.get("flags") or [])])
    return core.xlsx_bytes({"Schedule CG": summary, "Sales": rows})
