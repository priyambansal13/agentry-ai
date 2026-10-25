"""Inbox triage improvements, batch C: writing style from sent mail (#1), attachments read (#14), several inboxes
with routing (#16), WhatsApp alerts (#3) and the weekly summary (#19)."""
import base64
import uuid

from conftest import expect
from sqlalchemy import text
from test_inbox_batch_a import model_says, triaged

from agentry.automations.inbox_triage import style
from agentry.automations.inbox_triage import workflow as wf
from agentry.connectors.store import save_connection
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


def test_style_from_sent_mail():
    body = "Hi Ravi,\n\nDone, sending the file today.\n\nCheers,\nAnita\n\nOn Mon, 3 Mar 2026 Ravi wrote:\n> can you send it?"
    assert style.new_text(body) == "Hi Ravi,\n\nDone, sending the file today.\n\nCheers,\nAnita"
    samples = [f"Hi {n},\n\nSure, will do by Friday.\n\nCheers,\nAnita" for n in ("Ravi", "Meena", "Arjun", "Sam")]
    guide = style.heuristic_style(samples)
    assert 'Greets with "Hi' in guide and "Signs off with \"Anita\"" in guide and "short" in guide


async def test_drafts_follow_the_learned_style(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"])

    async def samples(org_id: str, limit: int = 50) -> list[str]:
        return [f"Hey {n}!\n\nAll sorted, ping me if anything.\n\nAnita" for n in ("Ravi", "Meena", "Arjun")]
    monkeypatch.setattr(style, "sent_samples", samples)
    r = await style.learn_style(oid)
    assert r["learned"] and r["samples"] == 3
    seen = model_says(monkeypatch, {"category": "Client", "urgent": False, "needs_reply": True, "summary": "x", "language": "en"})
    await triaged(oid, sender="client@acme.example", subject="Quick one", body="Can you resend the invoice?")
    drafter = seen[-1][1]["content"]
    assert "How this business writes" in drafter and 'Greets with "Hey' in drafter


async def test_attachments_are_read_and_used(team_org, monkeypatch):
    from agentry.connectors.gmail import _attachments, read_attachments
    payload = {"parts": [{"mimeType": "text/plain", "body": {"data": "x"}},
                         {"filename": "INV-204.txt", "mimeType": "text/plain", "body": {"attachmentId": "A1", "size": 120}},
                         {"filename": "photo.jpg", "mimeType": "image/jpeg", "body": {"attachmentId": "A2", "size": 50_000}}]}
    found = _attachments(payload)
    assert [a["filename"] for a in found] == ["INV-204.txt", "photo.jpg"]

    class G:
        async def call(self, method, path, **kw):
            assert path.endswith("/attachments/A1")  # images are never downloaded
            return {"data": base64.urlsafe_b64encode(b"Invoice INV-204\nAmount due: Rs 58,000\nDue: 30 Nov 2026").decode()}
    files = await read_attachments(G(), "M1", found)
    assert files[0]["text"].startswith("Invoice INV-204") and "text" not in files[1]
    oid, _h = await team_org(["inbox_triage"])
    seen = model_says(monkeypatch, {"category": "Invoice/Payment", "urgent": False, "needs_reply": True, "summary": "invoice", "language": "en"})
    email, _t = await triaged(oid, sender="accounts@vendor.example", subject="Invoice attached", body="Please find our invoice attached.",
                              extra={"attachments": files}, draft=False)
    assert "Amount due: Rs 58,000" in email["body"] and "Amount due: Rs 58,000" in seen[-1][1]["content"]


async def test_several_inboxes_reply_from_the_right_one_and_route(client, team_org):
    from agentry.connectors.gmail import GmailMailbox
    oid, h = await team_org(["inbox_triage"])
    sales = await save_connection(oid, provider="gmail", account_ref="sales@mehta.example", secret={"refresh_token": "r1"})
    accounts = await save_connection(oid, provider="gmail", account_ref="accounts@mehta.example", secret={"refresh_token": "r2"})
    people = {p["role"]: p["id"] for p in (await client.get("/org/assignees", headers=h["owner"])).json()["items"]}
    got = {r: (await client.put(f"/org/connections/{accounts}/routing", headers=h[r], json={"assign_to": people["finance"]})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    email, _t = await triaged(oid, sender="vendor@steel.example", subject="Payment status?", body="Has our invoice been paid?",
                              extra={"mailbox": "accounts@mehta.example", "gmail": {"message_id": "g1", "thread_id": "t1"}})
    async with tenant_session(oid) as conn:
        assigned = (await conn.execute(text("select assigned_to from app.approvals where conversation_id = cast(:c as uuid)"),
                                        {"c": email["conversation_id"]})).scalar_one()
    assert assigned == people["finance"]  # everything to accounts@ goes to the finance person
    g, _meta = await GmailMailbox()._ctx(oid, email["conversation_id"])
    assert g.conn["id"] == accounts and g.conn["account_ref"] == "accounts@mehta.example"  # replies go out from accounts@
    conns = (await client.get("/org/connections", headers=h["owner"])).json()["items"]
    assert {c["account_ref"]: c["assign_to"] for c in conns if c["provider"] == "gmail"} == {
        "sales@mehta.example": None, "accounts@mehta.example": people["finance"]}
    assert sales


async def test_whatsapp_alerts_per_person(client, team_org, monkeypatch):
    from agentry.notify import alerts
    emails, whatsapps = [], []
    monkeypatch.setattr(alerts, "send_email", lambda to, s, b: emails.append(to.split("-")[0]))

    async def send_template(org_id, to, name, language="en", params=None):
        whatsapps.append((to, name, params[0]))
        return "wamid.1"
    monkeypatch.setattr("agentry.connectors.whatsapp.send_template", send_template)
    oid, h = await team_org(["inbox_triage"])
    # no WhatsApp number connected: only email is offered
    assert (await client.get("/org/notifications", headers=h["owner"])).json()["channels"] == ["email"]
    wa = await save_connection(oid, provider="whatsapp", account_ref=f"pn-{uuid.uuid4().hex[:6]}", secret={"access_token": "t"})
    assert (await client.put(f"/org/connections/{wa}/alert-template", headers=h["staff"], json={"template": "agentry_alert"})).status_code == 403
    assert (await client.put(f"/org/connections/{wa}/alert-template", headers=h["owner"], json={"template": "agentry_alert"})).status_code == 200
    me = (await client.get("/org/notifications", headers=h["owner"])).json()
    assert me["channels"] == ["email", "whatsapp"]
    assert (await client.put("/org/notifications/whatsapp", headers=h["owner"], json={"number": "12345"})).status_code == 422
    assert (await client.put("/org/notifications/whatsapp", headers=h["owner"], json={"number": "98765 43210"})).json() == {"whatsapp_to": "+919876543210"}
    await client.put("/org/notifications", headers=h["owner"], json={"urgent": ["whatsapp"]})
    channel = await alerts.send_owner_alert(oid, "URGENT email: Site down", "Client's site is down")
    assert whatsapps == [("+919876543210", "agentry_alert", "URGENT email: Site down")]
    assert emails == ["manager"] and channel == "email+whatsapp"  # the owner on WhatsApp, the manager by email
    # the template is removed: WhatsApp people get email instead, nobody misses it
    await client.put(f"/org/connections/{wa}/alert-template", headers=h["owner"], json={"template": None})
    emails.clear()
    await alerts.send_owner_alert(oid, "URGENT email: again", "x")
    assert sorted(emails) == ["manager", "owner"]


async def test_weekly_summary(team_org, monkeypatch):
    from agentry.automations.inbox_triage import weekly
    sent: list[tuple[str, str]] = []

    async def alert(org_id, subject, body, **kw):
        sent.append((subject, body, kw.get("kind")))
        return "email"
    monkeypatch.setattr(weekly, "send_owner_alert", alert)
    oid, _h = await team_org(["inbox_triage"])
    assert await weekly.send_week(oid) == "quiet week" and sent == []
    for i in range(3):
        await triaged(oid, sender=f"c{i}@acme.example", subject="URGENT: server down" if i == 0 else f"Question {i}", body="please help asap" if i == 0 else "a question", draft=False)
    assert await weekly.send_week(oid) == "email"
    subject, body, kind = sent[0]
    assert subject.startswith("Your week with Agentry: 3 emails sorted") and "Urgent caught: 1" in body and kind == "weekly"
    assert wf  # module import keeps the triage workflow registered
