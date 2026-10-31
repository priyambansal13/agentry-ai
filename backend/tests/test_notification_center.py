"""Notification Center: any event -> rules -> people -> Telegram / WhatsApp / email / bell, with conditions, no
duplicates, quiet hours, an hourly limit, digests, personal and muted rules, and the events it adds."""
from datetime import UTC, datetime, timedelta

import pytest
from conftest import expect
from sqlalchemy import text
from test_telegram import TEAM, FakeTelegram, link

from agentry.config import settings
from agentry.connectors import http
from agentry.db import tenant_session
from agentry.events import emit
from agentry.notify import alerts, center
from agentry.worker import notify_jobs

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


@pytest.fixture
def channels(monkeypatch):
    """A fake Telegram team bot, and email captured instead of sent."""
    from agentry import telegram_team
    f = FakeTelegram()
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "telegram_bot_token", TEAM)
    monkeypatch.setattr(settings, "telegram_mode", "polling")
    monkeypatch.setattr(telegram_team, "_username", None)
    f.emails = []
    monkeypatch.setattr(alerts, "send_email", lambda to, s, b: f.emails.append((to.split("-")[0], s, b)))
    return f


async def fire(oid: str, type_: str, payload: dict) -> dict:
    async with tenant_session(oid) as conn:
        eid = await emit(conn, oid, type_, payload)
    return {"id": eid, "org_id": oid, "type": type_, "payload": payload}


async def run(event: dict, now: datetime | None = None) -> list[int]:
    ids = await center.plan(event, now)
    if ids:
        await center.deliver(event["org_id"], ids)
    return ids


async def mine(oid: str, role_email_prefix: str) -> list[dict]:
    async with tenant_session(oid) as conn:
        return [dict(r) for r in (await conn.execute(text("""select n.* from app.notifications n join auth."user" u on u.id = n.user_id
            where u.email like :e order by n.id"""), {"e": f"{role_email_prefix}-%"})).mappings()]


PAYMENT = {"amount": 41250.0, "currency": "INR", "invoice": "MSR-1014", "gateway": "razorpay", "status": "paid", "reference": "pay_1"}


async def test_defaults_payment_alert_fallback_and_no_duplicates(client, team_org, channels):
    oid, h = await team_org(["invoice_follow_up"])
    d = (await client.get("/org/notification-center", headers=h["owner"])).json()
    names = {r["name"] for r in d["rules"]}
    assert {"Money in", "Cards waiting too long", "Broken connections"} <= names and "New bookings" not in names  # only what they have
    assert {c["type"] for c in d["catalogue"]} >= {"payment.received", "approval.created", "connection.broken"}
    fin = (await client.get("/org/notification-center", headers=h["finance"])).json()
    assert "lead.created" not in {c["type"] for c in fin["catalogue"]}  # finance can't see leads
    owner = await link(client, h, "owner", channels)
    ev = await fire(oid, "payment.received", PAYMENT)
    ids = await run(ev)
    assert len(ids) == 2  # "Money in": owner + finance
    assert channels.to(owner)[-1]["text"].startswith("🔔 Payment received: ₹41,250 for MSR-1014")
    assert [e[:2] for e in channels.emails] == [("finance", "Payment received: ₹41,250 for MSR-1014")]  # no Telegram linked: email instead
    fin_row = (await mine(oid, "finance"))[0]
    assert fin_row["status"] == "sent" and fin_row["deliveries"][-1]["fallback"] is True
    assert await center.plan(ev) == []  # the same event never notifies twice
    bell = (await client.get("/org/notifications/inbox", headers=h["owner"])).json()
    assert bell["unread"] == 1 and bell["items"][0]["link"] == "/invoices"
    assert (await client.post("/org/notifications/inbox/read", headers=h["owner"], json={})).json() == {"read": 1}
    assert (await client.get("/org/notifications/inbox", headers=h["owner"])).json()["unread"] == 0


