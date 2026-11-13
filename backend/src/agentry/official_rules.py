"""Official figures the agents work with (tax slabs, TDS rates and thresholds, audit limits, presumptive rates, festival
dates), each with the law or source it comes from, and the changes to them approved by Agentry staff.

    registry  RULES below: the value the code was written with (FY 2025-26 / AY 2026-27 law, the 2026-27 festival calendar),
              what fixes it, and the words a source must use when it changes it
    changes   app.rule_updates: a change found by the daily check of official sources (automations/ca/due_dates.py runs
              both checks) or entered by staff from the notification; approved in HQ → Official updates
    reading   get(key) gives the value in force: the approved change, else the registry's. The values in force are held
              in memory and reloaded at most every two minutes (fresh(), before the agents' API calls and jobs), and at
              once in the process that approves a change.
Agents never see a proposed change: only an approved one.
"""
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text

from agentry.db import system_session

IT = ("Income-tax law (Finance Act 2025 rates, AY 2026-27)", "https://www.incometax.gov.in/iec/foportal/")
IT_TDS = ("Income-tax law: TDS rates and thresholds (FY 2025-26)", "https://www.incometax.gov.in/iec/foportal/")
IT_AUDIT = ("Income-tax law: disallowances and penalties", "https://www.incometax.gov.in/iec/foportal/")
BASE_FY = 2025  # the figures above are the law for FY 2025-26 (AY 2026-27): a change must apply from a later year
RBI = ("Reserve Bank of India: bank rate", "https://www.rbi.org.in/")
MSMED = ("MSMED Act, 2006 (sections 15 and 16)", "https://samadhaan.msme.gov.in/")
GST = ("GST law: CGST Rules and CBIC notifications (GSTR-1)", "https://cbic-gst.gov.in/")
DEP_IT = ("Income-tax law: depreciation (section 32 and Appendix I rates; carried into the Income-tax Act, 2025)", "https://www.incometax.gov.in/iec/foportal/")
DEP_CO = ("Companies Act, 2013: Schedule II (useful lives, residual value)", "https://www.mca.gov.in/")
FEST = ("Festival dates (government holiday lists and the published panchang)", "https://dopt.gov.in/")


@dataclass(frozen=True)
class Rule:
    agent: str               # which agent uses it
    label: str
    kind: str                # amount (₹) / rate (fraction) / months / days / date / slabs
    default: object
    source: tuple[str, str]  # (what fixes it, official site)
    words: str = ""          # a source's sentence about it must match this (stops a change landing on the wrong figure)
    tags: tuple[str, ...] = field(default_factory=tuple)


