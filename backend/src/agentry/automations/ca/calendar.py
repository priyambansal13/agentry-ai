"""Compliance calendar (CA Firm pack): every client's due dates, on the board ahead of time, with reminders.

    rules      Indian due dates by what the client's profile says applies to them: GSTR-1 / GSTR-3B (monthly or QRMP),
               TDS payment and quarterly returns, PF / ESI, advance tax instalments, ITR (31 Jul, or 31 Oct with audit),
               tax audit report, GSTR-9, ROC AOC-4 / MGT-7, DIR-3 KYC
    ahead      a daily run puts each due date that's within N days on the filing board (a card with its due date; never
               twice), whether or not the board is switched on, so the calendar page can show it
    reminders  clients are reminded N days before (settings: 7 and 2) of what they need to do or send
Statutory dates move when the government extends them: the firm edits a card's due date and that's what counts.
"""
import json
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.automations.ca import core
from agentry.db import tenant_session


class CalendarConfig(BaseModel):
    days_ahead: int = Field(30, ge=7, le=90, title="Put due dates on the board this many days ahead", json_schema_extra={"editable_by": "client"})
    remind_clients: bool = Field(True, title="Remind clients before their due dates", json_schema_extra={"editable_by": "client"})
    remind_days: list[int] = Field(default_factory=lambda: [7, 2], title="Remind clients this many days before",
                                   json_schema_extra={"editable_by": "client"})
    whatsapp_template: str | None = Field(None, title="Approved WhatsApp template for reminders",
                                          description="One parameter: the reminder text.", json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="ca_compliance_calendar", name="Compliance calendar",
    description="GST, TDS, advance tax, ROC and PF/ESI dates per client, with reminders.",
    config_model=CalendarConfig, metrics=(),
))

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ASK = {
    "gstr1": "Please send this month's sales invoices if you haven't already.",
    "gstr3b": "Please send your sales and purchase bills if you haven't already, so we can file on time.",
    "gstr9": "We'll prepare the annual GST return from the year's filings; we'll ask if anything is missing.",
    "tds_payment": "Please pay the TDS deducted last month by then (we can share the challan details).",
    "tds_24q": "Please send the quarter's salary and TDS details if you haven't already.",
    "tds_26q": "Please send the quarter's vendor payments with TDS if you haven't already.",
    "pf_esi": "Please share this month's salary sheet so PF / ESI can be paid on time.",
    "advance_tax": "Please pay the advance tax instalment by then; we'll share the amount.",
    "itr": "Please send your documents for the return if you haven't already.",
    "tax_audit": "Please share the books and trial balance for the audit if you haven't already.",
    "roc_aoc4": "Please make sure the financials are signed and the AGM date is fixed.",
    "roc_mgt7": "We'll need the shareholding and director details confirmed.",
    "dir3_kyc": "We'll need the OTP sent to your mobile and email to complete the KYC.",
}


def _fy(d: date) -> int:
    """Financial year start: FY 2026-27 -> 2026."""
    return d.year if d.month >= 4 else d.year - 1


def _fyl(y: int) -> str:
    return f"{y}-{str(y + 1)[2:]}"


def _add_month(y: int, m: int, n: int = 1) -> tuple[int, int]:
    m += n
    return y + (m - 1) // 12, (m - 1) % 12 + 1


def _day(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, monthrange(y, m)[1]))


def deadlines(client_kind: str, profile: dict, start: date, end: date) -> list[dict]:
    """Every due date in [start, end] that applies to this client: {kind, period, due_on, title}."""
    p, out = profile or {}, []

    def add(kind: str, period: str, due: date, title: str | None = None) -> None:
        if start <= due <= end:
            out.append({"kind": kind, "period": period, "due_on": due, "title": title or f"{core.KINDS[kind]} {period}"})

    # month by month (the period is the month before the due date)
    y, m = _add_month(start.year, start.month, -2)
    while date(y, m, 1) <= end:
        ny, nm = _add_month(y, m)
        label = f"{y}-{m:02d}"
        human = f"{MONTHS[m - 1]} {y}"
        if p.get("gst") and not p.get("gst_qrmp"):
            add("gstr1", label, _day(ny, nm, 11), f"GSTR-1 {human}")
            add("gstr3b", label, _day(ny, nm, 20), f"GSTR-3B {human}")
        if p.get("gst") and p.get("gst_qrmp") and m in (6, 9, 12, 3):
            q = {6: 1, 9: 2, 12: 3, 3: 4}[m]
            fy = _fyl(y if m >= 4 else y - 1)
            add("gstr1", f"Q{q} FY {fy}", _day(ny, nm, 13), f"GSTR-1 Q{q} FY {fy}")
            add("gstr3b", f"Q{q} FY {fy}", _day(ny, nm, 22), f"GSTR-3B Q{q} FY {fy}")
        if p.get("tds"):
            add("tds_payment", label, _day(ny, nm, 30 if m == 3 else 7), f"TDS payment {human}")
        if p.get("pf_esi"):
            add("pf_esi", label, _day(ny, nm, 15), f"PF / ESI {human}")
        y, m = ny, nm
    # financial-year dates
    for fy in range(_fy(start) - 1, _fy(end) + 1):
        if p.get("tds"):
            for q, (yy, mm, dd) in enumerate([(fy, 7, 31), (fy, 10, 31), (fy + 1, 1, 31), (fy + 1, 5, 31)], start=1):
                add("tds_26q", f"Q{q} FY {_fyl(fy)}", date(yy, mm, dd))
                if p.get("pf_esi") or client_kind in ("company", "llp", "firm"):
                    add("tds_24q", f"Q{q} FY {_fyl(fy)}", date(yy, mm, dd))
        if p.get("advance_tax") or p.get("business"):
            for n, (mm, pct) in enumerate([(6, 15), (9, 45), (12, 75), (3, 100)], start=1):
                add("advance_tax", f"FY {_fyl(fy)} #{n}", date(fy + (mm == 3), mm, 15), f"Advance tax FY {_fyl(fy)}: instalment {n} ({pct}%)")
        ay = _fyl(fy + 1)
        audit = p.get("audit") or client_kind in ("company",)
        add("itr", f"AY {ay}", date(fy + 1, 10, 31) if audit else date(fy + 1, 7, 31))
        if p.get("audit"):
            add("tax_audit", f"AY {ay}", date(fy + 1, 9, 30))
        if p.get("gst"):
            add("gstr9", f"FY {_fyl(fy)}", date(fy + 1, 12, 31))
        if client_kind in ("company", "llp") or p.get("company_roc"):
            add("roc_aoc4", f"FY {_fyl(fy)}", date(fy + 1, 10, 30),
                f"{'ROC AOC-4' if client_kind == 'company' else 'LLP Form 8'} FY {_fyl(fy)}")
            add("roc_mgt7", f"FY {_fyl(fy)}", date(fy + 1, 11, 29) if client_kind == "company" else date(fy + 1, 5, 30),
                f"{'ROC MGT-7' if client_kind == 'company' else 'LLP Form 11'} FY {_fyl(fy)}")
            if client_kind == "company":
                add("dir3_kyc", f"FY {_fyl(fy + 1)}", date(fy + 1, 9, 30))
    return sorted(out, key=lambda d: d["due_on"])


