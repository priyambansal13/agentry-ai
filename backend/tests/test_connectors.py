"""Gmail and WhatsApp connectors end to end, against fake Google and Meta servers."""
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fakes import FakeProviders
from sqlalchemy import text

from agentry.automations.inbox_triage.workflow import triage_email
from agentry.automations.whatsapp_assistant import answer_whatsapp
from agentry.config import settings
from agentry.connectors import gmail, http
from agentry.db import system_session, tenant_session
from agentry.worker.delivery import deliver_approved_reply

H = lambda login, email, org: login(email) | {"X-Org-Id": org}
APP_SECRET = "test-app-secret"


@pytest.fixture
def fake(monkeypatch):
    f = FakeProviders()
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "gsecret")
    monkeypatch.setattr(settings, "whatsapp_app_secret", APP_SECRET)
    monkeypatch.setattr(settings, "whatsapp_verify_token", "verify-me")
    return f


@pytest.fixture
async def cleanup(orgs):
    yield
    async with system_session() as conn:
        await conn.execute(text("""delete from app.leads where conversation_id in (select id from app.conversations
            where external_ref like 'gmail:%' or external_ref like 'wa:%')"""))
        await conn.execute(text("""delete from app.conversations where external_ref like 'gmail:%' or external_ref like 'wa:%'"""))
        await conn.execute(text("delete from app.contacts where email like '%@brand.example' or email = 'a@b.example'"))
        await conn.execute(text("delete from app.connections"))
        await conn.execute(text("delete from app.automation_instances where template_key = 'whatsapp_assistant'"))
        await conn.execute(text("delete from app.contacts where source = 'whatsapp'"))


async def connect_gmail(client, login, orgs) -> dict:
    owner = H(login, "riya@sharmadigital.example", orgs["sharma-digital"])
    start = (await client.post("/org/connections/gmail/start", headers=owner)).json()
    q = parse_qs(urlparse(start["url"]).query)
    assert q["scope"][0].endswith("gmail.modify") and q["access_type"] == ["offline"]
    r = await client.get("/connect/google/callback", params={"state": q["state"][0], "code": "good-code"})
    return {"redirect": r.headers["location"], "owner": owner}


async def test_gmail_connect_stores_tokens_encrypted(client, login, orgs, fake, cleanup):
    r = await connect_gmail(client, login, orgs)
    assert "connected=gmail" in r["redirect"]
    async with tenant_session(orgs["sharma-digital"]) as conn:
        row = (await conn.execute(text("select account_ref, secret_enc, state from app.connections where provider='gmail'"))).one()
    assert row.account_ref == "owner@sharmadigital.example" and "rt-secret-123" not in row.secret_enc
    listed = (await client.get("/org/connections", headers=r["owner"])).json()
    assert listed["items"][0]["provider"] == "gmail" and "secret" not in json.dumps(listed)


async def test_gmail_callback_rejects_tampered_or_foreign_state(client, login, orgs, fake, cleanup):
    bad = await client.get("/connect/google/callback", params={"state": "abc.def", "code": "good-code"})
    assert "error=" in bad.headers["location"]
    from agentry.secrets import sign_state
    # A Sharma user's state can't attach a mailbox to SmileCraft.
    users = {}
    async with system_session() as conn:
        users = dict((await conn.execute(text('select email, id from auth."user"'))).all())
    forged = sign_state({"org": orgs["smilecraft"], "uid": users["riya@sharmadigital.example"], "p": "gmail"})
    r = await client.get("/connect/google/callback", params={"state": forged, "code": "good-code"})
    assert "no longer have access" in r.headers["location"].replace("+", " ")