async def test_conditions_rules_permissions_and_muting(client, team_org, channels):
    oid, h = await team_org(["invoice_follow_up"])
    body = {"name": "Big payments", "event_type": "payment.received", "conditions": [{"field": "amount", "op": "gt", "value": 100000}],
            "roles": ["manager"], "channels": ["email"]}
    got = {r: (await client.post("/org/notification-rules", headers=h[r], json=body)).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    assert (await client.post("/org/notification-rules", headers=h["owner"], json=body)).status_code == 201
    bad = body | {"conditions": [{"field": "invoice", "op": "gt", "value": 5}]}
    assert (await client.post("/org/notification-rules", headers=h["owner"], json=bad)).status_code == 422
    assert (await client.post("/org/notification-rules", headers=h["owner"], json=body | {"event_type": "lead.created"})).status_code == 422  # not here
    await run(await fire(oid, "payment.received", PAYMENT))  # ₹41,250: not "big"
    assert not await mine(oid, "manager")
    await run(await fire(oid, "payment.received", PAYMENT | {"amount": 250000.0, "reference": "pay_2"}))
    assert [e[:2] for e in channels.emails if e[0] == "manager"] == [("manager", "Payment received: ₹250,000 for MSR-1014")]
    # finance mutes "Money in" for themselves; a personal rule of their own still works
    money_in = next(r["id"] for r in (await client.get("/org/notification-center", headers=h["finance"])).json()["rules"] if r["name"] == "Money in")
    assert (await client.post(f"/org/notification-rules/{money_in}/mute", headers=h["finance"], json={"muted": True})).json()["muted"] is True
    assert (await client.put(f"/org/notification-rules/{money_in}", headers=h["finance"], json=body | {"name": "Renamed"})).status_code == 403
    personal = {"name": "Razorpay only", "event_type": "payment.received", "conditions": [{"field": "gateway", "op": "eq", "value": "razorpay"}],
                "channels": ["email"], "personal": True}
    assert (await client.post("/org/notification-rules", headers=h["finance"], json=personal)).status_code == 201
    channels.emails.clear()
    await run(await fire(oid, "payment.received", PAYMENT | {"reference": "pay_3"}))
    rows = await mine(oid, "finance")
    assert len(rows) == 3 and rows[-1]["rule_id"] is not None  # from their own rule, though "Money in" is muted
    assert ("finance", "Payment received: ₹41,250 for MSR-1014") in [e[:2] for e in channels.emails]
    others = (await client.get("/org/notification-center", headers=h["owner"])).json()["rules"]
    assert "Razorpay only" not in {r["name"] for r in others}  # personal rules are private
    t = await client.post(f"/org/notification-rules/{money_in}/test", headers=h["owner"])
    assert t.json() == {"results": {"telegram": "Telegram isn't linked"}}


async def test_quiet_hours_critical_hourly_limit_and_digests(client, team_org, channels):
    oid, h = await team_org(["invoice_follow_up", "website_chat"])
    owner = await link(client, h, "owner", channels)
    await client.put("/org/notification-settings", headers=h["owner"], json={"quiet_from": "00:00", "quiet_to": "23:59", "max_per_hour": 2})
    await run(await fire(oid, "payment.received", PAYMENT))
    row = [r for r in await mine(oid, "owner")][-1]
    assert row["status"] == "held" and row["deliver_after"] > datetime.now(UTC)  # quiet hours: until morning
    before = len(channels.to(owner))
    # critical events ignore quiet hours
    await run(await fire(oid, "connection.broken", {"provider": "gmail", "account": "owner@clinic.example", "error": "invalid_grant"}))
    assert channels.to(owner)[-1]["text"].startswith("🔔 Gmail stopped working") and len(channels.to(owner)) == before + 1
    await client.put("/org/notification-settings", headers=h["owner"], json={"max_per_hour": 2})  # quiet hours off
    for i in range(3):
        await run(await fire(oid, "payment.received", PAYMENT | {"reference": f"pay_h{i}"}))
    statuses = [r["status"] for r in await mine(oid, "owner")]
    assert statuses[-3:] == ["sent", "digest", "digest"]  # 1 critical + 1 now = 2 this hour; the rest wait
    # leads: a daily digest at 18:00, sent as one message
    await run(await fire(oid, "lead.created", {"lead_id": None, "source": "web_chat"}))  # unknown lead: described as nothing, skipped
    async with tenant_session(oid) as conn:
        cid = (await conn.execute(text("insert into app.contacts (org_id, name, source) values (:o, 'Meera', 'web_chat') returning id"), {"o": oid})).scalar_one()
        leads = [str((await conn.execute(text("insert into app.leads (org_id, contact_id, source) values (:o, :c, 'web_chat') returning id"),
                                         {"o": oid, "c": cid})).scalar_one()) for _ in range(2)]
    for lid in leads:
        await run(await fire(oid, "lead.created", {"lead_id": lid, "source": "web_chat"}))
    digest = [r for r in await mine(oid, "owner") if r["event_type"] == "lead.created"]
    assert len(digest) == 2 and all(r["status"] == "digest" for r in digest)
    n_before = len(channels.to(owner))
    assert await center.release_due(datetime.now(UTC) + timedelta(days=2)) >= 1
    combined = channels.to(owner)[n_before:]
    # 1 payment held in quiet hours + 2 over the hourly limit + 2 leads: one message
    assert len(combined) == 1 and combined[0]["text"].startswith("🔔 5 updates from Agentry")
    assert all(r["status"] == "sent" for r in await mine(oid, "owner"))


async def test_new_events_cards_waiting_and_broken_connections(client, team_org, channels):
    from agentry.connectors.store import save_connection, update_state
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        aid = (await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, created_at)
            values (:o, 'handoff', 'inbox_triage', 'Customer wants a call', 'x', now() - interval '5 hours') returning id::text"""), {"o": oid})).scalar_one()
    assert await notify_jobs.waiting_step() >= 1
    async with tenant_session(oid) as conn:
        evs = (await conn.execute(text("select payload from app.events where type = 'approval.waiting_long'"))).scalars().all()
    assert len(evs) == 1 and evs[0]["approval_id"] == aid and evs[0]["hours"] >= 5
    cid = await save_connection(oid, provider="gmail", account_ref="owner@clinic.example", secret={"refresh_token": "r"})
    await update_state(oid, cid, error="invalid_grant: token revoked")
    await update_state(oid, cid, error="invalid_grant: still revoked")  # still broken: no second event
    async with tenant_session(oid) as conn:
        broken = (await conn.execute(text("select payload from app.events where type = 'connection.broken'"))).scalars().all()
    assert len(broken) == 1 and broken[0]["provider"] == "gmail"
    await run({"id": -1, "org_id": oid, "type": "approval.waiting_long", "payload": evs[0]})
    assert {r["title"] for r in await mine(oid, "owner")} == {"Waiting 5 h: Customer wants a call"}


async def test_hq_delivery_log_is_staff_only(client, team_org, channels):
    oid, h = await team_org(["invoice_follow_up"])
    await run(await fire(oid, "payment.received", PAYMENT))
    assert (await client.get(f"/hq/orgs/{oid}/notifications-log", headers=h["owner"])).status_code == 403
    log = (await client.get(f"/hq/orgs/{oid}/notifications-log", headers=h["agentry"])).json()
    assert len(log["items"]) == 2 and log["last_7_days"]["sent"] == 2
    assert ALL
