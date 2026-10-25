"""Inbox triage improvements, batch B: correcting labels (#8), assigning cards (#9), follow-ups when clients go quiet
(#10), auto-send for trusted categories (#13), and replying in the sender's language (#15)."""
import json
from datetime import UTC, datetime, timedelta

from conftest import expect
from sqlalchemy import text
from test_inbox_batch_a import model_says, triaged

from agentry.automations.inbox_triage import workflow as wf
from agentry.automations.inbox_triage.nudges import suggest_follow_ups
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def test_correct_a_label_and_it_sticks(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    email, t = await triaged(oid, sender="offers@bolts.example", subject="20% off bolts this week", body="Big sale, limited time offer", draft=False)
    assert t["category"] == "Promotion"
    cid = email["conversation_id"]
    got = {r: (await client.post(f"/org/conversations/{cid}/category", headers=h[r], json={"category": "Other"})).status_code
           for r in ("finance", "viewer")}
    expect(got, finance=403, viewer=403)
    assert (await client.post(f"/org/conversations/{cid}/category", headers=h["staff"], json={"category": "Banana"})).status_code == 422
    async with tenant_session(oid) as conn:  # the business has its own "Supplier" category
        await conn.execute(text("""update app.automation_instances set config = config || '{"custom_categories": ["Supplier"]}'
            where template_key = 'inbox_triage'"""))
    r = await client.post(f"/org/conversations/{cid}/category", headers=h["staff"], json={"category": "Supplier"})
    assert r.json() == {"category": "Supplier", "previous": "Promotion"}
    conv = (await client.get(f"/org/conversations/{cid}", headers=h["owner"])).json()
    assert "Agentry/Supplier" in conv["conversation"]["metadata"]["labels"] and "Agentry/Promotion" not in conv["conversation"]["metadata"]["labels"]
    triage = next(m["metadata"]["triage"] for m in conv["messages"] if m["direction"] == "in")
    assert triage["category"] == "Supplier" and triage["original_category"] == "Promotion"
    # the next email from this supplier is filed as Supplier straight away
    _e, t2 = await triaged(oid, sender="offers@bolts.example", subject="New catalogue", body="Our new catalogue, special offer", draft=False)
    assert t2["category"] == "Supplier" and t2["source"] == "learned"


async def test_assign_cards_to_a_person(client, team_org, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("agentry.notify.email.send_email", lambda to, s, b: sent.append((to.split("-")[0], s)))
    oid, h = await team_org(["inbox_triage"])
    email, _t = await triaged(oid, sender="client@acme.example", subject="Board pack", body="Can you send the board pack?")
    async with tenant_session(oid) as conn:
        card = str((await conn.execute(text("select id from app.approvals where conversation_id = cast(:c as uuid)"), {"c": email["conversation_id"]})).scalar_one())
    people = (await client.get("/org/assignees", headers=h["manager"])).json()["items"]
    by_role = {p["role"]: p["id"] for p in people}
    assert set(by_role) == {"owner", "manager", "staff", "finance"}  # viewers can't work cards
    assert (await client.post(f"/org/approvals/{card}/assign", headers=h["manager"], json={"user_id": by_role["finance"]})).status_code == 422  # not an invoice email
    assert (await client.post(f"/org/approvals/{card}/assign", headers=h["viewer"], json={"user_id": by_role["staff"]})).status_code == 403
    assert (await client.post(f"/org/approvals/{card}/assign", headers=h["manager"], json={"user_id": by_role["staff"]})).status_code == 200
    assert len(sent) == 1 and sent[0][0] == "staff" and sent[0][1].endswith("assigned you: Reply to client@acme.example: Board pack")
    mine = {r: [i["id"] for i in (await client.get("/org/approvals?view=mine", headers=h[r])).json()["items"]] for r in ("staff", "owner")}
    assert mine["staff"] == [card] and card not in mine["owner"]  # assigned to someone else: not in the owner's "Mine"
    item = (await client.get("/org/approvals", headers=h["owner"])).json()["items"][0]
    assert item["assigned_name"] == "Staff"


async def quiet_conversation(oid: str, category: str, days_ago: int, *, sender: str = "client@acme.example") -> str:
    async with tenant_session(oid) as conn:
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, metadata)
            values (:o, 'email', 'inbox_triage', 'Proposal for FY27 audit', '{"source": "local"}') returning id"""), {"o": oid})).scalar_one())
        t = datetime.now(UTC) - timedelta(days=days_ago)
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
            values (:o, cast(:c as uuid), 'in', 'contact', 'Please send the proposal', cast(:m as jsonb), :t)"""),
            {"o": oid, "c": cid, "t": t - timedelta(hours=1), "m": json.dumps({"from": sender, "triage": {"category": category}})})
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, created_at)
            values (:o, cast(:c as uuid), 'out', 'human', 'Here is our proposal: Rs 45,000. Shall we go ahead?', :t)"""), {"o": oid, "c": cid, "t": t})
    return cid


async def test_follow_up_when_a_client_goes_quiet(team_org):
    oid, _h = await team_org(["inbox_triage"])
    quiet = await quiet_conversation(oid, "Client", 4)
    recent = await quiet_conversation(oid, "Client", 1)            # not quiet long enough
    promo = await quiet_conversation(oid, "Promotion", 5)          # we don't chase promotions
    assert await suggest_follow_ups(oid) == 1
    async with tenant_session(oid) as conn:
        cards = (await conn.execute(text("select conversation_id::text, title, payload from app.approvals"))).all()
    assert [c[0] for c in cards] == [quiet] and "No reply from client@acme.example in 3 days" in cards[0][1] and cards[0][2]["nudge"]
    assert recent not in [c[0] for c in cards] and promo not in [c[0] for c in cards]
    assert await suggest_follow_ups(oid) == 0  # once per quiet spell
    async with tenant_session(oid) as conn:  # switched off
        await conn.execute(text("""update app.automation_instances set config = config || '{"nudge_after_days": 0}' where template_key = 'inbox_triage'"""))
    await quiet_conversation(oid, "Lead", 6)
    assert await suggest_follow_ups(oid) == 0


async def trusted(oid: str, n: int, category: str = "Client") -> None:
    async with tenant_session(oid) as conn:
        for _ in range(n):
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, status, decided_at, decided_by, payload)
                values (:o, 'reply_draft', 'inbox_triage', 't', 'b', 'approved', now(), 'someone', cast(:p as jsonb))"""),
                {"o": oid, "p": json.dumps({"category": category})})