async def test_gmail_sync_triage_label_draft_and_send(client, login, orgs, fake, cleanup):
    org = orgs["sharma-digital"]
    r = await connect_gmail(client, login, orgs)
    thread = f"t-{uuid.uuid4().hex[:6]}"
    sender = f"newclient-{uuid.uuid4().hex[:6]}@brand.example"  # unknown sender on every run
    fake.add_email("m-1", thread, sender, "Need a quote for Instagram ads",
                   "Hi, we need Instagram ads management for our cafe chain. What would it cost per month?")
    fake.add_email("m-2", "t-own", "owner@sharmadigital.example", "My own sent mail", "ignore me")
    assert await gmail.sync(org) == 1
    assert await gmail.sync(org) == 0  # nothing new, and m-1 is not ingested twice

    async with tenant_session(org) as conn:
        msg_id = str((await conn.execute(text("select id from app.messages where metadata->>'external_id' = 'gmail:m-1'"))).scalar_one())
    await triage_email({"org_id": org, "payload": {"message_id": msg_id}})

    labelled = dict(fake.modified)["m-1"]["addLabelIds"]
    assert fake.labels["Agentry/Lead"] in labelled
    draft_id, draft = next(iter(fake.drafts.items()))
    mime = fake.draft_mime(draft_id)
    assert draft["threadId"] == thread and mime["In-Reply-To"] == "<m-1@mail.example>"
    assert mime["To"] == sender and mime["Subject"].startswith("Re: Need a quote")

    pending = (await client.get("/org/approvals", headers=r["owner"])).json()["items"]
    item = next(a for a in pending if sender in a["title"])
    final = "Hi! Thanks for reaching out. Our Instagram management starts with a free discovery call. When suits you?"
    assert (await client.post(f"/org/approvals/{item['id']}", headers=r["owner"], json={"action": "approve", "body": final})).status_code == 200
    await deliver_approved_reply({"org_id": org, "payload": {"approval_id": item["id"], "status": "edited", "kind": "reply_draft"}})
    assert fake.sent_drafts == [draft_id]
    assert final in fake.draft_mime(draft_id).get_payload(decode=True).decode()
    async with tenant_session(org) as conn:
        out = (await conn.execute(text("select metadata from app.messages where metadata->>'approval_id' = :a"), {"a": item["id"]})).scalar_one()
    assert out["delivery"] == "sent" and out["external_id"] == f"gmail:sent-{draft_id}"


async def test_gmail_refreshes_expired_access_token(client, login, orgs, fake, cleanup):
    await connect_gmail(client, login, orgs)
    org = orgs["sharma-digital"]
    from agentry.connectors.store import get_connection, update_state
    conn = await get_connection(org, "gmail")
    await update_state(org, conn["id"], secret={**conn["secret"], "expires_at": time.time() - 10})
    fake.add_email("m-9", "t-9", "a@b.example", "hello", "hi there")
    await gmail.sync(org)
    assert fake.refreshes == 1


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def wa_payload(pnid: str, wa_id: str, msg_id: str, text_: str) -> bytes:
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550100100", "phone_number_id": pnid},
        "contacts": [{"profile": {"name": "Meera"}, "wa_id": wa_id}],
        "messages": [{"from": wa_id, "id": msg_id, "timestamp": str(int(time.time())), "type": "text", "text": {"body": text_}}]}}]}]}).encode()


async def test_whatsapp_connect_webhook_and_reply(client, login, orgs, fake, cleanup, faqs):
    org = orgs["smilecraft"]
    await faqs(org, [{"q": "Is parking available?", "a": "Yes, free parking is available behind the clinic."}])
    owner = H(login, "neha@smilecraft.example", org)
    bad = await client.post("/org/connections/whatsapp", headers=owner,
                            json={"phone_number_id": "100200300", "waba_id": "900800", "access_token": "EAAG-wrong-token-000000000"})
    assert bad.status_code == 422
    ok = await client.post("/org/connections/whatsapp", headers=owner,
                           json={"phone_number_id": "100200300", "waba_id": "900800", "access_token": "EAAG-test-token-1234567890"})
    assert ok.json()["display"] == "+1 555 010 0100"

    hs = await client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert hs.text == "42"
    assert (await client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})).status_code == 403

    body = wa_payload("100200300", "919000012345", "wamid.in1", "Is parking available?")
    assert (await client.post("/webhooks/whatsapp", content=body, headers={"content-type": "application/json"})).status_code == 401
    assert (await client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": "sha256=" + "0" * 64})).status_code == 401
    first = (await client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)})).json()
    again = (await client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)})).json()
    assert first["messages"] == 1 and again["messages"] == 0  # redelivery stored once

    async with tenant_session(org) as conn:
        ev = (await conn.execute(text("""select payload from app.events where type = 'whatsapp.received'
            and payload->>'wa_id' = '919000012345' order by id desc limit 1"""))).scalar_one()
    # approval mode (default after connecting): reply waits in Needs you, nothing sent
    await answer_whatsapp({"org_id": org, "payload": ev})
    assert fake.wa_sent == []
    pending = (await client.get("/org/approvals", headers=owner)).json()["items"]
    item = next(a for a in pending if "+919000012345" in a["title"])
    assert "parking" in item["body"].lower()

    # approve -> delivered as WhatsApp text inside the 24h window
    await client.post(f"/org/approvals/{item['id']}", headers=owner, json={"action": "approve", "body": item["body"]})
    await deliver_approved_reply({"org_id": org, "payload": {"approval_id": item["id"], "status": "approved", "kind": "reply_draft"}})
    assert fake.wa_sent[-1]["to"] == "919000012345" and fake.wa_sent[-1]["type"] == "text"

    # live mode: the next message is answered immediately
    async with tenant_session(org) as conn:
        await conn.execute(text("update app.automation_instances set status = 'live' where template_key = 'whatsapp_assistant'"))
    body2 = wa_payload("100200300", "919000012345", "wamid.in2", "Do you take walk-ins?")
    await client.post("/webhooks/whatsapp", content=body2, headers={"x-hub-signature-256": sign(body2)})
    async with tenant_session(org) as conn:
        ev2 = (await conn.execute(text("""select payload from app.events where payload->>'message_id' is not null
            and type = 'whatsapp.received' order by id desc limit 1"""))).scalar_one()
    await answer_whatsapp({"org_id": org, "payload": ev2})
    assert len(fake.wa_sent) == 2 and fake.wa_sent[-1]["type"] == "text" and fake.wa_sent[-1]["text"]["body"]
    async with tenant_session(org) as conn:
        sent = (await conn.execute(text("""select body from app.messages where metadata->>'external_id' = 'wa:wamid.out2'"""))).scalar_one()
    assert sent == fake.wa_sent[-1]["text"]["body"]  # the agent's reply was recorded with Meta's message id

    # delivery status webhook updates the sent message
    status = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "100200300"},
                         "statuses": [{"id": "wamid.out2", "status": "read", "recipient_id": "919000012345"}]}}]}]}).encode()
    assert (await client.post("/webhooks/whatsapp", content=status, headers={"x-hub-signature-256": sign(status)})).json()["statuses"] == 1