RULES: dict[str, Rule] = {
    # ---------- ITR preparation ----------
    "itr.new_slabs": Rule("ITR preparation", "New regime slabs (upper limit, rate)", "slabs",
                          [[400000, 0], [800000, 0.05], [1200000, 0.10], [1600000, 0.15], [2000000, 0.20], [2400000, 0.25], [None, 0.30]], IT,
                          r"slab|new (tax )?regime|115bac"),
    "itr.std_new": Rule("ITR preparation", "Standard deduction, new regime", "amount", 75000, IT, r"standard deduction"),
    "itr.std_old": Rule("ITR preparation", "Standard deduction, old regime", "amount", 50000, IT, r"standard deduction"),
    "itr.rebate_limit_new": Rule("ITR preparation", "Rebate 87A income limit, new regime", "amount", 1200000, IT, r"87a|rebate"),
    "itr.rebate_max_new": Rule("ITR preparation", "Rebate 87A maximum, new regime", "amount", 60000, IT, r"87a|rebate"),
    "itr.rebate_limit_old": Rule("ITR preparation", "Rebate 87A income limit, old regime", "amount", 500000, IT, r"87a|rebate"),
    "itr.rebate_max_old": Rule("ITR preparation", "Rebate 87A maximum, old regime", "amount", 12500, IT, r"87a|rebate"),
    "itr.ded_80c": Rule("ITR preparation", "80C limit", "amount", 150000, IT, r"80c"),
    "itr.ded_80ccd1b": Rule("ITR preparation", "80CCD(1B) own NPS limit", "amount", 50000, IT, r"80ccd"),
    "itr.home_loan": Rule("ITR preparation", "Home loan interest, self-occupied (old regime)", "amount", 200000, IT, r"24\(b\)|interest on (housing|home) loan|self.occupied"),
    "itr.ltcg_exempt": Rule("ITR preparation", "112A long-term gains exempt each year", "amount", 125000, IT, r"112a|long.term capital gain"),
    "itr.rate_111a": Rule("ITR preparation", "Short-term gains on listed shares / equity funds (111A)", "rate", 0.20, IT, r"111a|short.term capital gain"),
    "itr.rate_112a": Rule("ITR preparation", "Long-term gains on listed shares / equity funds (112A)", "rate", 0.125, IT, r"112a|long.term capital gain"),
    "itr.cess": Rule("ITR preparation", "Health and education cess", "rate", 0.04, IT, r"cess"),
    # ---------- capital gains ----------
    "cg.equity_long_months": Rule("Capital gains", "Listed shares / equity funds are long-term after (months)", "months", 12, IT, r"long.term|holding period"),
    "cg.other_long_months": Rule("Capital gains", "Other assets are long-term after (months)", "months", 24, IT, r"long.term|holding period"),
    "cg.rate_change": Rule("Capital gains", "Date the current capital gains rates started", "date", "2024-07-23", IT, r"capital gain"),
    # ---------- TDS returns ----------
    "tds.no_pan_rate": Rule("TDS returns", "TDS without a valid PAN (206AA)", "rate", 0.20, IT_TDS, r"206aa|without pan|pan"),
    "tds.late_deduction": Rule("TDS returns", "Interest for deducting late, per month", "rate", 0.01, IT_TDS, r"201\(1a\)|interest"),
    "tds.late_deposit": Rule("TDS returns", "Interest for depositing late, per month", "rate", 0.015, IT_TDS, r"201\(1a\)|interest"),
    "tds.194C.yearly": Rule("TDS returns", "194C contractors: yearly total that needs TDS", "amount", 100000, IT_TDS, r"194c|contract"),
    # ---------- tax audit 3CD ----------
    "audit.cash_limit": Rule("Tax audit (3CD)", "40A(3): cash paid to one person in a day", "amount", 10000, IT_AUDIT, r"40a\(3\)|cash payment"),
    "audit.cash_limit_transport": Rule("Tax audit (3CD)", "40A(3): cash a day to a transporter", "amount", 35000, IT_AUDIT, r"40a\(3\)|transport"),
    "audit.loan_cash": Rule("Tax audit (3CD)", "269SS / 269T: cash loan limit", "amount", 20000, IT_AUDIT, r"269ss|269t|loan"),
    "audit.cash_receipt": Rule("Tax audit (3CD)", "269ST: cash received from one person in a day", "amount", 200000, IT_AUDIT, r"269st|cash receipt"),
    "audit.msme_days": Rule("Tax audit (3CD)", "43B(h): MSME payment limit (days, with an agreement)", "days", 45, IT_AUDIT, r"43b\(h\)|msme|micro"),
    "audit.tds_disallow": Rule("Tax audit (3CD)", "40(a)(ia): share disallowed when TDS isn't deducted", "rate", 0.30, IT_AUDIT, r"40\(a\)\(ia\)|disallow"),
    # ---------- invoice follow-up: MSME payments ----------
    "msme.bank_rate": Rule("Invoice follow-up", "RBI bank rate (MSME interest is three times this)", "rate", 0.0575, RBI, r"bank rate"),
    "msme.max_days": Rule("Invoice follow-up", "Longest credit a buyer can agree with a micro / small supplier (days)", "days", 45, MSMED,
                          r"45 days|forty.five days|msme|micro"),
    "msme.tax_section_2025": Rule("Invoice follow-up", "Buyer's deduction only when paid: Income-tax Act, 2025 (tax year 2026-27 on)", "text",
                                  "section 37(2)(g) of the Income-tax Act, 2025", ("Income-tax Act, 2025: section 37",
                                  "https://wm.incometaxindia.gov.in/w/section-37-176"), r"micro|small enterprise|msme"),
    "msme.tax_section_1961": Rule("Invoice follow-up", "Buyer's deduction only when paid: Income-tax Act, 1961 (up to FY 2025-26)", "text",
                                  "section 43B(h) of the Income-tax Act, 1961", IT, r"43b|micro|small enterprise|msme"),
    "msme.default_days": Rule("Invoice follow-up", "Payment due without a written agreement (days)", "days", 15, MSMED, r"15 days|fifteen days|msme|micro"),
    # ---------- bank statements ----------
    "bank.sft_cash": Rule("Bank statement classifier", "Cash deposits reported to the department (SFT) above, a year", "amount", 1000000, IT, r"sft|cash deposit|specified financial"),
    "bank.44ad_digital": Rule("Bank statement classifier", "44AD presumptive income on digital receipts", "rate", 0.06, IT, r"44ad"),
    "bank.44ad_cash": Rule("Bank statement classifier", "44AD presumptive income on cash receipts", "rate", 0.08, IT, r"44ad"),
    "bank.44ada": Rule("Bank statement classifier", "44ADA presumptive income for professionals", "rate", 0.50, IT, r"44ada"),
    # ---------- GSTR-1 ----------
    "gst.b2cl_limit": Rule("GSTR-1 preparation", "B2CL: inter-state invoice to an unregistered buyer above (else B2CS)", "amount", 100000, GST,
                           r"b2cl|b2c \(large\)|unregistered|inter-state"),
    # ---------- Depreciation ----------
    "dep.bld_res": Rule("Depreciation", "WDV rate: residential buildings", "rate", 0.05, DEP_IT, r"residential|building"),
    "dep.bld": Rule("Depreciation", "WDV rate: other buildings", "rate", 0.10, DEP_IT, r"building"),
    "dep.bld_temp": Rule("Depreciation", "WDV rate: temporary structures", "rate", 0.40, DEP_IT, r"temporary|purely temporary"),
    "dep.furniture": Rule("Depreciation", "WDV rate: furniture and fittings", "rate", 0.10, DEP_IT, r"furniture|fittings"),
    "dep.pm": Rule("Depreciation", "WDV rate: plant and machinery (general, incl. cars)", "rate", 0.15, DEP_IT, r"plant and machinery|machinery|motor car"),
    "dep.vehicle_hire": Rule("Depreciation", "WDV rate: buses, lorries, taxis in a hiring business", "rate", 0.30, DEP_IT, r"lorr|bus|taxi|hire"),
    "dep.computer": Rule("Depreciation", "WDV rate: computers and software", "rate", 0.40, DEP_IT, r"computer|software"),
    "dep.energy": Rule("Depreciation", "WDV rate: energy-saving and renewable energy devices", "rate", 0.40, DEP_IT, r"energy|renewable|pollution"),
    "dep.intangible": Rule("Depreciation", "WDV rate: know-how, patents, copyrights, trademarks, licences", "rate", 0.25, DEP_IT,
                           r"intangible|patent|copyright|trade ?mark|know-how|licen"),
    "dep.half_days": Rule("Depreciation", "Half the rate when put to use for less than (days)", "days", 180, DEP_IT, r"180 days|half|put to use"),
    "dep.residual": Rule("Depreciation", "Residual value, books (share of cost)", "rate", 0.05, DEP_CO, r"residual value|schedule ii"),
    "dep.tax_company": Rule("Depreciation", "Tax rate for deferred tax: company (22% + 10% surcharge + 4% cess, section 115BAA)", "rate", 0.25168, IT,
                            r"115baa|domestic compan|corporate tax"),
    "dep.tax_firm": Rule("Depreciation", "Tax rate for deferred tax: firm / LLP (30% + 4% cess)", "rate", 0.312, IT, r"firm|llp|partnership"),
}

