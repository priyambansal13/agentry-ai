"""Inbox triage improvements, batch A: fraud warnings (#20), your own categories (#7), learned corrections (#8 core),
snooze (#11), saved replies (#12), response time and draft quality (#17, #18), deleting old email text (#4), and sent
Gmail replies recorded."""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from conftest import expect
from sqlalchemy import text

from agentry.automations.inbox_triage import workflow as wf
from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.automations.inbox_triage.insights import baseline_minutes, purge_old_email_text
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def triaged(oid: str, *, sender: str, subject: str, body: str, extra: dict | None = None, draft: bool = True) -> tuple[dict, dict]:
    mid = await ingest_email(oid, sender=sender, subject=subject, body=body, thread_ref=f"local:{uuid.uuid4().hex[:8]}", extra=extra)
    email = await wf.load_email(oid, mid)
    triage = await wf.classify(oid, email)
    await wf.save_triage(oid, email, triage)
    if draft:
        await wf.draft_reply(oid, email, triage | {"needs_reply": True})
    return email, triage


def model_says(monkeypatch, decision: dict) -> list[list[dict]]:
    """The classifier/drafter model returns `decision` (JSON) and the rendered prompts are captured."""
    seen: list[list[dict]] = []

    async def complete(tier, messages, **kw):
        seen.append(messages)
        if kw.get("json_output"):
            return SimpleNamespace(data=dict(decision), text="", mock=False, model="test/model")
        return SimpleNamespace(data=None, text="Hi,\n\nThanks!\n\nTeam", mock=False, model="test/model")
    monkeypatch.setattr(wf, "complete", complete)
    return seen


async def test_fraud_warning_on_changed_bank_details(team_org):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:  # a supplier they know
        await conn.execute(text("insert into app.contacts (org_id, name, email) values (:o, 'Acme', 'billing@acme.com')"), {"o": oid})
    email, triage = await triaged(oid, sender="billing@acrne.com", subject="Invoice 2291 - updated payment details",
                                  body="Hello, please note our bank account details have changed. Kindly pay invoice 2291 of "
                                       "Rs 4,80,000 to the new bank account below and update your records.",
                                  extra={"reply_to": "payments@other-domain.io"})
    assert triage["suspicious"] is True and triage["category"] == "Invoice/Payment" and triage["urgent"] is True
    assert any("bank details" in r for r in triage["risk"]) and any("acme.com" in r for r in triage["risk"])
    assert any("other-domain.io" in r for r in triage["risk"])
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select payload from app.approvals where conversation_id = cast(:c as uuid)"),
                                   {"c": email["conversation_id"]})).scalar_one()
        labels = (await conn.execute(text("select metadata->'labels' from app.conversations where id = cast(:c as uuid)"),
                                     {"c": email["conversation_id"]})).scalar_one()
    assert card["suspicious"] is True and card["risk"] and "Agentry/Suspicious" in labels
    # an ordinary email from the same supplier raises nothing
    _e, ok = await triaged(oid, sender="billing@acme.com", subject="Re: March invoice", body="Thanks, received.", draft=False)
    assert ok["suspicious"] is False and ok["risk"] == []


