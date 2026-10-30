"""Urgent emails nobody answers: the owner hears about it after the set time (and never at night)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from agentry.automations.inbox_triage import escalation
from agentry.db import tenant_session

IST = ZoneInfo("Asia/Kolkata")


def test_quiet_hours_wait():
    q = ["21:00", "08:00"]
    assert escalation.seconds_until_quiet_end("Asia/Kolkata", q, datetime(2026, 10, 25, 14, 0, tzinfo=IST)) == 0
    assert escalation.seconds_until_quiet_end("Asia/Kolkata", q, datetime(2026, 10, 25, 23, 0, tzinfo=IST)) == 9 * 3600
    assert escalation.seconds_until_quiet_end("Asia/Kolkata", q, datetime(2026, 10, 26, 7, 30, tzinfo=IST)) == 1800
    assert escalation.seconds_until_quiet_end("Asia/Kolkata", ["13:00", "14:00"], datetime(2026, 10, 25, 13, 30, tzinfo=IST)) == 1800


async def urgent_email(oid: str, owner_alert: str = "immediately") -> dict:
    """An urgent email in a conversation, as the triage workflow leaves it (with its draft card)."""
    async with tenant_session(oid) as conn:
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, metadata)
            values (:o, 'email', 'inbox_triage', 'Site is down!', '{"source": "local"}') returning id"""), {"o": oid})).scalar_one())
        received = (await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, cast(:c as uuid), 'in', 'contact', 'Our site is down, please help ASAP', '{"from": "ceo@bigclient.example"}')
            returning created_at"""), {"o": oid, "c": cid})).scalar_one()
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body)
            values (:o, 'reply_draft', 'inbox_triage', cast(:c as uuid), 'Reply', 'On it')"""), {"o": oid, "c": cid})
    return {"conversation_id": cid, "message_id": "m", "from": "ceo@bigclient.example", "subject": "Site is down!",
            "received_at": received.isoformat(), "urgent_reason": "site outage", "summary": "Client's site is down.",
            "config": {"quiet_hours": ["21:00", "08:00"], "alert_channel": "email", "telegram_chat_id": None,
                       "owner_alert": owner_alert, "escalate_after_minutes": 30}}


async def test_handled_means_replied_or_decided(team_org):
    oid, _h = await team_org(["inbox_triage"])
    e = await urgent_email(oid)
    assert await escalation.is_handled(oid, e["conversation_id"], e["received_at"]) is False
    async with tenant_session(oid) as conn:  # someone approves the draft in Needs you
        await conn.execute(text("update app.approvals set status = 'approved' where conversation_id = cast(:c as uuid)"), {"c": e["conversation_id"]})
    assert await escalation.is_handled(oid, e["conversation_id"], e["received_at"]) is True
    e2 = await urgent_email(oid)
    async with tenant_session(oid) as conn:  # or a person replies (from Agentry, or Gmail sync records it)
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
            values (:o, cast(:c as uuid), 'out', 'human', 'Looking now')"""), {"o": oid, "c": e2["conversation_id"]})
    assert await escalation.is_handled(oid, e2["conversation_id"], e2["received_at"]) is True


async def test_who_gets_first_alert_and_escalation(team_org, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("agentry.notify.alerts.send_email", lambda to, s, b: sent.append((to.split("-")[0], s)))
    oid, _h = await team_org(["inbox_triage"])
    # default: owner and manager get the first alert; the escalation goes to the owner
    e = await urgent_email(oid)
    await escalation.send_alert(oid, e, escalation=False)
    assert sorted(w for w, _ in sent) == ["manager", "owner"] and sent[0][1].startswith("URGENT email")
    sent.clear()
    await escalation.send_alert(oid, e, escalation=True, minutes=30)
    assert sent == [("owner", "Still unanswered after 30 min: Site is down!")]
    # "only if unanswered": the first alert skips the owner
    sent.clear()
    e = await urgent_email(oid, owner_alert="if_unanswered")
    await escalation.send_alert(oid, e, escalation=False)
    assert [w for w, _ in sent] == ["manager"]
    # a one-person team: nobody else gets alerts, so the owner is told straight away anyway
    sent.clear()
    solo, _ = await team_org(["inbox_triage"])
    async with tenant_session(solo) as conn:
        await conn.execute(text("""delete from app.notification_preferences where org_id = :o"""), {"o": solo})
    from agentry.notify import alerts
    monkeypatch.setattr(alerts, "recipients", _only_owner(alerts.recipients))
    await escalation.send_alert(solo, await urgent_email(solo, owner_alert="if_unanswered"), escalation=False)
    assert [w for w, _ in sent] == ["owner"]


def _only_owner(real):
    """recipients as in an organisation where only the owner exists."""
    async def f(org_id: str, kind: str, exclude_roles: tuple[str, ...] = ()) -> list[dict]:
        return [p for p in await real(org_id, kind, exclude_roles) if p["email"].startswith("owner-")]
    return f


async def test_follow_up_escalates_only_when_unanswered(team_org, monkeypatch):
    from dbos import DBOS
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("agentry.notify.alerts.send_email", lambda to, s, b: sent.append((to.split("-")[0], s)))
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)
    monkeypatch.setattr(DBOS, "sleep_async", no_wait)

    async def daytime(org_id: str) -> float:  # the first part happens in the day, whatever time the tests run
        return 0
    monkeypatch.setattr(escalation, "quiet_wait", daytime)
    oid, _h = await team_org(["inbox_triage"])
    # nobody answered: after 30 min the owner hears about it
    e = await urgent_email(oid)
    assert await escalation.follow_up_urgent(oid, e, "email") == "escalated"
    assert waits == [1800] and sent == [("owner", "Still unanswered after 30 min: Site is down!")]
    # answered in time: no second alert
    sent.clear()
    e = await urgent_email(oid)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.approvals set status = 'resolved' where conversation_id = cast(:c as uuid)"), {"c": e["conversation_id"]})
    assert await escalation.follow_up_urgent(oid, e, "email") == "handled" and sent == []
    # arrived at night: the held first alert goes out when quiet hours end, then the escalation if still unanswered
    async def night(org_id: str) -> float:
        return 7200 if waits[-1:] != [7200] else 0  # quiet until the first long wait is over
    monkeypatch.setattr(escalation, "quiet_wait", night)
    waits.clear()
    e = await urgent_email(oid)
    assert await escalation.follow_up_urgent(oid, e, "deferred_quiet_hours") == "escalated"
    assert waits[:2] == [7200, 1800]
    assert [s.split(":")[0] for _, s in sent] == ["URGENT email", "URGENT email", "Still unanswered after 30 min"]