async def test_whatsapp_reply_outside_24h_window_is_not_sent(client, login, orgs, fake, cleanup):
    org = orgs["smilecraft"]
    owner = H(login, "neha@smilecraft.example", org)
    await client.post("/org/connections/whatsapp", headers=owner,
                      json={"phone_number_id": "100200301", "waba_id": "900801", "access_token": "EAAG-test-token-1234567890"})
    body = wa_payload("100200301", "919000099999", "wamid.old", "Hello?")
    await client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)})
    async with tenant_session(org) as conn:
        conv = (await conn.execute(text("select id from app.conversations where external_ref = 'wa:919000099999'"))).scalar_one()
        await conn.execute(text("update app.messages set created_at = now() - interval '30 hours' where conversation_id = :c"), {"c": conv})
        aid = (await conn.execute(text("""insert into app.approvals (org_id, kind, conversation_id, title, body, status)
            values (:o, 'reply_draft', :c, 'late reply', 'Sorry for the delay!', 'approved') returning id"""), {"o": org, "c": conv})).scalar_one()
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, :c, 'out', 'human', 'Sorry for the delay!', jsonb_build_object('approval_id', cast(:a as text)))"""),
            {"o": org, "c": conv, "a": str(aid)})
    await deliver_approved_reply({"org_id": org, "payload": {"approval_id": str(aid), "status": "approved", "kind": "reply_draft"}})
    async with tenant_session(org) as conn:
        meta = (await conn.execute(text("select metadata from app.messages where metadata->>'approval_id' = :a"), {"a": str(aid)})).scalar_one()
    assert meta["delivery"] == "failed" and "24-hour" in meta["delivery_error"] and fake.wa_sent == []


async def test_gmail_sync_skips_messages_that_disappeared(client, login, orgs, fake, cleanup):
    """Gmail history can list a message that was deleted (or a draft that was sent) before we fetch it. That must not
    block the sync: before this fix one missing message failed every sync, forever."""
    from agentry.connectors.gmail import sync
    await connect_gmail(client, login, orgs)
    org = orgs["sharma-digital"]
    await sync(org)  # first sync: starts from now
    fake.add_email("m-gone", "t-gone", "a@b.example", "deleted before we looked", "x")
    del fake.messages["m-gone"]
    fake.add_email("m-real", "t-real", "client@brand.example", "Quote please", "Could you send a quote?")
    assert await sync(org) == 1  # the real one is triaged, the missing one skipped
    async with tenant_session(org) as conn:
        c = (await conn.execute(text("select status, last_error from app.connections where provider = 'gmail'"))).one()
    assert c.status == "connected" and c.last_error is None
    assert await sync(org) == 0  # and the history moved past both

