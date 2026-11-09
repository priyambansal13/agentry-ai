"""Booking service: availability, holidays, least-busy assignment, no double-booking under concurrency."""
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from agentry.booking import BookingError, availability, book
from agentry.db import tenant_session

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 11, 2)  # a Monday after the seeded holidays (8-9 Nov are holidays)
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=IST)


def upcoming(weekday: int) -> date:
    """The next such weekday that is still ahead (bookings can't be in the past) and after the seeded 8-9 Nov holidays."""
    d = max(datetime.now(IST).date() + timedelta(days=1), date(2026, 11, 10))
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


@pytest.fixture
async def clean_bookings(orgs):
    yield
    async with tenant_session(orgs["smilecraft"]) as conn:
        await conn.execute(text("delete from app.bookings where source = 'test'"))
        await conn.execute(text("delete from app.contacts where source = 'test'"))


async def test_availability_follows_hours_and_holidays(orgs):
    slots, _tz, svc = await availability(orgs["smilecraft"], "consult", MONDAY, days=1, limit=500, now=NOW)
    assert svc["minutes"] == 30
    assert slots[0].start == datetime(2026, 11, 2, 10, 0, tzinfo=IST)
    assert slots[-1].end <= datetime(2026, 11, 2, 20, 0, tzinfo=IST)
    sunday, _, _ = await availability(orgs["smilecraft"], "consult", MONDAY - timedelta(days=1), days=1, now=NOW)
    assert sunday == []  # closed on Sundays
    holiday, _, _ = await availability(orgs["smilecraft"], "consult", date(2026, 11, 9), days=1, now=NOW)
    assert holiday == []  # clinic holiday


async def test_cleaning_only_offered_by_staff_who_do_it(orgs):
    slots, _, _ = await availability(orgs["smilecraft"], "cleaning", MONDAY, days=1, limit=500, now=NOW)
    assert {s.staff_name for s in slots} <= {"Dr. Amit Desai", "Sneha Patil (hygienist)"}


async def test_booking_takes_the_slot_away(orgs, clean_bookings):
    d = upcoming(1)
    start = datetime(d.year, d.month, d.day, 18, 0, tzinfo=IST)
    r = await book(orgs["smilecraft"], service_key="cleaning", start=start, name="Test Patient", phone="+91-90000-99901",
                   source="test")
    assert r["when"].startswith(f"Tuesday {d.day} {d:%B} at 6:00")
    slots, _, _ = await availability(orgs["smilecraft"], "cleaning", start.date(), days=1, limit=500, now=NOW)
    takers = [s.staff_name for s in slots if s.start == start]
    assert r["staff"] not in takers  # that person is busy now; the other cleaner may still be free


async def test_unavailable_time_offers_alternatives(orgs):
    d = upcoming(6)  # the next Sunday (closed), always in the future so there are alternatives to offer
    with pytest.raises(BookingError) as e:
        await book(orgs["smilecraft"], service_key="consult", start=datetime(d.year, d.month, d.day, 11, 0, tzinfo=IST),
                   name="X", source="test")
    assert e.value.alternatives


async def test_concurrent_bookings_never_double_book(orgs, clean_bookings):
    """Three agents grab the same slot at once; only as many succeed as there are free staff."""
    d = upcoming(2)
    start = datetime(d.year, d.month, d.day, 11, 0, tzinfo=IST)
    slots, _, _ = await availability(orgs["smilecraft"], "implant", start.date(), days=1, limit=500, now=NOW)
    free_staff = len({s.staff_id for s in slots if s.start == start})
    results = await asyncio.gather(*[
        book(orgs["smilecraft"], service_key="implant", start=start, name=f"P{i}", phone=f"+91-90000-9990{i}", source="test")
        for i in range(3)], return_exceptions=True)
    ok = [r for r in results if isinstance(r, dict)]
    assert len(ok) == free_staff == 1  # only Dr. Kulkarni does implants
    assert all(isinstance(r, BookingError) for r in results if not isinstance(r, dict))
