"""Ask your business + the MCP server: read-only tools under each person's permissions (front desk never sees money,
finance never sees conversations), numbers from the business's own data, personal tokens shown once and revocable,
and the MCP handshake Claude Desktop / ChatGPT use."""
from types import SimpleNamespace

from conftest import expect
from sqlalchemy import create_engine, text
from test_invoice_e2e import go_live_invoice_client

from agentry import copilot
from agentry.config import settings
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


def test_each_role_gets_only_its_tools():
    names = lambda role: {t.name for t in copilot.tools_for(copilot.Who("o", role))}
    assert "overdue_invoices" in names("finance") and "leads_summary" not in names("finance")
    assert "leads_summary" in names("staff") and "money_summary" not in names("staff") and "expenses" not in names("staff")
    assert names("owner") == set(copilot.TOOLS)
    assert {t.name for t in copilot.tools_for(copilot.Who("o", None, staff=True))} == set(copilot.TOOLS)


async def test_tools_read_the_business_and_refuse_outside_permissions(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)
    money = await copilot.call_tool(copilot.Who(oid, "finance"), "money_summary", {"period": "this_month"})
    assert money["open_invoices"] >= 1 and money["currency"] == "INR" and money["outstanding"] > 0
    overdue = await copilot.call_tool(copilot.Who(oid, "owner"), "overdue_invoices", {})
    assert overdue["invoices"] and {"number", "customer", "balance", "days_late"} <= set(overdue["invoices"][0])
    assert await copilot.call_tool(copilot.Who(oid, "staff"), "overdue_invoices", {}) == {"error": "you don't have access to this information"}
    assert (await copilot.call_tool(copilot.Who(oid, "owner"), "drop_tables", {}))["error"].startswith("unknown tool")
    name = overdue["invoices"][0]["customer"][:4]
    assert "open_invoices" in (await copilot.call_tool(copilot.Who(oid, "owner"), "find_customer", {"name": name}))["matches"][0]
    assert "open_invoices" not in (await copilot.call_tool(copilot.Who(oid, "staff"), "find_customer", {"name": name}))["matches"][0]


async def test_a_question_is_answered_through_tools(client, team_org, monkeypatch):
    oid, h = await go_live_invoice_client(client, team_org)
    calls = []

    async def fake(tier, messages, **kw):
        calls.append([t["function"]["name"] for t in kw.get("tools") or []])
        if messages[-1]["role"] == "user":
            return SimpleNamespace(text="", tool_calls=[{"id": "c1", "name": "overdue_invoices", "arguments": {"limit": 3}}], mock=False, model="m")
        return SimpleNamespace(text="Two invoices are overdue; the biggest is E-1.", tool_calls=[], mock=False, model="m")
    monkeypatch.setattr(copilot, "complete", fake)
    out = await copilot.answer(copilot.Who(oid, "finance"), "What's overdue?")
    assert out == {"answer": "Two invoices are overdue; the biggest is E-1.", "tools": ["overdue_invoices"], "model": "m"}
    assert "leads_summary" not in calls[0]  # finance isn't even offered the lead tools
    got = {r: (await client.post("/org/ask", headers=h[r], json={"question": "What's overdue?"})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=200, viewer=200, agentry=200)


async def test_without_a_model_it_routes_by_keywords(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)
    out = await copilot.answer(copilot.Who(oid, "owner"), "how much money is overdue?")
    assert out["tools"] == ["money_summary"] and "overdue" in out["answer"]
    assert (await copilot.answer(copilot.Who(oid, "finance"), "any new leads?"))["tools"] == []  # finance: no lead tools


async def test_tokens_and_the_mcp_server(client, team_org):
    oid, h = await go_live_invoice_client(client, team_org)
    r = await client.post("/org/api-tokens", headers=h["finance"], json={"name": "Claude Desktop"})
    assert r.status_code == 201 and r.json()["token"].startswith("agt_") and r.json()["mcp_url"].endswith("/mcp")
    token, tid = r.json()["token"], r.json()["id"]
    listed = (await client.get("/org/api-tokens", headers=h["finance"])).json()["items"]
    assert [t["name"] for t in listed] == ["Claude Desktop"] and "token" not in listed[0]  # shown once only
    assert (await client.get("/org/api-tokens", headers=h["owner"])).json()["items"] == []  # each person sees their own
    mcp = {"Authorization": f"Bearer {token}"}
    init = (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                          "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})).json()
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}} and init["result"]["serverInfo"]["name"] == "agentry"
    assert (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "method": "notifications/initialized"})).status_code == 202
    tools = (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})).json()["result"]["tools"]
    assert "overdue_invoices" in {t["name"] for t in tools} and "leads_summary" not in {t["name"] for t in tools}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    res = (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                         "params": {"name": "money_summary", "arguments": {"period": "this_month"}}})).json()["result"]
    assert res["isError"] is False and res["structuredContent"]["open_invoices"] >= 1
    denied = (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                            "params": {"name": "leads_summary", "arguments": {}}})).json()["result"]
    assert denied["isError"] is True
    assert (await client.post("/mcp", headers={"Authorization": "Bearer agt_forged"}, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})).status_code == 401
    # a role change applies at once: no longer a member, the token stops working
    owner_db = create_engine(settings.migrate_database_url)
    with owner_db.begin() as c:
        uid = c.execute(text("select user_id from app.api_tokens where id = cast(:i as uuid)"), {"i": tid}).scalar_one()
        c.execute(text('update auth.member set role = \'viewer\' where "userId" = :u and "organizationId" = :o'), {"u": uid, "o": oid})
    assert (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 5, "method": "ping"})).json()["result"] == {}
    assert (await client.delete(f"/org/api-tokens/{tid}", headers=h["finance"])).status_code == 200
    assert (await client.post("/mcp", headers=mcp, json={"jsonrpc": "2.0", "id": 6, "method": "ping"})).status_code == 401
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.audit_log where action like 'api_token.%'"))).scalar_one() == 2
