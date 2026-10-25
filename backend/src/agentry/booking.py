"""Booking service shared by every agent (chat, receptionist, speed-to-lead, reactivation).

Availability = staff working hours (org timezone) minus existing bookings, holidays and a lead time. Booking picks
the least-busy free staff member; a Postgres exclusion constraint makes double-booking impossible even when two
agents book the same slot at the same moment, in which case the caller gets alternatives instead.
"""
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentry.db import tenant_session
from agentry.events import emit
from agentry.leads import advance, resolve_contact

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
STEP_MIN = 30
LEAD_TIME = timedelta(hours=1)


@dataclass
class Slot:
    start: datetime
    end: datetime
    staff_id: str
    staff_name: str

    def label(self, tz: ZoneInfo) -> str:
        return self.start.astimezone(tz).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


class BookingError(Exception):
    def __init__(self, message: str, alternatives: list[str] | None = None):
        super().__init__(message)
        self.alternatives = alternatives or []


async def _context(conn, service_key: str) -> tuple[dict, ZoneInfo, list[dict], list[str]]:
    svc = (await conn.execute(text("select id, key, name, minutes from app.services where key = :k and active"),
                              {"k": service_key})).mappings().first()
    if not svc:
        raise BookingError(f"unknown service '{service_key}'")
    s = (await conn.execute(text("select timezone, profile from app.org_settings"))).mappings().one()
    staff = (await conn.execute(text("""select id, name, working_hours from app.staff
        where active and :k = any(service_keys) order by name"""), {"k": service_key})).mappings().all()
    return dict(svc), ZoneInfo(s["timezone"]), [dict(x) for x in staff], (s["profile"] or {}).get("holidays", [])


async def availability(org_id: str, service_key: str, start_day: date | None = None, days: int = 7,
                       limit: int = 40, now: datetime | None = None) -> tuple[list[Slot], ZoneInfo, dict]:
    async with tenant_session(org_id) as conn:
        svc, tz, staff, holidays = await _context(conn, service_key)
        now = now or datetime.now(tz)
        start_day = start_day or now.astimezone(tz).date()
        window_start = datetime.combine(start_day, time.min, tz)
        window_end = window_start + timedelta(days=days)
        busy = (await conn.execute(text("""select staff_id, starts_at, ends_at from app.bookings
            where status in ('booked','confirmed') and starts_at < :e and ends_at > :s"""),
            {"s": window_start, "e": window_end})).all()
    busy_by_staff: dict[str, list[tuple[datetime, datetime]]] = {}
    for b in busy:
        busy_by_staff.setdefault(str(b.staff_id), []).append((b.starts_at, b.ends_at))
    length = timedelta(minutes=svc["minutes"])
    slots: dict[datetime, Slot] = {}
    for d in range(days):
        day = start_day + timedelta(days=d)
        if day.isoformat() in holidays:
            continue
        for st in staff:
            for open_, close in st["working_hours"].get(DAYS[day.weekday()], []):
                t = datetime.combine(day, time.fromisoformat(open_), tz)
                end_of_day = datetime.combine(day, time.fromisoformat(close), tz)
                while t + length <= end_of_day:
                    clash = any(t < e and t + length > s for s, e in busy_by_staff.get(str(st["id"]), []))
                    if t >= now + LEAD_TIME and not clash and t not in slots:
                        slots[t] = Slot(t, t + length, str(st["id"]), st["name"])
                    t += timedelta(minutes=STEP_MIN)
    ordered = [slots[k] for k in sorted(slots)]
    return ordered[:limit], tz, svc


async def book(org_id: str, *, service_key: str, start: datetime, name: str, phone: str | None = None,
               email: str | None = None, source: str, conversation_id: str | None = None,
               lead_id: str | None = None) -> dict:
    if start.tzinfo is None:
        raise BookingError("start time needs a timezone")
    slots, tz, svc = await availability(org_id, service_key, start.astimezone(ZoneInfo("UTC")).date() - timedelta(days=1),
                                        days=3, limit=500)
    matching = [s for s in slots if s.start == start]
    if not matching:
        raise BookingError("that time is not available", [s.label(tz) for s in slots if s.start > start][:3])
    async with tenant_session(org_id) as conn:
        # Least-busy free staff member that day.
        counts = dict((await conn.execute(text("""select staff_id::text, count(*) from app.bookings
            where status in ('booked','confirmed') and starts_at::date = cast(:d as date) group by 1"""),
            {"d": start.date()})).all())
        candidates = sorted({s.staff_id: s for s in slots if s.start == start}.values(), key=lambda s: counts.get(s.staff_id, 0))
        contact_id = await resolve_contact(conn, org_id, name=name, phone=phone, email=email, source=source)
        booking = None
        for cand in candidates:
            try:
                async with conn.begin_nested():
                    booking = (await conn.execute(text("""
                        insert into app.bookings (org_id, staff_id, service_id, contact_id, lead_id, starts_at, ends_at, source, conversation_id)
                        values (:o, :st, :sv, :c, :l, :s, :e, :src, :conv) returning id"""),
                        {"o": org_id, "st": cand.staff_id, "sv": svc["id"], "c": contact_id, "l": lead_id,
                         "s": cand.start, "e": cand.end, "src": source, "conv": conversation_id})).scalar_one()
                staff_name = cand.staff_name
                break
            except IntegrityError:
                continue  # someone else just took this staff member's slot: try the next one
        if booking is None:
            raise BookingError("that slot was just taken", [s.label(tz) for s in slots if s.start > start][:3])
        if lead_id:
            await advance(conn, lead_id, "booked")
        # A booking ends every outbound sequence for this person (reactivation, cold email): they're in.
        await conn.execute(text("""update app.sequence_enrollments e set status = 'completed', stop_reason = 'booked', updated_at = now()
            from app.sequences s where s.id = e.sequence_id and e.contact_id = :c and s.automation_key in ('lead_reactivation', 'cold_email')
            and e.status in ('active','paused')"""), {"c": contact_id})
        if conversation_id:
            await conn.execute(text("update app.conversations set contact_id = :c where id = :conv"),
                               {"c": contact_id, "conv": conversation_id})
        await emit(conn, org_id, "booking.created", {"booking_id": str(booking), "source": source,
                                                     "service": service_key, "starts_at": start.isoformat()})
    return {"booking_id": str(booking), "service": svc["name"], "staff": staff_name,
            "when": start.astimezone(tz).strftime("%A %d %B at %I:%M %p").replace(" 0", " "),
            "starts_at": start.isoformat(), "contact_id": str(contact_id)}


async def set_catalog(org_id: str, services: list[dict], staff: list[dict]) -> None:
    """Replace an organisation's services and staff (onboarding, packs, Demo Studio)."""
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.services set active = false"))
        for s in services:
            await conn.execute(text("""insert into app.services (org_id, key, name, minutes, price) values (:o, :k, :n, :m, :p)
                on conflict (org_id, key) do update set name = excluded.name, minutes = excluded.minutes,
                price = excluded.price, active = true"""),
                {"o": org_id, "k": s["key"], "n": s["name"], "m": s["minutes"], "p": s.get("price")})
        await conn.execute(text("update app.staff set active = false"))
        for st in staff:
            await conn.execute(text("""insert into app.staff (org_id, name, email, service_keys, working_hours)
                values (:o, :n, :e, :k, cast(:h as jsonb))"""),
                {"o": org_id, "n": st["name"], "e": st.get("email"), "k": st["services"], "h": json.dumps(st["hours"])})