async def put_on_board(conn: AsyncConnection, org_id: str, today: date, days_ahead: int) -> int:
    from agentry.automations.ca.tracker import create_filing
    clients = (await conn.execute(text("select id::text, kind, profile from app.ca_clients"))).mappings().all()
    made = 0
    for c in clients:
        for d in deadlines(c["kind"], c["profile"], today, today + timedelta(days=days_ahead)):
            if await create_filing(conn, org_id, c["id"], kind=d["kind"], period=d["period"], due_on=d["due_on"], source="calendar", title=d["title"]):
                made += 1
    return made


def reminder(title: str, due: date, kind: str, firm: str, name: str | None) -> str:
    first = (name or "").split()[0] if name else ""
    return (f"{'Hi ' + first + ',' if first else 'Hello,'} a reminder from {firm}: {title} is due on {due:%d %b %Y}. "
            f"{ASK.get(kind, '')}".strip() + "\n\nReply here if you have a question.")


async def daily(org_id: str, today: date | None = None) -> int:
    """Due dates onto the board, then client reminders. Returns the number of new cards."""
    from agentry.outbound import reach_contact
    today = today or datetime.now(UTC).date()
    async with tenant_session(org_id) as conn:
        cfg = await core.enabled(conn, "ca_compliance_calendar")
        if not cfg:
            return 0
        made = await put_on_board(conn, org_id, today, int(cfg.get("days_ahead", 30)))
        if not cfg.get("remind_clients", True) or cfg["status"] != "live":
            return made
        firm = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        offsets = sorted({int(x) for x in cfg.get("remind_days") or [] if 0 <= int(x) <= 60}, reverse=True)
        rows = (await conn.execute(text("""select f.id::text, f.kind, f.title, f.due_on, f.data, f.client_id::text, c.name from app.ca_filings f
            join app.ca_clients c on c.id = f.client_id where f.status not in ('filed','verified') and f.due_on >= :t and f.due_on <= :u"""),
            {"t": today, "u": today + timedelta(days=max(offsets or [0]))})).mappings().all()
        for r in rows:
            left = (r["due_on"] - today).days
            due_offset = min((o for o in offsets if left <= o), default=None)
            sent = set((r["data"] or {}).get("reminded", []))
            if due_offset is None or due_offset in sent or (sent and min(sent) <= due_offset):
                continue
            res = await reach_contact(conn, org_id, await core.who(conn, r["client_id"]), reminder(r["title"], r["due_on"], r["kind"], firm, r["name"]),
                                      agent="ca_compliance_calendar", subject=f"{r['title']} is due on {r['due_on']:%d %b}",
                                      email_ref=f"ca-due:{r['id']}", wa_template=cfg.get("whatsapp_template"),
                                      wa_params=[f"{r['title']} is due on {r['due_on']:%d %b %Y}"])
            if res["status"] in ("sent", "recorded"):
                await conn.execute(text("""update app.ca_filings set data = jsonb_set(data, '{reminded}', cast(:r as jsonb)) where id = cast(:i as uuid)"""),
                                   {"r": json.dumps(sorted(sent | {due_offset})), "i": r["id"]})
    return made


async def upcoming(conn: AsyncConnection, today: date, days: int = 60) -> list[dict]:
    rows = (await conn.execute(text("""select f.id::text, f.client_id::text, c.name as client, f.kind, f.period, f.title, f.due_on, f.status,
        f.data->'reminded' as reminded from app.ca_filings f join app.ca_clients c on c.id = f.client_id
        where f.due_on is not null and f.due_on <= :u and (f.status not in ('filed','verified') or f.due_on >= :t)
        order by f.due_on, c.name limit 500"""), {"t": today, "u": today + timedelta(days=days)})).mappings().all()
    return [dict(r) | {"overdue": r["due_on"] < today and r["status"] not in ("filed", "verified")} for r in rows]
