"""Governance: levels that start from what a business already had, daily limits and quiet hours that turn automatic
sends into cards, watch-only, the track record behind suggestions, owner-only changes, and the tamper-evident audit log."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import expect
from helpers import enrollment_for
from sqlalchemy import create_engine, text
from test_invoice_e2e import go_live_invoice_client

from agentry import audit, governance
from agentry.config import settings
from agentry.db import tenant_session
from agentry.invoices import enroll_open
from agentry.sequences import send_step

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
IST = ZoneInfo("Asia/Kolkata")


async def test_defaults_change_nothing_on_day_one(client, team_org):
    oid, h = await team_org(["invoice_follow_up", "cold_email", "inbox_triage"], live=False)
    d = (await client.get("/org/governance", headers=h["owner"])).json()
    levels = {a["action"]: (a["level"], a["chosen"]) for a in d["actions"]}
    assert levels == {"invoice_follow_up.send": ("recommend", False), "inbox_triage.send_reply": ("recommend", False),
                      "cold_email.send": ("auto_limited", False)}  # approval mode = cards; cold email: lines are approved first
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'live'"))
    d = (await client.get("/org/governance", headers=h["owner"])).json()
    assert {a["action"]: a["level"] for a in d["actions"]}["invoice_follow_up.send"] == "auto_limited"


async def test_limits_quiet_hours_and_who_may_change(client, team_org, monkeypatch):
    oid, h = await team_org(["invoice_follow_up", "speed_to_lead", "cold_email"])
    got = {r: (await client.get("/org/governance", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    body = {"level": "auto_limited", "max_per_day": 2, "quiet_hours": True}
    got = {r: (await client.put("/org/governance/invoice_follow_up.send", headers=h[r], json=body)).status_code for r in ALL}
    expect(got, owner=200, manager=403, staff=403, finance=403, viewer=403, agentry=200)
    assert (await client.put("/org/governance/cold_email.send", headers=h["owner"], json={"level": "recommend"})).status_code == 422
    noon = datetime(2026, 11, 2, 12, 0, tzinfo=IST).astimezone(UTC)
    async with tenant_session(oid) as conn:
        modes = [(await governance.decide(conn, oid, "invoice_follow_up.send", noon)).mode for _ in range(3)]
        third = await governance.decide(conn, oid, "invoice_follow_up.send", noon)
    assert modes == ["send", "send", "card"] and third.reason == "today's limit of 2 reached: the rest wait for a person"
    monkeypatch.setattr(governance, "_quiet", governance.is_quiet)  # the real clock rule
    night = datetime(2026, 11, 3, 23, 0, tzinfo=IST).astimezone(UTC)
    async with tenant_session(oid) as conn:
        d = await governance.decide(conn, oid, "invoice_follow_up.send", night)
        lead = await governance.decide(conn, oid, "speed_to_lead.send", night)  # replying to a fresh lead isn't held
    assert d.mode == "card" and d.reason.startswith("quiet hours") and lead.mode == "send"
    async with tenant_session(oid) as conn:
        acts = (await conn.execute(text("select metadata from app.audit_log where action = 'governance.changed'"))).scalars().all()
    assert acts[-1] == {"level": "auto_limited", "max_per_day": 2, "quiet_hours": True}


async def test_reminders_follow_the_level(client, team_org):
    oid, h = await go_live_invoice_client(client, team_org)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'live'"))
        await conn.execute(text("delete from app.connections where provider = 'gmail'"))  # recorded locally, not sent
        await enroll_open(conn, oid)
    await client.put("/org/governance/invoice_follow_up.send", headers=h["owner"], json={"level": "auto_limited", "max_per_day": 1})
    first = await send_step(oid, await enrollment_for(oid, "E-1"), 0)
    second = await send_step(oid, await enrollment_for(oid, "E-2"), 0)
    assert first["results"][0]["status"] == "recorded"
    assert second["results"][0] == {"channel": "email", "status": "awaiting_approval", "reason": "today's limit of 1 reached: the rest wait for a person"}
    async with tenant_session(oid) as conn:
        held = (await conn.execute(text("select payload->>'held_because' from app.approvals where kind = 'outbound_draft'"))).scalar_one()
    assert held.startswith("today's limit")
    await client.put("/org/governance/invoice_follow_up.send", headers=h["owner"], json={"level": "shadow"})
    watch = await send_step(oid, await enrollment_for(oid, "E-1"), 1)
    assert watch["results"][0]["status"] == "shadow" and watch["results"][0]["would_send"]["body"]
    async with tenant_session(oid) as conn:
        cards = (await conn.execute(text("select count(*) from app.approvals where kind = 'outbound_draft'"))).scalar_one()
    assert cards == 1  # watching only: no card, nothing sent


async def test_track_record_suggests_more_freedom(client, team_org):
    oid, h = await team_org(["invoice_follow_up"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
        uid = (await conn.execute(text("""select m."userId" from auth.member m where m."organizationId" = :o and m.role = 'owner'"""), {"o": oid})).scalar_one()
        for i in range(21):
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, status, decided_by, decided_at)
                values (:o, 'outbound_draft', 'invoice_follow_up', :t, 'x', :s, :u, now())"""),
                {"o": oid, "t": f"Reminder {i}", "s": "edited" if i == 0 else "approved", "u": uid})
    a = next(x for x in (await client.get("/org/governance", headers=h["owner"])).json()["actions"] if x["action"] == "invoice_follow_up.send")
    assert a["record"] == {"decided": 21, "as_written": 20, "edited": 1, "rejected": 0, "rate": 0.95}
    assert a["suggestion"].startswith("20 of the last 21 were approved as written")


async def test_audit_log_is_tamper_evident(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        for i in range(3):
            await audit.record(conn, org_id=oid, actor_type="system", action=f"test.event{i}", metadata={"n": i})
    got = {r: (await client.get(f"/hq/orgs/{oid}/audit-chain", headers=h[r])).status_code for r in ("owner", "agentry")}
    expect(got, owner=403, agentry=200)
    ok = (await client.get(f"/hq/orgs/{oid}/audit-chain", headers=h["agentry"])).json()
    assert ok["intact"] is True and ok["rows"] >= 3
    with pytest.raises(Exception, match="permission denied"):  # the app itself can't rewrite history
        async with tenant_session(oid) as conn:
            await conn.execute(text("update app.audit_log set metadata = '{}' where action = 'test.event1'"))
    owner_db = create_engine(settings.migrate_database_url)  # someone with database access edits a row...
    with owner_db.begin() as c:
        bad = c.execute(text("update app.audit_log set metadata = '{\"n\": 99}' where org_id = :o and action = 'test.event1' returning id"),
                        {"o": oid}).scalar_one()
    broken = (await client.get(f"/hq/orgs/{oid}/audit-chain", headers=h["agentry"])).json()
    assert broken["intact"] is False and broken["first_broken_id"] == bad  # ...and the chain shows exactly where
