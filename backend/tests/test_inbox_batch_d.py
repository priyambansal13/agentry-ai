"""Inbox triage improvements, batch D: Outlook / Microsoft 365 (#6) and Gmail push (#5), against fake Microsoft and
Google APIs (tests/fakes.py)."""
import base64
import json

import pytest
from conftest import expect
from fakes import FakeProviders
from sqlalchemy import text

from agentry.automations.inbox_triage import workflow as wf
from agentry.config import settings
from agentry.connectors import http, outlook
from agentry.db import tenant_session
from agentry.secrets import sign_state

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


@pytest.fixture
def fake(monkeypatch):
    f = FakeProviders()
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "microsoft_client_id", "ms-client")
    monkeypatch.setattr(settings, "microsoft_client_secret", "ms-secret")
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "gsecret")
    return f


async def connect_outlook(client, h, oid: str, uid: str) -> None:
    r = await client.get("/connect/microsoft/callback", params={"state": sign_state({"org": oid, "uid": uid, "p": "outlook"}), "code": "good-code"})
    assert r.status_code == 303 and "connected=outlook" in r.headers["location"], r.headers["location"]


async def test_outlook_end_to_end(client, team_org, fake):
    oid, h = await team_org(["inbox_triage"])
    got = {r: (await client.post("/org/connections/outlook/start", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    url = (await client.post("/org/connections/outlook/start", headers=h["owner"])).json()["url"]
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize") and "Mail.ReadWrite" in url
    owner_id = (await client.get("/org/assignees", headers=h["owner"])).json()["items"]
    uid = next(p["id"] for p in owner_id if p["role"] == "owner")
    await connect_outlook(client, h, oid, uid)
    conns = (await client.get("/org/connections", headers=h["owner"])).json()
    assert [c["account_ref"] for c in conns["items"] if c["provider"] == "outlook"] == ["owner@contoso.example"]
    prof = (await client.get("/org/profile", headers=h["owner"])).json()
    assert {c["key"]: c["done"] for c in prof["go_live_checks"]}["mailbox"] is True  # Outlook counts as the mailbox

    # new mail arrives (with an attachment); it is ingested once, from the inbox only
    fake.add_outlook("AAMk1", "conv-1", "client@acme.example", "Contract renewal", "Can we renew the contract for 2027?",
                     attachments=[{"name": "terms.txt", "contentType": "text/plain", "size": 40,
                                   "contentBytes": base64.b64encode(b"Renewal term: 12 months at Rs 2,40,000").decode()}])
    assert await outlook.sync(oid) == 1 and await outlook.sync(oid) == 0
    async with tenant_session(oid) as conn:
        mid, cid, meta = (await conn.execute(text("""select m.id::text, m.conversation_id::text, m.metadata from app.messages m
            join app.conversations c on c.id = m.conversation_id where c.external_ref = 'outlook:conv-1'"""))).one()
    assert meta["mailbox"] == "owner@contoso.example" and meta["attachments"][0]["text"].startswith("Renewal term")
    # triage: categories in Outlook, a draft made with createReply
    email = await wf.load_email(oid, mid)
    triage = await wf.classify(oid, email)
    await wf.save_triage(oid, email, triage)
    approval = await wf.draft_reply(oid, email, triage | {"needs_reply": True})
    assert "Agentry/" + triage["category"] in fake.ms_categories["AAMk1"]
    assert list(fake.ms_drafts) == ["ms-draft-1"] and fake.ms_drafts["ms-draft-1"]["reply_to"] == "AAMk1"
    # approving sends it from Outlook
    from agentry.worker.delivery import send_approved
    r = await send_approved(oid, {"source": "outlook", "conversation_id": cid, "body": "Yes, happy to renew.", "message_id": None})
    assert r["external_id"].startswith("outlook:") and fake.ms_sent_drafts == ["ms-draft-1"]
    assert fake.ms_drafts["ms-draft-1"]["body"] == "Yes, happy to renew."
    # a reply sent from Outlook itself is recorded (and counts as handled)
    fake.add_outlook("AAMk2", "conv-1", "owner@contoso.example", "RE: Contract renewal", "Sure, sending the papers.", folder="sentitems",
                     at="2026-10-25T11:00:00Z")
    await outlook.sync(oid)
    async with tenant_session(oid) as conn:
        outs = (await conn.execute(text("select metadata->>'sent_from' from app.messages where conversation_id = cast(:c as uuid) and direction = 'out'"),
                                   {"c": cid})).scalars().all()
    assert outs == ["outlook"]
    assert approval


async def test_outlook_admin_consent_message(client, team_org, fake):
    oid, _h = await team_org(["inbox_triage"])
    r = await client.get("/connect/microsoft/callback", params={"state": sign_state({"org": oid, "uid": "x", "p": "outlook"}),
                                                               "error": "consent_required", "error_description": "AADSTS65001: The user or administrator has not consented"})
    assert "admin needs to approve" in r.headers["location"].replace("+", " ")


async def test_gmail_push_triggers_a_sync(client, team_org, fake, monkeypatch):
    from agentry.connectors.gmail import Gmail, watch
    from agentry.connectors.store import save_connection
    oid, _h = await team_org(["inbox_triage"])
    cid = await save_connection(oid, provider="gmail", account_ref="owner@sharmadigital.example", secret={"refresh_token": "rt"})
    monkeypatch.setattr(settings, "gmail_pubsub_topic", "projects/agentry/topics/gmail")
    monkeypatch.setattr(settings, "gmail_push_token", "push-secret")
    from agentry.connectors.store import get_connections
    conn = next(c for c in await get_connections(oid, "gmail") if str(c["id"]) == cid)
    assert (await watch(Gmail(oid, conn)))["expiration"] == "1762000000000"
    assert fake.watches == [{"topicName": "projects/agentry/topics/gmail", "labelIds": ["INBOX", "SENT"], "labelFilterBehavior": "INCLUDE"}]
    data = base64.b64encode(json.dumps({"emailAddress": "owner@sharmadigital.example", "historyId": 1234}).encode()).decode()
    assert (await client.post("/webhooks/gmail", params={"token": "wrong"}, json={"message": {"data": data}})).status_code == 403
    assert (await client.post("/webhooks/gmail", params={"token": "push-secret"}, json={"message": {"data": data}})).status_code == 200
    async with tenant_session(oid) as c:
        ev = (await c.execute(text("select payload from app.events where type = 'gmail.push' order by occurred_at desc limit 1"))).scalar_one()
    assert ev["account"] == "owner@sharmadigital.example"
