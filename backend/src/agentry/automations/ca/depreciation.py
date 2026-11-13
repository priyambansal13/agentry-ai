"""Depreciation (CA desk part 2, docs/PLAN-CA-DESK-2.md #6): a client's fixed asset register -> depreciation for the year
twice over: the books (Companies Act, Schedule II: straight line over the useful life) and the tax return (Income-tax:
written-down value by block of assets), with the timing difference for deferred tax. All by rules (no AI).

    read        the register through the Excel cleaner; columns found by name: asset, category, IT block (optional), date
                bought, date put to use, cost, opening accumulated depreciation or opening book WDV, opening tax WDV
                (optional), date sold, sale value, useful life, residual %, payment mode
    classify    the category (else the asset's name) -> the Income-tax block and the Schedule II useful life; an IT block
                column ("Plant & Machinery 15%") wins for the block, a useful-life column for the life; nothing matched ->
                plant and machinery, marked "assumed"
    books       SLM: (cost - residual) / life, for the days in the year the asset was in use (from the put-to-use date, up
                to the day before it was sold), never below the residual value (5% of cost unless given); profit or loss
                on sale; land isn't depreciated; goodwill and other intangibles without a life are flagged
    tax         per block: opening WDV + additions - sale money; additions put to use for less than 180 days in the year
                get half the rate; sale money above the block -> short-term capital gain (section 50), a block whose every
                asset is sold with WDV left -> short-term capital loss; an asset paid in cash over ₹10,000 isn't added
                (section 43(1)); not yet put to use -> capital work in progress, no depreciation
    opening     the tax WDV by block from the register's column, or entered on the result page; without either the book WDV
                is used and flagged (the tax computation of last year is the right figure)
    deferred    book WDV - tax WDV of the depreciable assets, opening and closing; the change at the tax rate is the year's
                deferred tax charge (or credit)
Rates (block rates, the half-rate days, the residual value, the tax rates for deferred tax) are official figures.
"""
import re
from collections import defaultdict
from datetime import date, timedelta

from agentry import official_rules as rules
from agentry.automations.ca import cleaner, core

BLOCKS = {  # IT block -> label (rate from official_rules "dep.<key>")
    "bld_res": "Buildings (residential)", "bld": "Buildings (other)", "bld_temp": "Temporary structures",
    "furniture": "Furniture and fittings", "pm": "Plant and machinery (general, incl. cars)", "vehicle_hire": "Motor buses, lorries, taxis used in a hiring business",
    "computer": "Computers and computer software", "energy": "Energy-saving and renewable energy devices", "intangible": "Know-how, patents, copyrights, trademarks, licences",
}
# (pattern on category / name, IT block, Schedule II class, useful life in years); first match wins
CLASSES = [
    (r"goodwill", None, "Goodwill", None),
    (r"\bland\b(?!.*\b(build|develop|shed))|freehold land|leasehold land", None, "Land", None),
    (r"software|\berp\b|licen[cs]e (fee|software)", "computer", "Computer software (intangible)", None),
    (r"patent|trade ?mark|copyright|know[- ]?how|franchise|licen[cs]e", "intangible", "Intangible assets", None),
    (r"server|network|switch|router|firewall", "computer", "Servers and networks", 6),
    (r"computer|laptop|desktop|\bpc\b|printer|scanner|monitor|tablet|ipad", "computer", "Computers (end-user devices)", 3),
    (r"temporary|tin shed|portable cabin|porta ?cabin", "bld_temp", "Temporary structures", 3),
    (r"factory (building|shed)|industrial (building|shed)|godown|warehouse", "bld", "Factory buildings", 30),
    (r"residential|staff quarter|\bflat\b|guest ?house|bungalow", "bld_res", "Buildings (residential)", 60),
    (r"building|premises|office space|\bshop\b|\bshed\b", "bld", "Buildings (other than factory)", 60),
    (r"electrical|wiring|lighting", "furniture", "Electrical installations", 10),
    (r"furniture|fixture|fitting|interior|partition|almirah|cabinet|chair|table|workstation", "furniture", "Furniture and fittings", 10),
    (r"solar|wind ?(mill|turbine)|energy[- ]saving|pollution control|effluent", "energy", "Plant and machinery (energy / pollution)", 15),
    (r"(truck|lorry|bus|tempo|taxi|tanker|cab)\b.*\b(hire|hiring|rental|rent)\b|\b(hire|hiring|rental)\b.*\b(truck|lorry|bus|tempo|taxi|tanker|cab)", "vehicle_hire",
     "Motor buses, lorries and taxis (hire business)", 6),
    (r"truck|lorry|\bbus\b|tempo|tanker|pick ?up", "pm", "Motor lorries and buses", 8),
    (r"motor ?cycle|scooter|two[- ]wheeler|\bbike\b|activa", "pm", "Motor cycles and scooters", 10),
    (r"\bcar\b|vehicle|\bsuv\b|sedan|innova|swift|creta|motor", "pm", "Motor cars", 8),
    ((r"mobile|phone|office equipment|air ?condition|\bac\b|cctv|camera|xerox|photocopi|projector|refrigerat|fridge|cooler|\bups\b|inverter|"
      r"water purifier|ro plant|television|\btv\b"), "pm", "Office equipment", 5),
    (r"plant|machine|equipment|tool|\bdie\b|mould|mold|crane|compressor|generator|dg set|boiler|lathe|cnc|press|furnace|pump", "pm",
     "Plant and machinery (general)", 15),
]
BLOCK_TEXT = [(r"residential", "bld_res"), (r"temporary", "bld_temp"), (r"building", "bld"), (r"furniture|fitting", "furniture"),
              (r"computer|software", "computer"), (r"hire|hiring|taxi", "vehicle_hire"), (r"energy|solar|pollution|renewable", "energy"),
              (r"intangible|know|patent|copyright|trademark|licen", "intangible"), (r"plant|machinery|vehicle|car", "pm")]
