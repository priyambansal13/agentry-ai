"""Onboarding endpoints: profile, persona, knowledge, test chat, go-live gate."""
from sqlalchemy import text

from agentry.db import tenant_session

H = lambda login, email, org: login(email) | {"X-Org-Id": org}


async def test_onboarding_flow_for_a_client_still_setting_up(client, login, orgs):
    """Kaveri bought invoice follow-up only: its steps and go-live checks are about invoices and a channel, not chat."""
    org = orgs["kaveri-industrial"]
    owner = H(login, "natarajan@kaverisupplies.example", org)
    async with tenant_session(org) as conn:
        await conn.execute(text("update app.onboarding_progress set status = 'todo' where step_key = 'profile'"))
    prof = (await client.get("/org/profile", headers=owner)).json()
    assert prof["status"] == "onboarding" and prof["steps"][0]["key"] == "profile"
    assert "test" not in [s["key"] for s in prof["steps"]] and "knowledge" not in [s["key"] for s in prof["steps"]]
    assert (await client.get("/org/knowledge", headers=owner)).status_code == 404  # not part of their plan

    blocked = await client.post("/org/go-live", headers=owner)
    assert blocked.status_code == 409 and "Business profile" in blocked.text and "Gmail or WhatsApp connected" in blocked.text

    assert (await client.patch("/org/profile", headers=owner, json={"phone": "+91-422-0000000", "customer_value": 250000})).status_code == 200
    async with tenant_session(org) as conn:
        await conn.execute(text("""insert into app.connections (org_id, provider, account_ref, status, secret_enc)
            values (:o, 'whatsapp', 'test-kaveri-wa', 'connected', 'x')"""), {"o": org})
    try:
        live = (await client.post("/org/go-live", headers=owner)).json()
        assert live["live"] is True
        async with tenant_session(org) as conn:
            status = (await conn.execute(text("select status from app.org_settings"))).scalar_one()
    finally:
        async with tenant_session(org) as conn:  # restore the seeded state for other tests / demos
            await conn.execute(text("delete from app.connections where account_ref = 'test-kaveri-wa'"))
            await conn.execute(text("update app.org_settings set status = 'onboarding'"))
            await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
            await conn.execute(text("delete from app.onboarding_progress where step_key = 'go_live'"))
            await conn.execute(text("update app.onboarding_progress set status = 'todo' where step_key = 'profile'"))
    assert status == "live"


async def test_knowledge_and_agent_test_for_a_chat_client(client, login, orgs):
    org = orgs["sharma-digital"]  # has the website chat agent
    owner = H(login, "riya@sharmadigital.example", org)
    assert (await client.post("/org/knowledge/faqs", headers=owner,
                              json={"q": "What are your credit terms?", "a": "Standard credit period is 45 days."})).status_code == 201
    try:
        t = (await client.post("/org/agent/test", headers=owner, json={"text": "What are your credit terms?"})).json()
        assert "45 days" in t["reply"]  # mock policy answers from knowledge
        t2 = (await client.post("/org/agent/test", headers=owner, json={"conversation_id": t["conversation_id"], "text": "Thanks"})).json()
        assert t2["conversation_id"] == t["conversation_id"]
    finally:
        async with tenant_session(org) as conn:
            await conn.execute(text("delete from app.conversations where metadata->>'test' = 'true'"))
            await conn.execute(text("delete from app.kb_documents where title = 'What are your credit terms?'"))


async def test_staff_role_cannot_change_profile_or_go_live(client, login, orgs):
    h = H(login, "frontdesk@smilecraft.example", orgs["smilecraft"])
    assert (await client.patch("/org/profile", headers=h, json={"phone": "1"})).status_code == 403
    assert (await client.post("/org/go-live", headers=h)).status_code == 403
    assert (await client.get("/org/profile", headers=h)).status_code == 200
