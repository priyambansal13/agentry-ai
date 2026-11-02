"""Support desk (ROADMAP-V3 A2): tickets from the chat agent and handoffs, order status from the sheet, SLA, ratings."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from agentry.agents.runtime import run_turn, setup_checkpointer
from agentry.agents.tools import tool_defs
from agentry.automations import support_desk as sd
from agentry.db import tenant_session
from agentry.leads import resolve_contact
from agentry.llm.gateway import LLMResult

ORDERS = (b"Order ID,Customer,Mobile,Email,Status,Items,Amount,Expected delivery,Tracking link\n"
          b"SD-1042,Asha Rao,+91 98100 00031,asha@example.com,Shipped,2 x Cotton kurta,2398,05/11/2026,https://track.example/SD1042\n"
          b"SD-1043,Vikram,+91 98100 00032,,Packed,1 x Saree,4500,07/11/2026,\n")


@pytest.fixture(scope="module", autouse=True)
async def checkpointer():
    await setup_checkpointer()


def result(text_: str = "", calls: list[dict] | None = None) -> LLMResult:
    return LLMResult(text_, None, "scripted/model", False, 10, 5, 0.0, 1, [{"id": f"call_{i}", **c} for i, c in enumerate(calls or [])])


class Script:
    def __init__(self, steps):
        self.steps, self.seen, self.tools = list(steps), [], []

    async def __call__(self, tier, messages, **kw):
        self.seen.append([m for m in messages if m["role"] == "tool"])
        self.tools.append([t["function"]["name"] for t in kw.get("tools") or []])
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


async def _conv(oid: str, phone: str) -> str:
    async with tenant_session(oid) as conn:
        k = await resolve_contact(conn, oid, name="Asha Rao", phone=phone, source="whatsapp")
        return str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, contact_id, external_ref)
            values (:o, 'whatsapp', 'whatsapp_assistant', :k, 'wa:' || gen_random_uuid()) returning id"""), {"o": oid, "k": k})).scalar_one())


async def test_order_status_and_a_ticket_from_the_chat(client, team_org):
    oid, h = await team_org(["whatsapp_assistant", "support_desk"])
    r = await client.post("/org/tickets/orders/import", headers=h["manager"], files={"file": ("orders.csv", ORDERS, "text/csv")})
    assert r.json() == {"imported": 2}
    conv = await _conv(oid, "+919810000031")
    script = Script([
        result(calls=[{"name": "order_status", "arguments": {}}]),
        lambda msgs: result("Your order SD-1042 has shipped and should arrive by 5 Nov."),
    ])
    out = await run_turn(oid, conv, "Where is my order?", llm=script, channel="whatsapp", source="whatsapp")
    assert {"order_status", "open_ticket"} <= set(script.tools[0])  # the desk's tools are offered
    seen = script.seen[1][0]["content"]
    assert "SD-1042" in seen and "Shipped" in seen and "SD-1043" not in seen  # only this customer's order
    assert out["reply"].startswith("Your order SD-1042")
    # someone else's order number isn't shown to this customer
    assert (await sd.order_status(oid, conv, "SD-1043"))["found"] is False
    script = Script([
        result(calls=[{"name": "open_ticket", "arguments": {"subject": "Kurta arrived torn", "summary": "One of the two kurtas is torn at the seam.",
                                                           "category": "product", "priority": "high", "order_ref": "SD-1042"}}]),
        lambda msgs: result("I'm sorry! I've opened ticket #1001 and the team will reply here."),
    ])
    await run_turn(oid, conv, "One kurta came torn", llm=script, channel="whatsapp", source="whatsapp")
    t = (await client.get("/org/tickets?status=active", headers=h["staff"])).json()
    assert len(t["items"]) == 1 and t["items"][0]["number"] == 1001 and t["items"][0]["priority"] == "high"
    tid = t["items"][0]["id"]
    assert (await client.get(f"/org/tickets/{tid}", headers=h["viewer"])).status_code == 403  # viewers don't read conversations
    d = (await client.get(f"/org/tickets/{tid}", headers=h["staff"]))
    assert d.status_code == 200, d.text
    d = d.json()
    assert d["order"]["status"] == "Shipped" and len(d["messages"]) == 4
    # a person replies: first response recorded; then resolves it
    assert (await client.post(f"/org/conversations/{conv}/reply", headers=h["staff"], json={"body": "Sorry! A replacement is on its way."})).status_code in (200, 201)
    r = await client.patch(f"/org/tickets/{tid}", headers=h["staff"], json={"status": "resolved", "note": "Replacement sent"})
    assert r.json()["status"] == "resolved"
    assert (await client.patch(f"/org/tickets/{tid}", headers=h["viewer"], json={"status": "open"})).status_code == 403
    d = (await client.get(f"/org/tickets/{tid}", headers=h["owner"])).json()
    assert d["first_response_at"] and d["resolved_at"] and d["notes"][0]["text"] == "Replacement sent"


async def test_handoff_becomes_a_ticket_and_sla_breach_alerts(client, team_org):
    oid, h = await team_org(["whatsapp_assistant", "support_desk"])
    conv = await _conv(oid, "+919810000033")
    script = Script([result(calls=[{"name": "handoff_to_human", "arguments": {"reason": "Customer is upset about a late refund"}}]),
                     lambda msgs: result("A team member will reply here shortly.")])
    await run_turn(oid, conv, "I want to talk to a person NOW", llm=script, channel="whatsapp", source="whatsapp")
    async with tenant_session(oid) as conn:
        t = (await conn.execute(text("select id::text, category, source, sla_due_at from app.tickets"))).mappings().one()
    assert t["category"] == "complaint" and t["source"] == "handoff"
    assert await sd.check_sla(oid, t["sla_due_at"] + timedelta(minutes=1)) == 1
    assert await sd.check_sla(oid, t["sla_due_at"] + timedelta(minutes=30)) == 0  # once
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.approvals where kind = 'escalation' and title like '%past its reply time%'"))).scalar_one() == 1
        assert (await conn.execute(text("select count(*) from app.events where type = 'ticket.sla_breached'"))).scalar_one() == 1
    assert (await client.get("/org/tickets", headers=h["owner"])).json()["stats"]["breached"] == 1


async def test_rating_after_resolving(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(["whatsapp_assistant", "support_desk"])
    conv = await _conv(oid, "+919810000034")
    async with tenant_session(oid) as conn:
        t = await sd.open_ticket(conn, oid, subject="Wrong size", conversation_id=conv, category="product")
        await sd.update_ticket(conn, oid, t["id"], {"status": "resolved"}, user_id=None)
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    assert await sd.ask_ratings(oid) == 1 and "1 (poor) to 5 (great)" in sent[0]
    assert await sd.ask_ratings(oid) == 0
    assert await sd.take_rating(oid, conv, "Thanks") is False
    assert await sd.take_rating(oid, conv, "5") is True
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select csat from app.tickets"))).scalar_one() == 5
    assert (await client.get("/org/tickets", headers=h["owner"])).json()["stats"]["csat"] == 5


def test_tools_follow_the_agents():
    assert "open_ticket" not in [t["function"]["name"] for t in tool_defs(())]
    assert {"order_status", "open_ticket"} <= {t["function"]["name"] for t in tool_defs(("support",))}


async def test_tickets_need_the_agent(client, team_org):
    _oid, h = await team_org(["whatsapp_assistant"])
    assert (await client.get("/org/tickets", headers=h["owner"])).status_code == 404
    assert datetime.now(UTC)  # keep the import used