async def test_own_categories_and_learning_from_corrections(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"custom_categories": ["Supplier", "Job applicant"]}'
            where template_key = 'inbox_triage'"""))
    seen = model_says(monkeypatch, {"category": "Supplier", "urgent": False, "needs_reply": True, "summary": "Price list",
                                    "language": "en"})
    _e, t = await triaged(oid, sender="sales@steelco.example", subject="New price list", body="Attached our 2027 price list.", draft=False)
    assert t["category"] == "Supplier"
    system = seen[-1][0]["content"]
    assert "- Supplier" in system and "- Job applicant" in system and datetime.now(UTC).date().isoformat()[:7] in system
    # a category the business doesn't use is never applied
    model_says(monkeypatch, {"category": "Banana", "urgent": False, "needs_reply": False, "summary": "x"})
    _e, t = await triaged(oid, sender="x@unknown.example", subject="hello", body="hello there", draft=False)
    assert t["category"] != "Banana"
    # the business moved this sender to "Supplier" once: from now on it's filed there, whatever the model thinks
    async with tenant_session(oid) as conn:
        await conn.execute(text("""insert into app.label_corrections (org_id, conversation_id, sender, sender_domain, from_category, to_category)
            values (:o, gen_random_uuid(), 'deals@boltsco.example', 'boltsco.example', 'Promotion', 'Supplier')"""), {"o": oid})
    model_says(monkeypatch, {"category": "Promotion", "urgent": False, "needs_reply": False, "summary": "Offer"})
    _e, t = await triaged(oid, sender="deals@boltsco.example", subject="20% off bolts", body="Big sale on bolts", draft=False)
    assert t["category"] == "Supplier" and t["source"] == "learned"


async def test_snooze_hides_a_card_until_later(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    email, _t = await triaged(oid, sender="client@acme.example", subject="Can we move the meeting?", body="Can we meet Friday instead?")
    async with tenant_session(oid) as conn:
        card = str((await conn.execute(text("select id from app.approvals where conversation_id = cast(:c as uuid)"),
                                       {"c": email["conversation_id"]})).scalar_one())
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    got = {r: (await client.post(f"/org/approvals/{card}/snooze", headers=h[r], json={"until": later})).status_code
           for r in ("finance", "viewer")}
    expect(got, finance=403, viewer=403)
    assert (await client.post(f"/org/approvals/{card}/snooze", headers=h["staff"],
                              json={"until": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()})).status_code == 422
    assert (await client.post(f"/org/approvals/{card}/snooze", headers=h["staff"], json={"until": later})).status_code == 200
    now = (await client.get("/org/approvals", headers=h["owner"])).json()
    assert card not in [i["id"] for i in now["items"]] and now["snoozed"] == 1
    snoozed = (await client.get("/org/approvals?view=snoozed", headers=h["owner"])).json()["items"]
    assert [i["id"] for i in snoozed] == [card]
    from agentry.automations.inbox_triage.escalation import (
        is_handled,  # snoozed = someone saw it: no escalation
    )
    assert await is_handled(oid, email["conversation_id"], email["received_at"]) is True
    await client.post(f"/org/approvals/{card}/snooze", headers=h["staff"], json={"until": None})
    assert card in [i["id"] for i in (await client.get("/org/approvals", headers=h["owner"])).json()["items"]]


async def test_saved_replies(client, team_org, monkeypatch):
    oid, h = await team_org(["inbox_triage"])
    body = {"title": "Audit fees", "body": "Our statutory audit starts at Rs 45,000 + GST, depending on turnover."}
    got = {r: (await client.post("/org/reply-templates", headers=h[r], json=body)).status_code for r in ALL}
    expect(got, owner=201, manager=201, staff=403, finance=403, viewer=403, agentry=201)
    got = {r: (await client.get("/org/reply-templates", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=200, viewer=403, agentry=200)  # finance replies to invoice emails
    items = (await client.get("/org/reply-templates", headers=h["staff"])).json()["items"]
    assert len(items) == 1 and items[0]["title"] == "Audit fees"  # saving the same title again updates it
    seen = model_says(monkeypatch, {"category": "Lead", "urgent": False, "needs_reply": True, "summary": "audit quote", "language": "hi"})
    await triaged(oid, sender="new@prospect.example", subject="Audit quote", body="Audit ke liye kitna charge hai?")
    drafter = seen[-1][1]["content"]
    assert "Audit fees" in drafter and "Rs 45,000" in drafter and "Reply in: Hindi" in drafter
    assert (await client.delete(f"/org/reply-templates/{items[0]['id']}", headers=h["staff"])).status_code == 403
    assert (await client.delete(f"/org/reply-templates/{items[0]['id']}", headers=h["manager"])).status_code == 200


async def test_response_time_and_draft_quality(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    now = datetime.now(UTC)
    async with tenant_session(oid) as conn:
        for minutes in (20, 40, None):  # two answered (20 and 40 min), one still waiting
            cid = (await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject)
                values (:o, 'email', 'inbox_triage', 'q') returning id"""), {"o": oid})).scalar_one()
            t0 = now - timedelta(hours=2)
            await conn.execute(text("insert into app.messages (org_id, conversation_id, direction, author, body, created_at) values (:o, :c, 'in', 'contact', 'hi', :t)"),
                               {"o": oid, "c": cid, "t": t0})
            if minutes:
                await conn.execute(text("insert into app.messages (org_id, conversation_id, direction, author, body, created_at) values (:o, :c, 'out', 'human', 'yes', :t)"),
                                   {"o": oid, "c": cid, "t": t0 + timedelta(minutes=minutes)})
        for status in ("approved", "approved", "edited", "rejected"):
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, status, decided_at, decided_by)
                values (:o, 'reply_draft', 'inbox_triage', 't', 'b', :s, now(), 'someone')"""), {"o": oid, "s": status})
    got = {r: (await client.get("/org/inbox/insights", headers=h[r])).status_code for r in ALL}
    expect(got, **{r: 200 for r in ALL})
    d = (await client.get("/org/inbox/insights", headers=h["owner"])).json()
    if now.day == 1 and now.hour < 2:  # the emails above fell in last month
        return
    assert d["response_time"]["this_month_minutes"] == 30.0 and d["response_time"]["answered"] == 2 and d["response_time"]["unanswered"] == 1
    assert d["drafts_30_days"] == {"sent_as_is": 2, "edited": 1, "discarded": 1, "total": 4, "as_is_pct": 50}


def test_baseline_from_gmail_threads():
    m = 60_000
    threads = [{"messages": [{"internalDate": 0, "labelIds": ["INBOX"]}, {"internalDate": 30 * m, "labelIds": ["SENT"]}]},
               {"messages": [{"internalDate": 0, "labelIds": ["INBOX"]}, {"internalDate": 90 * m, "labelIds": ["SENT"]}]},
               {"messages": [{"internalDate": 0, "labelIds": ["INBOX"]}]}]  # never answered: not in the median
    assert baseline_minutes(threads, until_ms=10**12) == 60.0


async def test_old_email_text_is_deleted_but_waiting_ones_kept(team_org):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"keep_email_text_days": 7}'
            where template_key = 'inbox_triage'"""))
        ids = {}
        for name, waiting in (("old_done", False), ("old_waiting", True)):
            cid = (await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject)
                values (:o, 'email', 'inbox_triage', :s) returning id"""), {"o": oid, "s": name})).scalar_one()
            ids[name] = (await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, created_at)
                values (:o, :c, 'in', 'contact', 'secret contract text', now() - interval '10 days') returning id"""), {"o": oid, "c": cid})).scalar_one()
            if waiting:
                await conn.execute(text("insert into app.approvals (org_id, kind, automation_key, conversation_id, title) values (:o, 'reply_draft', 'inbox_triage', :c, 't')"),
                                   {"o": oid, "c": cid})
    assert await purge_old_email_text() >= 1
    async with tenant_session(oid) as conn:
        rows = dict((await conn.execute(text("select id, body from app.messages where id = any(:i)"), {"i": list(ids.values())})).all())
    assert rows[ids["old_done"]] == "" and rows[ids["old_waiting"]] == "secret contract text"