# TDS: section -> (rate for individuals / HUF, rate for others, threshold, label)
_TDS = {
    "194A": (0.10, 0.10, 10000, "Interest (other than on securities)"), "194C": (0.01, 0.02, 30000, "Contractors"),
    "194H": (0.02, 0.02, 20000, "Commission / brokerage"), "194I(a)": (0.02, 0.02, 50000, "Rent: plant & machinery (₹50,000 a month)"),
    "194I(b)": (0.10, 0.10, 50000, "Rent: land & building (₹50,000 a month)"), "194J(a)": (0.02, 0.02, 50000, "Fees for technical services"),
    "194J(b)": (0.10, 0.10, 50000, "Professional fees"), "194Q": (0.001, 0.001, 5000000, "Purchase of goods (above ₹50 lakh from a seller)"),
    "194-IA": (0.01, 0.01, 5000000, "Purchase of immovable property"), "194T": (0.10, 0.10, 20000, "Partners' salary, commission, interest"),
    "194D": (0.02, 0.02, 20000, "Insurance commission"),
}
for _s, (_ri, _ro, _th, _l) in _TDS.items():
    _w = re.escape(_s.split("(")[0].lower()).replace("\\-", "-?")  # "194-IA" or "194IA"; "194J(b)" -> 194j
    RULES[f"tds.{_s}.rate_individual"] = Rule("TDS returns", f"{_s} {_l}: rate for individuals / HUF", "rate", _ri, IT_TDS, _w)
    RULES[f"tds.{_s}.rate_other"] = Rule("TDS returns", f"{_s} {_l}: rate for others", "rate", _ro, IT_TDS, _w)
    RULES[f"tds.{_s}.threshold"] = Rule("TDS returns", f"{_s} {_l}: threshold", "amount", _th, IT_TDS, _w)