SEVERITY = {"serious": 0, "warning": 1, "info": 2}


def rate(block: str) -> float:
    return rules.num(f"dep.{block}")


def _fy(fy: int | str | None, dates: list[date]) -> int:
    """The year's start (2025 for FY 2025-26): given ("FY 2025-26", "2025-26", 2025), else the year of the register's latest
    purchase or sale (a put-to-use date after the year end is capital work in progress, not a later year)."""
    if isinstance(fy, int):
        return fy
    m = re.search(r"(20\d{2})", str(fy or ""))
    if m:
        return int(m[1])
    d = max(dates) if dates else date.today()
    return d.year if d.month >= 4 else d.year - 1


def _d(v: object) -> date | None:
    s = str(v or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    return core.parse_date(s) if s else None


def _f(v: object) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return cleaner._num(v) if isinstance(v, str) and v.strip() else None


def classify(category: str, name: str, block_text: str = "") -> tuple[str | None, str, int | None, bool]:
    """(IT block, Schedule II class, useful life, assumed)."""
    for text_ in (category, name):
        for rx, blk, cls, life in CLASSES:
            if text_ and re.search(rx, text_, re.IGNORECASE):
                if block_text:
                    blk = next((b for rx2, b in BLOCK_TEXT if re.search(rx2, block_text, re.IGNORECASE)), blk)
                return blk, cls, life, False
    blk = next((b for rx2, b in BLOCK_TEXT if block_text and re.search(rx2, block_text, re.IGNORECASE)), "pm")
    return blk, "Plant and machinery (general)", 15, True


def read(rows: list[list[str]]) -> tuple[list[dict], dict]:
    """(assets, columns used). Dates as ISO strings; money as floats (None when blank)."""
    c = cleaner.clean(rows, drop_duplicates=False)
    cols, kinds, data = c["columns"], c["kinds"], c["rows"]
    lc = [x.lower() for x in cols]
    blank = {j for j in range(len(cols)) if all(str(r[j] if r[j] is not None else "").strip() == "" for r in data)}

    def col(rx: str, kind: str | None = None, avoid: str | None = None) -> int | None:
        return next((j for j, x in enumerate(lc) if re.search(rx, x) and (kind is None or kinds[j] == kind or j in blank)
                     and not (avoid and re.search(avoid, x))), None)
    k = {
        "name": col(r"asset|description|particulars|item|name", avoid=r"category|class|block|group|code|date|cost|value|life"),
        "category": col(r"category|class|type|group|head|nature", avoid=r"block|date|tax|it\b"),
        "block": col(r"\bblock\b|it block|tax block|rate as per it|it rate"),
        "acquired": col(r"purchase|acqui|bought|invoice date|date of (purchase|acq)|capitali[sz]", "date", avoid=r"sale|sold"),
        "in_use": col(r"put to use|in use|installed|use date|date of use|commission", "date"),
        "cost": col(r"\bcost\b|gross|original|purchase (value|price|amount)|amount|value", "number", avoid=r"sale|sold|wdv|written|dep|residual|scrap|tax"),
        "acc": col(r"(opening )?(accumulated|acc\.?) dep|dep(reciation)? (till|to date|upto|up to|b/f)|opening dep", "number"),
        "book_wdv": col(r"(opening|book).*(wdv|written down|carrying|net block)|^(wdv|net block|carrying)", "number", avoid=r"tax|\bit\b|income"),
        "tax_wdv": col(r"(tax|\bit\b|income.?tax).*(wdv|written down)|(wdv|written down).*(tax|\bit\b|income)", "number"),
        "sold": col(r"sale date|date of sale|sold on|disposal date|date of disposal|discard", "date"),
        "sale_value": col(r"sale (value|proceeds|amount|price)|sold for|disposal (value|proceeds)|realis|scrap value", "number"),
        "life": col(r"useful life|\blife\b", "number"),
        "residual": col(r"residual|salvage", "number"),
        "mode": col(r"payment mode|\bmode\b|paid (by|via|through)", "text"),
    }
    if k["name"] is None:
        k["name"] = next((j for j, kd in enumerate(kinds) if kd == "text" and j != k["category"]), None)
    if k["name"] is None or k["cost"] is None:
        raise core.CaError("this doesn't look like a fixed asset register: it needs an asset column and a cost column")
    out = []
    for r in data:
        def g(key: str, r: list = r) -> object:
            return r[k[key]] if k[key] is not None else None
        name = str(g("name") or "").strip()
        if not name or cleaner.TOTAL.match(name):
            continue
        out.append({"name": name, "category": str(g("category") or "").strip(), "block_text": str(g("block") or "").strip(),
                    "acquired": (d.isoformat() if (d := _d(g("acquired"))) else None), "in_use": (d.isoformat() if (d := _d(g("in_use"))) else None),
                    "cost": _f(g("cost")), "acc": _f(g("acc")), "book_wdv": _f(g("book_wdv")), "tax_wdv": _f(g("tax_wdv")),
                    "sold": (d.isoformat() if (d := _d(g("sold"))) else None), "sale_value": _f(g("sale_value")),
                    "life": _f(g("life")), "residual": _f(g("residual")), "mode": str(g("mode") or "").strip()})
    if not out:
        raise core.CaError("no assets found in the register")
    used = {key: cols[j] for key, j in k.items() if j is not None}
    return out, used


def _years_between(a: date, b: date) -> float:
    return max(0.0, (b - a).days / 365.25)


def build(assets: list[dict], *, fy: int | str | None = None, kind: str = "company", tax_opening: dict[str, float] | None = None,
          tax_rate: float | None = None, client: str = "") -> dict:
    """The year's depreciation, books and tax, from the register as read (pure: the result page rebuilds with it)."""
    dates = [d for a in assets for x in ("acquired", "sold") if (d := _d(a.get(x)))]
    y = _fy(fy, dates)
    start, end = date(y, 4, 1), date(y + 1, 3, 31)
    ydays = (end - start).days + 1
    half_days = int(rules.num("dep.half_days"))
    res_default = rules.num("dep.residual")
    checks: list[dict] = []

    def check(sev: str, what: str, assets_: list[str] | None = None) -> None:
        checks.append({"severity": sev, "what": what, "assets": (assets_ or [])[:12], "count": len(assets_ or [])})

    out: list[dict] = []
    by_check: dict[str, list[str]] = defaultdict(list)
    for a in assets:
        name, cost = a["name"], a.get("cost") or 0.0
        if cost <= 0:
            by_check["no_cost"].append(name)
            continue
        blk, cls, life, assumed = classify(a.get("category", ""), name, a.get("block_text", ""))
        if a.get("life"):
            if life and abs(a["life"] - life) >= 1:
                by_check["life_differs"].append(f"{name} ({a['life']:g} vs {life} years)")
            life = a["life"]
        if assumed:
            by_check["assumed"].append(name)
        acquired, in_use, sold = _d(a.get("acquired")), _d(a.get("in_use")), _d(a.get("sold"))
        if in_use and acquired and in_use < acquired:
            by_check["use_before_buy"].append(name)
        use_from = in_use or acquired
        addition = bool(acquired and start <= acquired <= end) or bool(not acquired and in_use and start <= in_use <= end)
        if acquired and acquired > end:
            by_check["after_year"].append(name)
            continue
        if sold and sold < start:
            continue  # sold in an earlier year
        cwip = addition and (use_from is None or use_from > end) or (in_use is not None and in_use > end)
        res_pct = (a["residual"] / 100 if a["residual"] and a["residual"] > 1 else a["residual"]) if a.get("residual") is not None else res_default
        residual = round(cost * res_pct, 2)
        depreciable = cls not in ("Land", "Goodwill") and life is not None and not cwip

        # ---- books: opening carrying amount ----
        if addition:
            opening = 0.0
        elif a.get("book_wdv") is not None:
            opening = a["book_wdv"]
        elif a.get("acc") is not None:
            opening = cost - a["acc"]
        elif depreciable and use_from:
            worked = min(cost - residual, (cost - residual) / life * _years_between(use_from, start))
            opening = round(cost - worked, 2)
            by_check["opening_worked"].append(name)
        else:
            opening = cost
            if depreciable:
                by_check["no_dates"].append(name)
        if cls in ("Goodwill",) or (cls in ("Intangible assets", "Computer software (intangible)") and not a.get("life")):
            by_check["intangible_life"].append(name)
            if cls != "Goodwill" and not a.get("life"):
                life = 5 if "software" in cls.lower() else 10
                depreciable = not cwip
        in_from = max(start, use_from) if use_from else start
        in_to = min(end, sold - timedelta(days=1)) if sold and sold <= end else end
        days = max(0, (in_to - in_from).days + 1) if depreciable else 0
        carrying = opening + (cost if addition else 0.0)
        charge = 0.0
        if depreciable and days:
            charge = round(min((cost - residual) / life * days / ydays, max(0.0, carrying - residual)), 2)
            if carrying - residual <= 0.5:
                by_check["fully_depreciated"].append(name)
        sold_in_year = bool(sold and start <= sold <= end)
        if sold_in_year and a.get("sale_value") is None:
            by_check["no_sale_value"].append(name)
        sale_value = (a.get("sale_value") or 0.0) if sold_in_year else 0.0
        at_sale = round(carrying - charge, 2)
        book = {"opening": round(opening, 2), "addition": round(cost, 2) if addition else 0.0, "depreciation": charge, "days": days,
                "disposal": at_sale if sold_in_year else 0.0, "profit_on_sale": round(sale_value - at_sale, 2) if sold_in_year else None,
                "closing": 0.0 if sold_in_year else at_sale}

        # ---- tax ----
        cash = bool(re.search(r"\bcash\b", a.get("mode") or "", re.IGNORECASE)) and cost > 10000
        if cash and addition:
            by_check["cash"].append(f"{name} (₹{cost:,.0f})")
        tax_use_days = (end - use_from).days + 1 if use_from and addition and not cwip else None
        out.append({"name": name, "category": a.get("category") or "", "class": cls, "block": blk, "assumed": assumed, "life": life,
                    "residual": residual, "cost": round(cost, 2), "acquired": a.get("acquired"), "in_use": a.get("in_use"), "sold": a.get("sold") if sold_in_year else None,
                    "sale_value": sale_value if sold_in_year else None, "addition": addition, "cwip": cwip, "book": book,
                    "tax": {"addition": round(cost, 2) if addition and not cwip and not cash and blk else 0.0,
                            "half": bool(tax_use_days is not None and tax_use_days < half_days and blk and not cash),
                            "days_used": tax_use_days, "cash_disallowed": cash and addition,
                            "opening": a.get("tax_wdv") if not addition and blk else None}})
        if cwip:
            by_check["cwip"].append(name)

    # ---- tax blocks ----
    tax_opening = {k: float(v) for k, v in (tax_opening or {}).items() if k in BLOCKS}
    blocks = []
    opening_proxy: list[str] = []
    for blk, label in BLOCKS.items():
        members = [x for x in out if x["block"] == blk]
        if not members and blk not in tax_opening:
            continue
        given = [x["tax"]["opening"] for x in members if x["tax"]["opening"] is not None]
        if blk in tax_opening:
            opening, how = tax_opening[blk], "entered"
        elif given:
            opening, how = sum(given), "register"
        elif any(not x["addition"] for x in members):
            opening, how = sum(x["book"]["opening"] for x in members if not x["addition"]), "book WDV (not the tax figure)"
            opening_proxy.append(label)
        else:
            opening, how = 0.0, "new block this year"
        full_add = sum(x["tax"]["addition"] for x in members if not x["tax"]["half"])
        half_add = sum(x["tax"]["addition"] for x in members if x["tax"]["half"])
        sales = sum(x["sale_value"] or 0.0 for x in members if x["sold"])
        r = rate(blk)
        full_base, half_base = opening + full_add - sales, half_add
        if full_base < 0:
            half_base, full_base = half_base + full_base, 0.0
        stcg = stcl = 0.0
        remaining = [x for x in members if not x["sold"] and not x["cwip"]]
        if half_base < 0:
            stcg, half_base = -half_base, 0.0
        if not remaining and members and full_base + half_base > 0 and sales:
            stcl, full_base, half_base = full_base + half_base, 0.0, 0.0
        dep_full, dep_half = round(full_base * r, 2), round(half_base * r / 2, 2)
        blocks.append({"key": blk, "label": label, "rate": r, "opening": round(opening, 2), "opening_from": how,
                       "additions_full": round(full_add, 2), "additions_half": round(half_add, 2), "sales": round(sales, 2),
                       "depreciation": round(dep_full + dep_half, 2), "depreciation_half": dep_half,
                       "closing": round(full_base + half_base - dep_full - dep_half, 2), "stcg": round(stcg, 2), "stcl": round(stcl, 2),
                       "assets": len(members)})
    if opening_proxy:
        check("warning", "Opening tax WDV not in the register for: " + ", ".join(opening_proxy) + ". The book WDV is used until you enter last year's "
              "closing tax WDV for each block (from last year's tax computation) on this page.")

    # ---- deferred tax: book vs tax WDV of the depreciable assets (cash-paid ones never get tax depreciation: permanent) ----
    dep_assets = [x for x in out if x["block"] and not x["tax"]["cash_disallowed"]]
    book_open = sum(x["book"]["opening"] for x in dep_assets if not x["addition"])
    book_close = sum(x["book"]["closing"] for x in dep_assets if not x["cwip"])
    tax_open, tax_close = sum(b["opening"] for b in blocks), sum(b["closing"] for b in blocks)
    company = kind in ("company", "pvt_ltd", "public_ltd")
    t_rate = tax_rate if tax_rate is not None else rules.num("dep.tax_company" if company else "dep.tax_firm")
    diff_open, diff_close = round(book_open - tax_open, 2), round(book_close - tax_close, 2)
    deferred = {"book_wdv_opening": round(book_open, 2), "tax_wdv_opening": round(tax_open, 2), "difference_opening": diff_open,
                "book_wdv_closing": round(book_close, 2), "tax_wdv_closing": round(tax_close, 2), "difference_closing": diff_close,
                "tax_rate": t_rate, "dtl_opening": round(diff_open * t_rate, 2), "dtl_closing": round(diff_close * t_rate, 2),
                "charge": round((diff_close - diff_open) * t_rate, 2),
                "position": "liability" if diff_close > 0 else "asset" if diff_close < 0 else "none"}

    # ---- books by Schedule II class ----
    classes: dict[str, dict] = {}
    for x in out:
        if x["cwip"]:
            continue  # shown as capital work in progress, not property, plant and equipment
        c = classes.setdefault(x["class"], {"class": x["class"], "life": x["life"], "opening": 0.0, "additions": 0.0, "depreciation": 0.0,
                                            "disposals": 0.0, "closing": 0.0, "assets": 0})
        b = x["book"]
        for k_, v in (("opening", b["opening"]), ("additions", b["addition"]), ("depreciation", b["depreciation"]), ("disposals", b["disposal"]),
                      ("closing", b["closing"])):
            c[k_] = round(c[k_] + v, 2)
        c["assets"] += 1

    msgs = {
        "assumed": ("warning", "Category not recognised: treated as plant and machinery (15% block, 15 years). Set the category in the register:"),
        "no_cost": ("warning", "No cost: left out:"),
        "life_differs": ("info", "Useful life in the register differs from Schedule II: allowed when justified (technical advice), and must be disclosed in the notes:"),
        "use_before_buy": ("warning", "Put to use before the purchase date: check the dates:"),
        "after_year": ("warning", "Bought after the year end: left out:"),
        "opening_worked": ("info", "No opening accumulated depreciation or WDV: worked out by straight line from the put-to-use date. Check against last year's register:"),
        "no_dates": ("warning", "No purchase or put-to-use date and no opening depreciation: not depreciated:"),
        "intangible_life": ("warning", ("Intangibles aren't covered by Schedule II's lives (AS 26 / Ind AS 38). Goodwill gets no tax depreciation; "
                                        "for the others give a useful life in the register (5 years used for software, 10 for the rest):")),
        "fully_depreciated": ("info", "Fully depreciated (down to the residual value), still in use:"),
        "no_sale_value": ("warning", "Sold in the year with no sale value: taken as nil, which overstates the tax depreciation if anything was received:"),
        "cash": ("serious", "Paid in cash over ₹10,000: not added to the block (section 43(1)); confirm the mode of payment:"),
        "cwip": ("info", "Bought but not yet put to use: capital work in progress, no depreciation this year:"),
    }
    for key, names in by_check.items():
        sev, what = msgs[key]
        check(sev, f"{what} {', '.join(names[:8])}{' …' if len(names) > 8 else ''}", names)
    new_pm = [x["name"] for x in out if x["addition"] and not x["cwip"] and x["block"] in ("pm", "energy")
              and x["class"] not in ("Motor cars", "Motor cycles and scooters", "Office equipment")]
    if new_pm:
        check("info", "New plant and machinery: a manufacturer may also claim additional depreciation (20%, half if used under 180 days) "
                      "unless it pays tax under section 115BAA / 115BAB. Not included here: " + ", ".join(new_pm[:8]), new_pm)
    half = [x["name"] for x in out if x["tax"]["half"]]
    if half:
        check("info", f"Put to use for less than {half_days} days in the year: half the block rate on them: " + ", ".join(half[:8]), half)
    for b in blocks:
        if b["stcg"]:
            check("serious", f"{b['label']}: sale money exceeds the block by ₹{b['stcg']:,.0f}: short-term capital gain under section 50, no depreciation on the block.")
        if b["stcl"]:
            check("warning", f"{b['label']}: every asset in the block was sold with ₹{b['stcl']:,.0f} WDV left: short-term capital loss under section 50 "
                             "(only if the register is the whole block: check last year's tax computation).")
    for x in out:
        if x["book"]["profit_on_sale"]:
            p = x["book"]["profit_on_sale"]
            check("info", f"{x['name']} sold on {x['sold']} for ₹{(x['sale_value'] or 0):,.0f}: book {'profit' if p > 0 else 'loss'} on sale ₹{abs(p):,.0f} "
                          "(in the P&L; for tax the sale money only reduces the block).", [x["name"]])
    checks.sort(key=lambda c: SEVERITY[c["severity"]])

    book_total = {k_: round(sum(c[k_] for c in classes.values()), 2) for k_ in ("opening", "additions", "depreciation", "disposals", "closing")}
    summary = {"assets": len(out), "additions": sum(1 for x in out if x["addition"]), "sold": sum(1 for x in out if x["sold"]),
               "book_depreciation": book_total["depreciation"], "tax_depreciation": round(sum(b["depreciation"] for b in blocks), 2),
               "deferred_tax_charge": deferred["charge"], "serious": sum(1 for c in checks if c["severity"] == "serious"),
               "warnings": sum(1 for c in checks if c["severity"] == "warning"), "cwip": round(sum(x["cost"] for x in out if x["cwip"]), 2)}
    return {"client": client, "year": {"label": f"FY {y}-{str(y + 1)[2:]}", "start": start.isoformat(), "end": end.isoformat(), "fy": y},
            "kind": kind, "assets": out, "classes": list(classes.values()), "book_total": book_total, "blocks": blocks, "deferred_tax": deferred,
            "checks": checks, "summary": summary, "half_days": half_days, "register": assets, "tax_opening": tax_opening, "tax_rate_given": tax_rate}


def compute(data: bytes, mime: str, *, fy: int | str | None = None, kind: str = "company", client: str = "", tax_opening: dict | None = None) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("depreciation works on a fixed asset register in CSV or Excel (.xlsx)")
    rows = core.table_rows(data, mime)
    if fy is None:  # a title line above the header: "Fixed Asset Register FY 2025-26"
        fy = next((m[1] for r in rows[:6] for c in r if (m := re.search(r"\b(?:FY|F\.Y\.|financial year)\s*(20\d{2})", str(c or ""), re.IGNORECASE))), None)
    assets, used = read(rows)
    return build(assets, fy=fy, kind=kind, client=client, tax_opening=tax_opening) | {"columns": used}


def rebuild(result: dict, tax_opening: dict[str, float]) -> dict:
    """The result page: last year's closing tax WDV by block entered -> blocks and deferred tax worked out again."""
    bad = [k for k in tax_opening if k not in BLOCKS]
    if bad:
        raise core.CaError(f"unknown block: {', '.join(bad)}")
    merged = {**(result.get("tax_opening") or {}), **{k: float(v) for k, v in tax_opening.items()}}
    return build(result["register"], fy=result["year"]["fy"], kind=result.get("kind", "company"), tax_opening=merged,
                 tax_rate=result.get("tax_rate_given"), client=result.get("client", "")) | {"columns": result.get("columns", {})}


def sheet(result: dict) -> bytes:
    pct = lambda r: f"{r * 100:g}%"
    return core.xlsx_bytes({
        "Books (Schedule II)": [["Class", "Useful life (years)", "Opening WDV", "Additions", "Depreciation", "Disposals", "Closing WDV", "Assets"],
                                *[[c["class"], c["life"] or "", c["opening"], c["additions"], c["depreciation"], c["disposals"], c["closing"], c["assets"]]
                                  for c in result["classes"]],
                                ["Total", "", *[result["book_total"][k] for k in ("opening", "additions", "depreciation", "disposals", "closing")]]],
        "Income-tax blocks": [["Block", "Rate", "Opening WDV", "Opening from", f"Additions ({result['half_days']}+ days)", f"Additions (under {result['half_days']} days)",
                               "Sales", "Depreciation", "of which at half rate", "Closing WDV", "STCG (s.50)", "STCL (s.50)"],
                              *[[b["label"], pct(b["rate"]), b["opening"], b["opening_from"], b["additions_full"], b["additions_half"], b["sales"],
                                 b["depreciation"], b["depreciation_half"], b["closing"], b["stcg"] or "", b["stcl"] or ""] for b in result["blocks"]]],
        "Asset-wise": [["Asset", "Category", "Schedule II class", "IT block", "Cost", "Bought", "Put to use", "Sold", "Sale value", "Life", "Residual",
                        "Opening WDV", "Addition", "Days", "Book depreciation", "Closing WDV", "Profit on sale", "Tax: half rate"],
                       *[[x["name"], x["category"], x["class"], BLOCKS.get(x["block"] or "", "none"), x["cost"], x["acquired"] or "", x["in_use"] or "",
                          x["sold"] or "", x["sale_value"] if x["sale_value"] is not None else "", x["life"] or "", x["residual"], x["book"]["opening"],
                          x["book"]["addition"], x["book"]["days"], x["book"]["depreciation"], x["book"]["closing"],
                          x["book"]["profit_on_sale"] if x["book"]["profit_on_sale"] is not None else "", "yes" if x["tax"]["half"] else ""]
                         for x in result["assets"]]],
        "Deferred tax": [["", "Opening", "Closing"],
                         ["Book WDV (depreciable assets)", result["deferred_tax"]["book_wdv_opening"], result["deferred_tax"]["book_wdv_closing"]],
                         ["Tax WDV", result["deferred_tax"]["tax_wdv_opening"], result["deferred_tax"]["tax_wdv_closing"]],
                         ["Timing difference", result["deferred_tax"]["difference_opening"], result["deferred_tax"]["difference_closing"]],
                         [f"Deferred tax at {result['deferred_tax']['tax_rate'] * 100:.3f}%", result["deferred_tax"]["dtl_opening"], result["deferred_tax"]["dtl_closing"]],
                         [], ["Charge for the year (credit if negative)", "", result["deferred_tax"]["charge"]]],
        "Checks": [["Severity", "Check"], *[[c["severity"], c["what"]] for c in result["checks"]]],
    })
