"""Website chat agent, end to end, for every role.

The visitor chats with the agent -> asks for a person (hand-off) -> people who handle conversations are alerted and
reply from the portal -> the visitor sees the reply in the widget -> the chat is handed back to the agent.

                               owner manager front-desk finance viewer agentry
see chats, hand-offs            ✓     ✓        ✓          –       –      ✓
reply / take over / hand back   ✓     ✓        ✓          –       –      ✓
test the agent, knowledge edit  ✓     ✓        –          –       –      ✓
"hand-off" alerts               on    on       opt-in     –       –
"""
from conftest import expect
from sqlalchemy import text

from agentry.agents.tools import run_tool
from agentry.db import tenant_session
from agentry.notify.alerts import recipient_emails

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
READERS = {"owner": 200, "manager": 200, "staff": 200, "finance": 403, "viewer": 403, "agentry": 200}
ADMINS = {"owner": 200, "manager": 200, "staff": 403, "finance": 403, "viewer": 403, "agentry": 200}


def created(m: dict) -> dict:
    return {r: (201 if c == 200 else c) for r, c in m.items()}


async def test_website_chat_handoff_loop_every_role(client, team_org):
    oid, h = await team_org(["website_chat"])
    async with tenant_session(oid) as conn:
        key = (await conn.execute(text("select widget_key from app.org_settings"))).scalar_one()
    # a visitor starts a chat and talks to the agent (mock mode)
    started = (await client.post(f"/widget/{key}/conversations")).json()
    cid, token = started["conversation_id"], started["token"]
    first = (await client.post(f"/widget/{key}/conversations/{cid}/messages", json={"token": token, "text": "Hi there"})).json()
    assert first["reply"] and not first["handed_off"]
    # the agent decides a person is needed
    await run_tool("handoff_to_human", {"reason": "Wants to discuss a custom package"}, org_id=oid, conversation_id=cid, source="web_chat")
    assert (await client.get(f"/widget/{key}/conversations/{cid}", params={"token": token})).json()["status"] == "handed_off"

    # who sees it
    seen = {r: (await client.get("/org/approvals", headers=h[r])) for r in ALL}
    expect({r: x.status_code for r, x in seen.items()}, **READERS)
    assert any(a["kind"] == "handoff" for a in seen["staff"].json()["items"])
    expect({r: (await client.get(f"/org/conversations/{cid}", headers=h[r])).status_code for r in ALL}, **READERS)
    who = lambda emails: sorted(e.split("-")[0] for e in emails)
    assert who(await recipient_emails(oid, "urgent")) == ["manager", "owner"]

    # while a person handles it, visitor messages wait for them (no AI reply)
    held = (await client.post(f"/widget/{key}/conversations/{cid}/messages", json={"token": token, "text": "Hello? Anyone?"})).json()
    assert held == {"reply": None, "status": "handed_off"}

    # each role tries to reply: only the people who handle conversations can
    got = {r: (await client.post(f"/org/conversations/{cid}/reply", headers=h[r], json={"body": f"Hi, this is {r}."})).status_code
           for r in ALL}
    expect(got, **created(READERS))
    # the visitor sees the replies in the widget, from the team, and the hand-off request is done
    hist = (await client.get(f"/widget/{key}/conversations/{cid}", params={"token": token})).json()
    team = [m["text"] for m in hist["messages"] if m["from"] == "human"]
    assert team == ["Hi, this is owner.", "Hi, this is manager.", "Hi, this is staff.", "Hi, this is agentry."]
    assert all(m.get("id") for m in hist["messages"])
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.approvals where status = 'pending'"))).scalar_one() == 0

    # hand back to the agent: only people who handle conversations; then the agent answers again
    expect({r: (await client.post(f"/org/conversations/{cid}/status", headers=h[r], json={"status": "open"})).status_code
            for r in ("finance", "viewer")}, finance=403, viewer=403)
    assert (await client.post(f"/org/conversations/{cid}/status", headers=h["staff"], json={"status": "open"})).status_code == 200
    back = (await client.post(f"/widget/{key}/conversations/{cid}/messages", json={"token": token, "text": "Thanks!"})).json()
    assert back["reply"]
    # take over again without a hand-off request
    assert (await client.post(f"/org/conversations/{cid}/status", headers=h["manager"], json={"status": "handed_off"})).status_code == 200
    assert (await client.get(f"/widget/{key}/conversations/{cid}", params={"token": token})).json()["status"] == "handed_off"

    async with tenant_session(oid) as conn:
        actions = set((await conn.execute(text("select action from app.audit_log"))).scalars())
    assert {"conversation.handoff", "conversation.replied", "conversation.returned_to_agent", "conversation.taken_over"} <= actions


async def test_website_chat_setup_permissions(client, team_org):
    oid, h = await team_org(["website_chat"])
    expect({r: (await client.post("/org/agent/test", headers=h[r], json={"text": "hello"})).status_code for r in ALL}, **ADMINS)
    expect({r: (await client.post("/org/knowledge/faqs", headers=h[r],
                                  json={"q": "Parking?", "a": "Free parking behind the building."})).status_code for r in ALL},
           **created(ADMINS))
    expect({r: (await client.get("/org/knowledge", headers=h[r])).status_code for r in ALL}, **READERS)
    expect({r: (await client.patch("/org/automations/website_chat/config", headers=h[r], json={})).status_code for r in ALL}, **ADMINS)
    # test chats are marked and never count
    async with tenant_session(oid) as conn:
        tests = (await conn.execute(text("select count(*) from app.conversations where metadata->>'test' = 'true'"))).scalar_one()
    assert tests >= 1
    f = (await client.get("/org/features", headers=h["owner"])).json()
    assert f["steps"] == ["profile", "plan", "team", "connect", "knowledge", "persona", "test", "go_live"]
    assert "invoices" not in f["pages"] and f["connections"] == []