TDS_LABELS = {s: v[3] for s, v in _TDS.items()}


def _festivals() -> None:
    from agentry.automations.festivals import FESTIVALS
    from agentry.automations.festivals import FIXED as fixed
    for key, (name, dates, _tags) in FESTIVALS.items():
        if key in fixed:
            continue
        years = sorted(dates)
        for y in [*years, years[-1] + 1]:  # the year after the last known one: found by the check when it's announced
            RULES[f"festival.{key}.{y}"] = Rule("Festival campaigns", f"{name} {y}", "date", f"{y}-{dates[y]}" if y in dates else None, FEST,
                                                re.escape(name.split(" /")[0].split(" begins")[0].lower()), ("festival",))


# ---------- the values in force ----------

_cache: dict[str, object] = {}
_loaded = 0.0
_fest = False
TTL = 120


def _ensure() -> None:
    global _fest
    if not _fest:
        _fest = True
        _festivals()


def get(key: str) -> object:
    _ensure()
    r = RULES.get(key)
    return _cache.get(key, r.default if r else None)


def num(key: str) -> float:
    v = get(key)
    return float(v) if v is not None else 0.0


async def refresh() -> None:
    global _loaded
    async with system_session() as conn:
        rows = (await conn.execute(text("""select distinct on (key) key, new_value from app.rule_updates where status = 'active'
            order by key, decided_at desc"""))).all()
    _cache.clear()
    _cache.update({k: v for k, v in rows})
    _loaded = time.monotonic()


async def fresh() -> None:
    """Reload the values in force when they're more than two minutes old (a FastAPI dependency and a job's first step)."""
    if time.monotonic() - _loaded > TTL:
        await refresh()


def tds_rates() -> dict[str, tuple[float | None, float | None, float, str]]:
    """The TDS table in force: section -> (rate individuals, rate others, threshold, label); salary has no rate check."""
    out: dict[str, tuple[float | None, float | None, float, str]] = {"192": (None, None, 0, "Salary")}
    for s, label in TDS_LABELS.items():
        out[s] = (num(f"tds.{s}.rate_individual"), num(f"tds.{s}.rate_other"), num(f"tds.{s}.threshold"), label)
    return out


def festival_date(key: str, year: int) -> date | None:
    v = get(f"festival.{key}.{year}")
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def show(kind: str, v: object) -> str:
    """How a value reads to a person."""
    if v is None:
        return "not known yet"
    if kind == "amount":
        from agentry.automations.ca.core import inr
        return inr(float(v))  # type: ignore[arg-type]  # Indian grouping: ₹50,00,000
    if kind == "rate":
        return f"{float(v) * 100:g}%"  # type: ignore[arg-type]
    if kind in ("months", "days"):
        return f"{v} {kind}"
    if kind == "date":
        return date.fromisoformat(str(v)).strftime("%d %b %Y")
    if kind == "text":
        return str(v)
    if kind == "slabs":
        lo, parts = 0, []
        for up, rate in v:  # type: ignore[attr-defined]
            from agentry.automations.ca.core import inr
            parts.append(f"{'above ' + inr(lo) if up is None else inr(lo) + '–' + inr(up)}: {rate * 100:g}%")
            lo = up or lo
        return "; ".join(parts)
    return json.dumps(v)


def listing() -> list[dict]:
    _ensure()
    return [{"key": k, "agent": r.agent, "label": r.label, "kind": r.kind, "value": get(k), "shown": show(r.kind, get(k)),
             "standard": r.default, "changed": k in _cache, "source": r.source[0], "url": r.source[1]} for k, r in RULES.items()]
