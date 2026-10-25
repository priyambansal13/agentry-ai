"""Voice test console (Phase 4.1): who may start a test call, and the call token dispatches the voice agent with the
right client and conversation."""
import json

import jwt
from conftest import expect
from sqlalchemy import text

from agentry.agents.spec import AgentSpec
from agentry.db import tenant_session
from agentry.voice.worker import AGENT_NAME

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def test_test_call_permissions_and_dispatch(client, team_org):
    oid, h = await team_org(["website_chat"])
    got = {r: (await client.post("/org/voice/test-call", headers=h[r])).status_code for r in ALL}
    expect(got, owner=201, manager=201, staff=403, finance=403, viewer=403, agentry=201)
    r = (await client.post("/org/voice/test-call", headers=h["owner"])).json()
    claims = jwt.decode(r["token"], options={"verify_signature": False})
    assert claims["video"]["room"] == r["room"] and claims["video"]["roomJoin"] is True
    dispatch = claims["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == AGENT_NAME
    assert json.loads(dispatch["metadata"]) == {"org_id": oid, "conversation_id": r["conversation_id"]}
    async with tenant_session(oid) as conn:
        c = (await conn.execute(text("""select channel, metadata->>'test' as test,
            (select body from app.messages m where m.conversation_id = c.id) as greeting
            from app.conversations c where id = cast(:c as uuid)"""), {"c": r["conversation_id"]})).one()
    assert c.channel == "voice" and c.test == "true" and "AI assistant" in c.greeting and "recorded" in c.greeting


async def test_test_call_needs_a_conversational_agent(client, team_org):
    _oid, h = await team_org(["inbox_triage"])
    assert (await client.post("/org/voice/test-call", headers=h["owner"])).status_code == 404


def test_voice_prompt_is_spoken_style():
    spec = AgentSpec(org_id="o", business="SmileCraft", name="Asha", tone="warm", greeting="Hi", timezone="Asia/Kolkata",
                     qualification=[], qualified_when="x", safety=None, services=[])
    voice, chat = spec.system_prompt("voice"), spec.system_prompt("web_chat")
    assert "phone line" in voice and "under 35 words" in voice and "aloud" in voice
    assert "website chat" in chat and "under 70 words" in chat


async def test_call_summary_and_recording(client, team_org, tmp_path, monkeypatch):
    from agentry.config import settings
    from agentry.voice.summary import summarise
    from agentry.voice.worker import save_recording
    oid, h = await team_org(["website_chat"])
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path / "recordings"))
    cid = (await client.post("/org/voice/test-call", headers=h["owner"])).json()["conversation_id"]
    async with tenant_session(oid) as conn:
        for direction, body in (("in", "How much is a teeth cleaning?"), ("out", "It's fifteen hundred rupees. Shall I book you?")):
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
                values (:o, cast(:c as uuid), :d, :a, :b)"""), {"o": oid, "c": cid, "d": direction, "a": "contact" if direction == "in" else "agent", "b": body})
    # the recording the voice worker hands over is kept under recordings_dir/<org>/<conversation>.ogg
    src = tmp_path / "audio.ogg"
    src.write_bytes(b"OggS" + b"\x00" * 4096)
    rel = await save_recording(oid, cid, src)
    assert rel == f"{oid}/{cid}.ogg" and (tmp_path / "recordings" / rel).is_file()
    assert await save_recording(oid, cid, tmp_path / "missing.ogg") is None
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.conversations set metadata = metadata || jsonb_build_object('recording', cast(:r as text)) where id = cast(:c as uuid)"),
                           {"r": rel, "c": cid})
    # summary (offline fallback in tests): outcome + the caller's request
    data = await summarise(oid, cid)
    assert data["outcome"] == "answered" and "teeth cleaning" in data["summary"]
    conv = (await client.get(f"/org/conversations/{cid}", headers=h["owner"])).json()["conversation"]
    assert conv["metadata"]["call"]["outcome"] == "answered"
    # the recording is streamed to people who may read the conversation
    got = {r: (await client.get(f"/org/conversations/{cid}/recording", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    ok = await client.get(f"/org/conversations/{cid}/recording", headers=h["owner"])
    assert ok.headers["content-type"] == "audio/ogg" and ok.content.startswith(b"OggS")
    async with tenant_session(oid) as conn:  # a path outside the recordings folder is never served
        await conn.execute(text("update app.conversations set metadata = metadata || '{\"recording\": \"../../etc/passwd\"}' where id = cast(:c as uuid)"),
                           {"c": cid})
    assert (await client.get(f"/org/conversations/{cid}/recording", headers=h["owner"])).status_code == 404
