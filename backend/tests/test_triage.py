"""Inbox triage end to end (workflow called directly; the running worker is not involved)."""
import json
import uuid

import httpx
from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.automations.inbox_triage.workflow import triage_email
from agentry.db import tenant_session

with open("../mock-data/inbox-triage/sharma-inbox.jsonl") as f:
    INBOX = [json.loads(line) for line in f]


async def mailpit_latest() -> dict:
    async with httpx.AsyncClient() as c:
        return (await c.get("http://localhost:58025/api/v1/messages?limit=1")).json()


def email(id_: str) -> dict:
    return next(e for e in INBOX if e["id"] == id_)


async def run(org: str, e: dict, ref: str) -> dict:
    msg_id = await ingest_email(org, sender=e["from"], subject=e["subject"], body=e["body"],
                                thread_ref=f"{ref}-{uuid.uuid4().hex[:8]}")
    await triage_email({"org_id": org, "payload": {"message_id": msg_id}})
    async with tenant_session(org) as conn:
        row = (await conn.execute(text("""
            select m.metadata->'triage' as triage, c.metadata as conv, c.id
            from app.messages m join app.conversations c on c.id = m.conversation_id where m.id = :m"""),
            {"m": msg_id})).mappings().one()
        approvals = (await conn.execute(text("select kind, body from app.approvals where conversation_id = :c"),
                                        {"c": row["id"]})).all()
        events = [r.type for r in (await conn.execute(text(
            "select type from app.events where payload->>'conversation_id' = :c or payload->>'lead_id' in "
            "(select id::text from app.leads where conversation_id = :cid)"), {"c": str(row["id"]), "cid": row["id"]})).all()]
    return {"triage": row["triage"], "conv": row["conv"], "approvals": approvals, "events": events}


async def test_urgent_client_email_alerts_owner_and_drafts(orgs, monkeypatch):
    from agentry.automations.inbox_triage import workflow
    monkeypatch.setattr(workflow, "_in_quiet_hours", lambda tz, q: False)

    async def no_recent(org_id: str) -> int:
        return 0

    monkeypatch.setattr(workflow, "recent_alert_count", no_recent)
    before = (await mailpit_latest())["total"]
    r = await run(orgs["sharma-digital"], email("m01"), "test-m01")
    assert r["triage"]["category"] == "Client" and r["triage"]["urgent"] is True
    assert "Agentry/Urgent" in r["conv"]["labels"]
    assert [a.kind for a in r["approvals"]] == ["reply_draft"] and r["conv"]["draft"]
    assert "email.triaged" in r["events"]
    latest = await mailpit_latest()
    assert latest["total"] == before + 1 and latest["messages"][0]["Subject"].startswith("URGENT email")


async def test_new_enquiry_creates_contact_and_lead(orgs):
    sender = f"founder-{uuid.uuid4().hex[:6]}@newbrand.example"  # unknown sender, whatever real data exists
    r = await run(orgs["sharma-digital"], {**email("m04"), "from": sender}, "test-m04")
    assert r["triage"]["category"] == "Lead"
    assert "lead.created" in r["events"]
    async with tenant_session(orgs["sharma-digital"]) as conn:
        lead = (await conn.execute(text("""select l.source, l.stage, c.email from app.leads l
            join app.contacts c on c.id = l.contact_id where c.email = :e"""), {"e": sender})).first()
    assert lead.source == "inbox" and lead.stage == "new"


async def test_gateway_receipt_is_decided_by_rules_without_a_draft(orgs):
    r = await run(orgs["sharma-digital"], email("m09"), "test-m09")
    assert r["triage"]["source"] == "rules" and r["triage"]["category"] == "Invoice/Payment"
    assert r["approvals"] == [] and "invoice.reply" not in r["events"]


async def test_phishing_is_spam_and_never_urgent(orgs):
    r = await run(orgs["sharma-digital"], email("m16"), "test-m16")
    assert r["triage"]["category"] == "Spam" and r["triage"].get("flag") == "phishing" and not r["triage"]["urgent"]


async def test_paused_automation_leaves_email_untouched(orgs):
    org = orgs["sharma-digital"]
    async with tenant_session(org) as conn:
        await conn.execute(text("update app.automation_instances set status = 'paused' where template_key = 'inbox_triage'"))
    try:
        r = await run(org, email("m02"), "test-m02-paused")
        assert r["triage"] is None and r["approvals"] == []
    finally:
        async with tenant_session(org) as conn:
            await conn.execute(text("update app.automation_instances set status = 'live' where template_key = 'inbox_triage'"))


async def test_alerts_are_rate_limited_and_respect_quiet_hours(orgs, monkeypatch):
    from agentry.automations.inbox_triage import workflow
    email = {"timezone": "Asia/Kolkata", "conversation_id": "x", "subject": "s", "from": "f",
             "config": {"quiet_hours": ["21:00", "08:00"], "max_alerts_per_hour": 5, "alert_channel": "email"}}

    async def many(org_id: str) -> int:
        return 5

    monkeypatch.setattr(workflow, "_in_quiet_hours", lambda tz, q: False)
    monkeypatch.setattr(workflow, "recent_alert_count", many)
    assert await workflow.alert_hold(orgs["sharma-digital"], email) == "deferred_rate_limit"
    monkeypatch.setattr(workflow, "_in_quiet_hours", lambda tz, q: True)
    assert await workflow.alert_hold(orgs["sharma-digital"], email) == "deferred_quiet_hours"


def test_quiet_hours_window_crosses_midnight():
    from datetime import datetime as real_datetime

    from agentry.automations.inbox_triage import workflow

    class At:
        @staticmethod
        def now(tz):
            return real_datetime(2026, 10, 24, 23, 30, tzinfo=tz)

    orig = workflow.datetime
    workflow.datetime = At
    try:
        assert workflow._in_quiet_hours("Asia/Kolkata", ["21:00", "08:00"])
        assert not workflow._in_quiet_hours("Asia/Kolkata", ["09:00", "17:00"])
    finally:
        workflow.datetime = orig


async def test_digest_summarises_last_24_hours(orgs):
    from agentry.automations.inbox_triage.digest import build_digest, render_digest
    await run(orgs["sharma-digital"], email("m11"), "test-digest")  # urgent client email, unanswered
    d = await build_digest(orgs["sharma-digital"])
    subject, body = render_digest("Sharma Digital Agency", d)
    assert d["urgent_open"] and "Website down?" in body and "urgent" in subject
