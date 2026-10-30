"""Cold email 5.4-5.5 against the mock sender: starting, office hours, ramp-up caps, the 4-step sequence in one thread,
compliance footer and one-click unsubscribe, replies of every kind, and automatic mailbox pausing."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import expect
from sqlalchemy import text
from test_cold_email import SEARCH, built

from agentry.automations.cold_email import providers, replies, sending
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
IST = ZoneInfo("Asia/Kolkata")


def monday(weeks_ahead: int = 1) -> datetime:
    """11:00 IST on a coming Monday: inside office hours, and +3/+7/+14 days are weekdays too."""
    d = datetime.now(IST).date()
    d += timedelta(days=(7 - d.weekday()) % 7 or 7) + timedelta(weeks=weeks_ahead - 1)
    return datetime(d.year, d.month, d.day, 11, 0, tzinfo=IST).astimezone(UTC)


async def ready_campaign(client, team_org, mailboxes: int = 1, start_at: datetime | None = None):
    """A built list with every line approved, settings filled in and mock sending mailboxes; not started yet."""
    oid, h = await team_org(["cold_email"])
    cid = await built(client, h, oid, SEARCH)
    assert (await client.post(f"/org/cold-email/campaigns/{cid}/approve-ready", headers=h["owner"])).json()["approved"] >= 8
    r = await client.patch("/org/automations/cold_email/config", headers=h["owner"],
                           json={"pitch": "We answer your clinic's calls and WhatsApp 24/7 and book the appointments",
                                 "postal_address": "Agentry, 12 FC Road, Pune 411004"})
    assert r.status_code == 200, r.text
    for i in range(mailboxes):
        r = await client.post(f"/hq/orgs/{oid}/sending-mailboxes", headers=h["agentry"],
                              json={"address": f"priyam{i}@getagentry.example", "sender_name": "Priyam"})
        assert r.status_code == 201, r.text
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.sending_mailboxes set started_at = :t"), {"t": start_at or monday()})
    return oid, h, cid


@pytest.fixture(autouse=True)
def clean_outbox():
    providers.MOCK_OUTBOX.clear()
    yield
    providers.MOCK_OUTBOX.clear()


async def test_start_needs_settings_a_mailbox_and_approved_lines(client, team_org):
    oid, h = await team_org(["cold_email"])
    cid = await built(client, h, oid, SEARCH)
    r = await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])
    assert r.status_code == 409 and "what you offer and your postal address" in r.json()["detail"]
    await client.patch("/org/automations/cold_email/config", headers=h["owner"], json={"pitch": "x", "postal_address": "Pune"})
    assert "no sending mailbox" in (await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])).json()["detail"]
    # mailboxes: Agentry only, never on the business's own domain
    body = {"address": "priyam@getagentry.example", "sender_name": "Priyam"}
    assert (await client.post(f"/hq/orgs/{oid}/sending-mailboxes", headers=h["owner"], json=body)).status_code == 403
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.org_settings set website = 'https://agentry.example'"))
    own = await client.post(f"/hq/orgs/{oid}/sending-mailboxes", headers=h["agentry"], json=body | {"address": "me@agentry.example"})
    assert own.status_code == 422 and "main domain" in own.json()["detail"]
    assert (await client.post(f"/hq/orgs/{oid}/sending-mailboxes", headers=h["agentry"], json=body)).status_code == 201
    assert "approve at least one" in (await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])).json()["detail"]
    await client.post(f"/org/cold-email/campaigns/{cid}/approve-ready", headers=h["owner"])
    got = {r: (await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h[r])).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    assert (await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["manager"])).json() == {"queued": 8}


async def test_office_hours_ramp_up_and_the_whole_sequence(client, team_org):
    t0 = monday()
    oid, h, cid = await ready_campaign(client, team_org, mailboxes=1, start_at=t0)
    await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])
    assert (await sending.send_due(oid, t0 - timedelta(days=2)))["sent"] == 0  # Saturday: nothing goes out
    assert (await sending.send_due(oid, t0 + timedelta(hours=8)))["reason"] == "outside office hours"  # 19:00
    first = await sending.send_due(oid, t0)
    assert first == {"sent": 5, "waiting_for_capacity": 3}  # day one of ramp-up: 5 a mailbox
    assert (await sending.send_due(oid, t0 + timedelta(minutes=30)))["sent"] == 0  # cap reached for today
    mail = providers.MOCK_OUTBOX[0]
    assert mail["from"] == "priyam0@getagentry.example" and "Agentry, 12 FC Road, Pune 411004" in mail["body"]
    assert "/unsubscribe/" in mail["body"] and mail["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert mail["body"].startswith("Hi ") and "Worth a 15-minute call" in mail["body"]
    async with tenant_session(oid) as conn:
        line = (await conn.execute(text("select first_line from app.prospects where email = :e"), {"e": mail["to"]})).scalar_one()
    assert line in mail["body"]
    # day 2: the cap has grown (5 + 3), the other 3 first emails go
    assert (await sending.send_due(oid, t0 + timedelta(days=1)))["sent"] == 3
    # day 3 after each first email: the bump, in the same thread, from the same mailbox
    assert (await sending.send_due(oid, t0 + timedelta(days=3)))["sent"] == 5
    bump = providers.MOCK_OUTBOX[-1]
    assert bump["subject"].startswith("Re: ") and bump["from"] == "priyam0@getagentry.example" and "Bumping" in bump["body"]
    for day in (4, 7, 8, 14, 15):
        await sending.send_due(oid, t0 + timedelta(days=day))
    assert len(providers.MOCK_OUTBOX) == 8 * 4
    c = (await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json()
    assert c["status"] == "completed" and c["sending"]["people_emailed"] == 8 and c["sending"]["emails_sent"] == 32
    assert "I'll stop here" in providers.MOCK_OUTBOX[-1]["body"]


async def test_replies_of_every_kind(client, team_org):
    t0 = monday()
    oid, h, cid = await ready_campaign(client, team_org, mailboxes=2, start_at=t0)
    await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])
    assert (await sending.send_due(oid, t0))["sent"] == 8
    emails = [m["to"] for m in providers.MOCK_OUTBOX]
    interested, later, stop, away, bounced, referral = emails[:6]

    r = await replies.ingest_reply(oid, interested, "Sounds interesting. What does it cost per month for one clinic?")
    assert r["kind"] == "interested" and r["lead_id"]
    async with tenant_session(oid) as conn:
        lead = (await conn.execute(text("select stage, source, owner_automation from app.leads where id = cast(:l as uuid)"), {"l": r["lead_id"]})).one()
        msgs = (await conn.execute(text("select direction from app.messages where conversation_id = cast(:c as uuid) order by created_at"),
                                   {"c": r["conversation_id"]})).scalars().all()
    assert tuple(lead) == ("engaged", "cold_email", "cold_email") and sorted(msgs) == ["in", "out"]  # our email + their reply
    cards = (await client.get("/org/approvals", headers=h["owner"])).json()["items"]
    assert any(a["title"].startswith("Interested: ") and a["conversation_id"] == r["conversation_id"] for a in cards)

    assert (await replies.ingest_reply(oid, later, "Thanks, not now. Maybe next quarter."))["kind"] == "not_now"
    assert (await replies.ingest_reply(oid, away, "Out of office until Monday, limited access to email."))["kind"] == "out_of_office"
    b = await replies.ingest_reply(oid, bounced, "Mail Delivery Subsystem: Delivery Status Notification (Failure). Address not found.")
    assert b["kind"] == "bounce" and b["mailbox_paused"] is None  # one bounce in 4 sends: too few to judge yet
    ref = await replies.ingest_reply(oid, referral, "I don't handle this, please talk to our manager Ravi Kulkarni ravi@clinic.example")
    assert ref["kind"] == "referral"
    assert (await replies.ingest_reply(oid, "stranger@nowhere.example", "hello"))["matched"] is False

    # the unsubscribe link: public, no sign-in, works once and for good
    async with tenant_session(oid) as conn:
        pid = (await conn.execute(text("select id::text from app.prospects where email = :e"), {"e": stop})).scalar_one()
    token = sending.unsubscribe_token(oid, pid)
    info = (await client.get(f"/public/unsubscribe/{token}")).json()
    assert info["email"] == stop and info["unsubscribed"] is False
    assert (await client.post(f"/public/unsubscribe/{token}")).json() == {"unsubscribed": True}
    assert (await client.get(f"/public/unsubscribe/{token}")).json()["unsubscribed"] is True
    assert (await client.get("/public/unsubscribe/forged.token")).status_code == 404

    async with tenant_session(oid) as conn:
        rows = dict((await conn.execute(text("select email, status || ':' || coalesce(stop_reason, '-') from app.prospects where email = any(:e)"),
                                        {"e": [interested, later, stop, away, bounced, referral]})).all())
        sup = dict((await conn.execute(text("select address, reason from app.suppressions where address = any(:e)"), {"e": [stop, bounced]})).all())
        nurture = (await conn.execute(text("select nurture_at > now() + interval '70 days' from app.prospects where email = :e"), {"e": later})).scalar_one()
        away_next = (await conn.execute(text("select next_send_at from app.prospects where email = :e"), {"e": away})).scalar_one()
    assert rows == {interested: "stopped:replied: interested", later: "stopped:replied: not now", stop: "stopped:unsubscribed",
                    away: "active:-", bounced: "stopped:bounced", referral: "stopped:replied: referral"}
    assert sup == {stop: "opt_out", bounced: "bounce"} and nurture and away_next > t0 + timedelta(days=9)
    # only the away and untouched prospects get the day-3 bump
    sent_before = len(providers.MOCK_OUTBOX)
    await sending.send_due(oid, t0 + timedelta(days=3))
    assert sorted(m["to"] for m in providers.MOCK_OUTBOX[sent_before:]) == sorted(emails[6:])
    c = (await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json()["sending"]
    assert (c["replied"], c["interested"], c["bounced"], c["unsubscribed"]) == (5, 1, 1, 1)


async def test_spam_complaint_and_bounce_rate_pause_the_mailbox(client, team_org):
    t0 = monday()
    oid, h, cid = await ready_campaign(client, team_org, mailboxes=1, start_at=t0 - timedelta(days=30))  # fully ramped
    await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])
    await sending.send_due(oid, t0)
    r = await replies.complaint(oid, providers.MOCK_OUTBOX[0]["to"])
    assert r["mailbox_paused"] == "a recipient marked an email as spam"
    boxes = (await client.get(f"/hq/orgs/{oid}/sending-mailboxes", headers=h["agentry"])).json()["items"]
    assert boxes[0]["status"] == "paused"
    assert (await sending.send_due(oid, t0 + timedelta(days=3)))["sent"] == 0  # threads wait for their own mailbox
    # bounce rate over 48 sends (8 real + 40): 1 bounce is 2.1%, fine; 2 bounces is 4.2%, over the 3% limit
    async with tenant_session(oid) as conn:
        mid = boxes[0]["id"]
        await conn.execute(text("delete from app.email_events where kind = 'complaint'"))
        await conn.execute(text("update app.sending_mailboxes set status = 'active', paused_reason = null"))
        for _ in range(40):
            await conn.execute(text("""insert into app.email_events (org_id, campaign_id, mailbox_id, kind) values (:o, cast(:c as uuid), cast(:m as uuid), 'sent')"""),
                               {"o": oid, "c": cid, "m": mid})
        await conn.execute(text("insert into app.email_events (org_id, mailbox_id, kind) values (:o, cast(:m as uuid), 'bounce')"), {"o": oid, "m": mid})
        assert await sending.check_mailbox(conn, mid) is None
        await conn.execute(text("insert into app.email_events (org_id, mailbox_id, kind) values (:o, cast(:m as uuid), 'bounce')"), {"o": oid, "m": mid})
        assert (await sending.check_mailbox(conn, mid)).startswith("bounce rate")


async def test_pause_drop_and_the_reply_simulator(client, team_org):
    t0 = monday()
    oid, h, cid = await ready_campaign(client, team_org, mailboxes=2, start_at=t0)
    await client.post(f"/org/cold-email/campaigns/{cid}/start", headers=h["owner"])
    assert (await client.post(f"/org/cold-email/campaigns/{cid}/pause", headers=h["manager"])).json() == {"status": "paused"}
    assert (await sending.send_due(oid, t0))["sent"] == 0
    await client.post(f"/org/cold-email/campaigns/{cid}/resume", headers=h["manager"])
    items = (await client.get(f"/org/cold-email/campaigns/{cid}/prospects?review=approved", headers=h["owner"])).json()["items"]
    await client.post(f"/org/cold-email/prospects/{items[0]['id']}", headers=h["owner"], json={"action": "drop"})
    assert (await sending.send_due(oid, t0))["sent"] == 7  # a dropped person is never emailed
    one = items[1]["id"]
    got = {r: (await client.post(f"/org/cold-email/prospects/{one}/simulate-reply", headers=h[r], json={"text": "Tell me more?"})).status_code
           for r in ("owner", "manager")}
    expect(got, owner=404, manager=404)  # Agentry staff only, and only in mock mode
    r = await client.post(f"/org/cold-email/prospects/{one}/simulate-reply", headers=h["agentry"], json={"text": "Tell me more, what's the price?"})
    assert r.status_code == 200 and r.json()["kind"] == "interested"
    assert ALL