async def test_auto_send_only_when_trusted(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set status = 'live',
            config = config || '{"auto_send_categories": ["Client"]}' where template_key = 'inbox_triage'"""))
    model_says(monkeypatch, {"category": "Client", "urgent": False, "needs_reply": True, "summary": "thanks", "confidence": 0.92, "language": "en"})

    async def run() -> str:
        email = await wf.load_email(oid, (await triaged(oid, sender="client@acme.example", subject="Got it", body="Received the files, thanks!", draft=False))[0]["message_id"])
        triage = await wf.classify(oid, email)
        approval = await wf.draft_reply(oid, email, triage)
        return await wf.maybe_auto_send(oid, email, triage, approval) or "waits"

    assert await run() == "waits"                      # no track record yet
    await trusted(oid, 10)
    assert await run() == "auto_sent"
    async with tenant_session(oid) as conn:
        auto = (await conn.execute(text("select metadata from app.messages where metadata ? 'auto_sent'"))).scalars().all()
        decided = (await conn.execute(text("select count(*) from app.events where type = 'approval.decided' and payload->>'auto' = 'true'"))).scalar_one()
    assert auto[0]["sent_by"]["name"] == "Sent automatically by Agentry" and decided == 1
    model_says(monkeypatch, {"category": "Client", "urgent": True, "needs_reply": True, "summary": "x", "confidence": 0.95})
    assert await run() == "waits"                      # urgent: always a person
    async with tenant_session(oid) as conn:          # approval mode: always a person
        await conn.execute(text("update app.automation_instances set status = 'approval_mode' where template_key = 'inbox_triage'"))
    model_says(monkeypatch, {"category": "Client", "urgent": False, "needs_reply": True, "summary": "x", "confidence": 0.95})
    assert await run() == "waits"


def test_language_from_script():
    from agentry.automations.inbox_triage.workflow import language_name, script_language
    assert script_language("कृपया मुझे ऑडिट की फीस बताइए") == "hi"
    assert script_language("தயவுசெய்து கட்டணம் சொல்லுங்கள்") == "ta"
    assert script_language("Audit ke liye kitna charge hai?") == "en"  # Hinglish in Latin script
    assert language_name("hi") == "Hindi" and language_name(None) == "English"