async def test_reply_sent_from_gmail_is_recorded_once(team_org):
    from agentry.connectors.gmail import record_sent
    oid, _h = await team_org(["inbox_triage"])
    mid = await ingest_email(oid, sender="client@acme.example", subject="Status?", body="Any update?", thread_ref="gmail:T1")
    sent = {"id": "S1", "thread_id": "T1", "body": "Done, sending today.", "internal_ms": int(datetime.now(UTC).timestamp() * 1000)}
    assert await record_sent(oid, sent) is True and await record_sent(oid, sent) is False
    assert await record_sent(oid, sent | {"id": "S2", "thread_id": "UNKNOWN"}) is False  # threads Agentry doesn't know: ignored
    email = await wf.load_email(oid, mid)
    from agentry.automations.inbox_triage.escalation import is_handled
    async with tenant_session(oid) as conn:
        outs = (await conn.execute(text("select metadata->>'sent_from', metadata #>> '{sent_by,name}' from app.messages where direction = 'out'"))).all()
    assert outs == [("gmail", "Sent from Gmail")]
    assert await is_handled(oid, email["conversation_id"], email["received_at"]) is True


def test_never_email_demo_addresses_through_a_real_server(monkeypatch):
    from agentry.config import settings
    from agentry.notify.email import undeliverable
    assert undeliverable("owner@mehtaco.example") is False  # tests use the local Mailpit: everything is delivered
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    assert undeliverable("owner@mehtaco.example") and undeliverable("x@example.com") and undeliverable("a@b.test")
    assert not undeliverable("pooja@gmail.com") and not undeliverable("ceo@example-corp.in")
