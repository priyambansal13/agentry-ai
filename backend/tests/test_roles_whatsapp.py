"""WhatsApp assistant, end to end, for every role, against a fake Meta API.

Customer writes on WhatsApp -> the assistant drafts a reply (approval mode) -> people who handle conversations approve
it -> it is sent from the business's number. Voice notes and "I want a person" go to the team, the assistant goes quiet,
a person replies from the portal, then hands the chat back.

                                 owner manager front-desk finance viewer agentry
connect WhatsApp, send a test     ✓     ✓        –          –       –      ✓
see / approve replies, reply      ✓     ✓        ✓          –       –      ✓
take over / hand back             ✓     ✓        ✓          –       –      ✓
"""
import json
import time

import pytest
from conftest import expect
from fakes import FakeProviders
from sqlalchemy import text
from test_connectors import APP_SECRET, sign, wa_payload

from agentry.automations.whatsapp_assistant import answer_whatsapp
from agentry.config import settings
from agentry.connectors import http
from agentry.db import tenant_session
from agentry.worker.delivery import deliver_approved_reply, deliver_human_reply

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
READERS = {"owner": 200, "manager": 200, "staff": 200, "finance": 403, "viewer": 403, "agentry": 200}
TOKEN = "EAAG-test-token-1234567890"


@pytest.fixture
def meta(monkeypatch):
    f = FakeProviders()
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "whatsapp_app_secret", APP_SECRET)
    return f


async def inbound(client, oid: str, body: bytes) -> dict:
    """Deliver a signed Meta webhook, then run the assistant for the stored message (what the worker does)."""
    assert (await client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)})).status_code == 200
    async with tenant_session(oid) as conn:
        ev = (await conn.execute(text("select payload from app.events where type = 'whatsapp.received' order by id desc limit 1"))).scalar_one()
    await answer_whatsapp({"org_id": oid, "payload": ev})
    return ev


def voice_note(pnid: str, wa_id: str, msg_id: str) -> bytes:
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550100100", "phone_number_id": pnid},
        "contacts": [{"profile": {"name": "Meera"}, "wa_id": wa_id}],
        "messages": [{"from": wa_id, "id": msg_id, "timestamp": str(int(time.time())), "type": "audio", "audio": {"id": "a1"}}]}}]}]}).encode()


async def test_whatsapp_every_role(client, team_org, meta):
    oid, h = await team_org(["whatsapp_assistant"])
    pnid = f"77{int(oid.replace('-', '')[:8], 16) % 10**9}"
    conn_body = {"phone_number_id": pnid, "waba_id": "900900", "access_token": TOKEN}
    got = {r: (await client.post("/org/connections/whatsapp", headers=h[r], json=conn_body)).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    assert (await client.post("/org/connections/whatsapp", headers=h["manager"], json=conn_body)).status_code == 201
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode' where template_key = 'whatsapp_assistant'"))

    # 1. approval mode: each role's own customer writes in; the drafted reply can only be approved by people who handle chats
    wa = {r: f"9198{i:08d}" for i, r in enumerate(ALL)}
    for i, r in enumerate(ALL):
        await inbound(client, oid, wa_payload(pnid, wa[r], f"wamid.q{i}{oid[:4]}", "What are your opening hours?"))
    expect({r: (await client.get("/org/approvals", headers=h[r])).status_code for r in ALL}, **READERS)
    items = (await client.get("/org/approvals", headers=h["owner"])).json()["items"]
    draft_for = {r: next(a for a in items if f"+{wa[r]}" in a["title"]) for r in ALL}
    got = {}
    for r in ALL:
        a = draft_for[r]
        got[r] = (await client.post(f"/org/approvals/{a['id']}", headers=h[r], json={"action": "approve"})).status_code
        if got[r] == 200:
            await deliver_approved_reply({"org_id": oid, "payload": {"approval_id": a["id"], "status": "approved", "kind": "reply_draft"}})
    expect(got, **READERS)
    assert sorted(m["to"] for m in meta.wa_sent) == sorted(wa[r] for r in ("owner", "manager", "staff", "agentry"))

    # 2. a voice note goes to the team; the assistant stays quiet afterwards
    n = len(meta.wa_sent)
    ev = await inbound(client, oid, voice_note(pnid, wa["staff"], f"wamid.v{oid[:4]}"))
    cid = ev["conversation_id"]
    assert len(meta.wa_sent) == n + 1 and "team will reply" in meta.wa_sent[-1]["text"]["body"]  # the busy reply
    await inbound(client, oid, wa_payload(pnid, wa["staff"], f"wamid.q9{oid[:4]}", "Hello??"))
    assert len(meta.wa_sent) == n + 1  # no AI answer while a person is handling it
    handoffs = [a for a in (await client.get("/org/approvals", headers=h["staff"])).json()["items"] if a["kind"] == "handoff"]
    assert handoffs and handoffs[0]["title"].startswith("WhatsApp from +")

    # 3. a person replies from the portal: sent from the business's WhatsApp number
    got = {r: (await client.post(f"/org/conversations/{cid}/reply", headers=h[r], json={"body": f"Hi, {r} here."})).status_code for r in ALL}
    expect(got, owner=201, manager=201, staff=201, finance=403, viewer=403, agentry=201)
    async with tenant_session(oid) as conn:
        mids = list((await conn.execute(text("""select id from app.messages where conversation_id = cast(:c as uuid)
            and author = 'human' and not metadata ? 'approval_id' order by created_at"""),
                                        {"c": cid})).scalars())
    for mid in mids:
        await deliver_human_reply({"org_id": oid, "payload": {"message_id": str(mid), "conversation_id": cid}})
    assert [m["text"]["body"] for m in meta.wa_sent[n + 1:]] == ["Hi, owner here.", "Hi, manager here.", "Hi, staff here.", "Hi, agentry here."]
    async with tenant_session(oid) as conn:
        delivered = list((await conn.execute(text("select metadata->>'delivery' from app.messages where id = any(:m)"), {"m": mids})).scalars())
    assert delivered == ["sent"] * 4

    # 4. hand back: the assistant answers again
    expect({r: (await client.post(f"/org/conversations/{cid}/status", headers=h[r], json={"status": "open"})).status_code
            for r in ("viewer", "finance")}, viewer=403, finance=403)
    assert (await client.post(f"/org/conversations/{cid}/status", headers=h["staff"], json={"status": "open"})).status_code == 200
    await inbound(client, oid, wa_payload(pnid, wa["staff"], f"wamid.q10{oid[:4]}", "Thanks, and do you open on Sundays?"))
    pending = [a for a in (await client.get("/org/approvals", headers=h["owner"])).json()["items"] if a["conversation_id"] == cid]
    assert any(a["kind"] == "reply_draft" for a in pending)


async def test_whatsapp_agent_handoff_is_labelled_whatsapp(client, team_org, meta):
    oid, h = await team_org(["whatsapp_assistant"])
    from agentry.agents.tools import run_tool
    async with tenant_session(oid) as conn:
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, external_ref)
            values (:o, 'whatsapp', 'whatsapp_assistant', 'wa:919999000001') returning id"""), {"o": oid})).scalar_one())
    await run_tool("handoff_to_human", {"reason": "Wants to talk about a refund"}, org_id=oid, conversation_id=cid, source="whatsapp")
    a = next(x for x in (await client.get("/org/approvals", headers=h["staff"])).json()["items"] if x["conversation_id"] == cid)
    assert a["title"] == "WhatsApp customer asked for a person" and a["automation_key"] == "whatsapp_assistant"
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select status from app.conversations where id = cast(:c as uuid)"), {"c": cid})).scalar_one() == "handed_off"
