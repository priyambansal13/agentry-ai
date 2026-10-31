"""Appointment Concierge: the evening-before reminder, "1" confirms, "2" offers three times and rebooks the one picked,
a cancelled slot goes to the waitlist (first yes wins), a no-show gets new times, recalls go out once, and every
message the business starts goes through governance."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from conftest import expect
from sqlalchemy import text

from agentry.automations import appointment_concierge as ac
from agentry.booking import book, set_catalog
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
IST = ZoneInfo("Asia/Kolkata")
HOURS = {d: [["09:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


async def clinic(team_org):
    oid, h = await team_org(["appointment_concierge"])
    await set_catalog(oid, [{"key": "cleaning", "name": "Cleaning", "minutes": 30}], [{"name": "Dr. Rao", "services": ["cleaning"], "hours": HOURS}])
    return oid, h


def at(days: int, hour: int) -> datetime:
    d = datetime.now(IST).date() + timedelta(days=days)
    return datetime.combine(d, time(hour), IST)


async def patient(oid: str, start: datetime, name: str = "Meera Shah", email: str = "meera@patients.example") -> tuple[str, str]:
    """A booking plus the chat the patient replies from (their Telegram conversation)."""
    r = await book(oid, service_key="cleaning", start=start, name=name, email=email, source="test")
    conv = await chat(oid, r["contact_id"])
    return r["booking_id"], conv


async def chat(oid: str, contact_id: str) -> str:
    async with tenant_session(oid) as conn:
        return str((await conn.execute(text("""insert into app.conversations (org_id, channel, contact_id, subject, external_ref)
            values (:o, 'telegram', :k, 'Telegram', :r) returning id"""), {"o": oid, "k": contact_id, "r": f"tg:test-{contact_id}"})).scalar_one())


async def said(oid: str, contact_id: str | None = None) -> list[str]:
    """What the concierge sent, oldest first (no mailbox connected: email messages are recorded, not sent)."""
    async with tenant_session(oid) as conn:
        return list((await conn.execute(text("""select m.body from app.messages m join app.conversations c on c.id = m.conversation_id
            where m.direction = 'out' and m.metadata->>'sent_from' = 'appointment_concierge' and (cast(:k as uuid) is null or c.contact_id = cast(:k as uuid))
            order by m.created_at, m.id"""), {"k": contact_id})).scalars())


async def booking(oid: str, bid: str) -> dict:
    async with tenant_session(oid) as conn:
        return dict((await conn.execute(text("select * from app.bookings where id = cast(:i as uuid)"), {"i": bid})).mappings().one())


def test_reminder_is_the_evening_before_unless_too_late():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=IST).astimezone(UTC)
    starts = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    assert ac.reminder_time(starts, "Asia/Kolkata", 18, now) == datetime(2026, 11, 3, 18, 0, tzinfo=IST)
    late = datetime(2026, 11, 2, 19, 0, tzinfo=IST)
    assert ac.reminder_time(datetime(2026, 11, 3, 10, 0, tzinfo=IST), "Asia/Kolkata", 18, late) is None  # booked at 7 pm for tomorrow: no reminder


async def test_reminder_then_one_confirms(team_org):
    oid, _h = await clinic(team_org)
    bid, conv = await patient(oid, at(3, 11))
    assert await ac.appt_send(oid, bid, "reminder") == "recorded"
    assert (await said(oid))[-1].startswith("Hi Meera, a reminder: your Cleaning is ") and "Reply 1 to confirm or 2 to change" in (await said(oid))[-1]
    assert (await booking(oid, bid))["concierge"]["awaiting"] == "confirm"
    assert (await ac.handle_reply(oid, conv, "hello, what are your hours?"))["handled"] is False  # not an answer: the assistant takes it
    assert (await ac.handle_reply(oid, conv, "1"))["action"] == "confirmed"
    b = await booking(oid, bid)
    assert b["status"] == "confirmed" and b["concierge"]["awaiting"] is None
    assert (await said(oid))[-1].startswith("Thanks Meera, see you ")
    assert (await ac.handle_reply(oid, conv, "1"))["handled"] is False  # nothing waiting any more
    assert await ac.appt_send(oid, bid, "reminder") == "skipped"  # confirmed already: no second reminder


async def test_two_offers_three_times_and_rebooks_the_pick(team_org):
    oid, _h = await clinic(team_org)
    bid, conv = await patient(oid, at(3, 11))
    await ac.appt_send(oid, bid, "reminder")
    assert (await ac.handle_reply(oid, conv, "2"))["action"] == "offered_times"
    offer = await said(oid)
    assert "Which suits you?\nA) " in offer[-1] and "C) " in offer[-1] and "Reply A, B or C (or 0 to cancel)." in offer[-1]
    picked = datetime.fromisoformat((await booking(oid, bid))["concierge"]["offered"][1])
    r = await ac.handle_reply(oid, conv, "b")
    assert r["action"] == "rebooked"
    old, new = await booking(oid, bid), await booking(oid, r["booking_id"])
    assert old["status"] == "cancelled" and old["cancel_reason"] == "rescheduled" and old["concierge"]["rebooked_as"] == r["booking_id"]
    assert new["status"] == "confirmed" and new["starts_at"] == picked and new["contact_id"] == old["contact_id"]
    assert (await said(oid))[-1].startswith("You're booked: Cleaning, ")


async def test_cancelled_slot_goes_to_the_waitlist_first_yes_wins(client, team_org):
    oid, h = await clinic(team_org)
    bid, _conv = await patient(oid, at(4, 10))
    got = {r: (await client.post("/org/waitlist", headers=h[r], json={"name": f"W {r}", "email": f"w-{r}@patients.example", "service_key": "cleaning"})).status_code
           for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    assert (await client.post("/org/waitlist", headers=h["owner"], json={"name": "W owner", "email": "w-owner@patients.example",
                                                                        "service_key": "cleaning"})).status_code == 409
    assert (await client.post("/org/waitlist", headers=h["owner"], json={"name": "No way", "service_key": "cleaning"})).status_code == 422
    assert (await client.post(f"/org/bookings/{bid}/status", headers=h["viewer"], json={"status": "cancelled"})).status_code == 403
    assert (await client.post(f"/org/bookings/{bid}/status", headers=h["staff"], json={"status": "cancelled"})).status_code == 200
    async with tenant_session(oid) as conn:
        wl = (await conn.execute(text("""select w.id::text, w.status, w.contact_id::text, k.name from app.waitlist w join app.contacts k on k.id = w.contact_id
            order by w.created_at"""))).mappings().all()
        ev = (await conn.execute(text("select payload from app.events where type = 'booking.cancelled'"))).scalars().all()
    assert [w["status"] for w in wl] == ["offered", "offered", "offered", "waiting"]  # the first three are offered the slot
    assert ev == [{"booking_id": bid, "reason": "cancelled by the team"}]
    assert "a Cleaning slot just opened" in (await said(oid, wl[0]["contact_id"]))[-1]
    second, first = await chat(oid, wl[1]["contact_id"]), await chat(oid, wl[0]["contact_id"])
    r = await ac.handle_reply(oid, second, "yes please")
    assert r["action"] == "waitlist_booked" and (await booking(oid, r["booking_id"]))["starts_at"] == at(4, 10)
    assert (await said(oid, wl[1]["contact_id"]))[-1].startswith("It's yours: Cleaning, ")
    async with tenant_session(oid) as conn:
        assert [s for (s,) in (await conn.execute(text("select status from app.waitlist order by created_at"))).all()] == ["waiting", "booked", "waiting", "waiting"]
    assert (await ac.handle_reply(oid, first, "yes"))["handled"] is False  # too late: the offer was withdrawn, they stay on the list
    assert (await client.get("/org/calendar", headers=h["viewer"], params={"start": at(4, 10).date().isoformat(), "days": 1})).json()["waitlist"][0]["email"] is None


async def test_no_show_gets_new_times_and_tells_the_team(client, team_org):
    oid, h = await clinic(team_org)
    bid, conv = await patient(oid, at(2, 15))
    assert (await client.post(f"/org/bookings/{bid}/status", headers=h["staff"], json={"status": "no_show"})).status_code == 200
    assert (await said(oid))[-1] == "Hi Meera, we missed you today. Reply 1 and we'll find you a new time."
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.events where type = 'booking.no_show'"))).scalar_one() == 1
    assert (await ac.handle_reply(oid, conv, "1"))["action"] == "offered_times"
    r = await ac.handle_reply(oid, conv, "A")
    assert r["action"] == "rebooked" and (await booking(oid, bid))["status"] == "no_show"  # the missed visit stays a no-show
    assert (await client.post(f"/org/bookings/{bid}/status", headers=h["owner"], json={"status": "no_show"})).status_code == 200
    assert len([m for m in await said(oid) if "we missed you" in m]) == 1  # marking twice doesn't message twice


async def test_recall_after_months_once(team_org):
    oid, _h = await clinic(team_org)
    async with tenant_session(oid) as conn:
        ids = (await conn.execute(text("select (select id from app.staff where active) as st, (select id from app.services where key = 'cleaning') as sv"))).one()
        from agentry.leads import resolve_contact
        k = await resolve_contact(conn, oid, name="Old Patient", email="old@patients.example", source="test")
        for months, status in ((7, "showed"), (2, "showed"), (8, "no_show")):
            start = datetime.now(UTC) - timedelta(days=30 * months)
            await conn.execute(text("""insert into app.bookings (org_id, staff_id, service_id, contact_id, starts_at, ends_at, status, source)
                values (:o, :st, :sv, :k, :s, :e, :status, 'test')"""), {"o": oid, "st": ids.st, "sv": ids.sv, "k": k, "s": start,
                                                                          "e": start + timedelta(minutes=30), "status": status})
        k2 = await resolve_contact(conn, oid, name="Due Patient", email="due@patients.example", source="test")
        start = datetime.now(UTC) - timedelta(days=200)
        await conn.execute(text("""insert into app.bookings (org_id, staff_id, service_id, contact_id, starts_at, ends_at, status, source)
            values (:o, :st, :sv, :k, :s, :e, 'showed', 'test')"""), {"o": oid, "st": ids.st, "sv": ids.sv, "k": k2, "s": start, "e": start + timedelta(minutes=30)})
    sent = await ac.recalls()
    assert sent >= 1
    assert (await said(oid, k2)) == ["Hi Due, it's been 6 months since your Cleaning. Reply 1 and we'll find you a time."]
    assert await said(oid, k) == []  # came back 2 months ago: not due
    await ac.recalls()
    assert len(await said(oid, k2)) == 1  # once


async def test_governance_shadow_and_limit(client, team_org):
    oid, h = await clinic(team_org)
    bid, _conv = await patient(oid, at(3, 12))
    assert (await client.put("/org/governance/appointment_concierge.send", headers=h["owner"], json={"level": "shadow"})).status_code == 200
    assert await ac.appt_send(oid, bid, "reminder") == "shadow"
    assert await said(oid) == []
    assert (await client.put("/org/governance/appointment_concierge.send", headers=h["owner"],
                             json={"level": "auto_limited", "max_per_day": 0})).status_code == 200
    assert await ac.appt_send(oid, bid, "reminder") == "awaiting_approval"  # over today's limit: a person decides
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select title, payload from app.approvals where automation_key = 'appointment_concierge'"))).one()
    assert card.title == "Message Meera Shah about their Cleaning" and card.payload["held_because"].startswith("today's limit of 0")


async def test_calendar_page_by_role(client, team_org):
    oid, h = await clinic(team_org)
    await patient(oid, at(1, 10))
    got = {r: (await client.get("/org/calendar", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=200, agentry=200)
    owner = (await client.get("/org/calendar", headers=h["owner"])).json()
    viewer = (await client.get("/org/calendar", headers=h["viewer"])).json()
    assert owner["concierge"] == "live" and owner["can_act"] is True and viewer["can_act"] is False
    assert owner["items"][0]["service"] == "Cleaning" and owner["items"][0]["time"] == "10:00 AM" and owner["items"][0]["email"] == "meera@patients.example"
    assert viewer["items"][0]["email"] is None  # viewers see the diary, not contact details


async def test_approval_mode_holds_messages_until_a_person_approves(client, team_org):
    from agentry.worker.delivery import deliver_outbound_draft
    oid, h = await clinic(team_org)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    bid, _conv = await patient(oid, at(2, 16))
    assert await ac.appt_send(oid, bid, "reminder") == "awaiting_approval"
    assert await said(oid) == []
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select id::text, kind, body from app.approvals where automation_key = 'appointment_concierge'"))).one()
    assert card.kind == "outbound_draft" and "Reply 1 to confirm" in card.body
    r = await client.post(f"/org/approvals/{card.id}", headers=h["staff"], json={"action": "approve", "body": card.body + " Thanks!"})
    assert r.status_code == 200, r.text
    assert (await deliver_outbound_draft(oid, card.id))["status"] == "recorded"
    assert (await said(oid))[-1].endswith("Reply 1 to confirm or 2 to change the time. Thanks!")  # the edited text went out
