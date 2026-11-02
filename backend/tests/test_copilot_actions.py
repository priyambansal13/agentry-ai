"""Business copilot (ROADMAP-V3 C1): requests become a plan of checked steps; nothing runs until a person taps Do it."""
import json
from datetime import date, timedelta

import pytest
from helpers import import_invoices, inv
from sqlalchemy import text

from agentry import copilot, governance
from agentry import copilot_actions as ca
from agentry.db import tenant_session
from agentry.leads import resolve_contact
from agentry.llm.gateway import LLMResult


def say(text_="", calls=None) -> LLMResult:
    return LLMResult(text_, None, "test/model", False, 1, 1, 0.0, 1, [{"id": f"c{i}", **c} for i, c in enumerate(calls or [])])


@pytest.fixture(autouse=True)
def daytime(monkeypatch):
    monkeypatch.setattr(governance, "is_quiet", lambda now, tz: False)


async def test_remind_and_note_planned_then_run(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(["invoice_follow_up", "inbox_triage"])
    await import_invoices(oid, [inv("E-1", date.today() - timedelta(days=10), email="rohan@northstar.example")])
    steps = iter([say(calls=[{"name": "propose_invoice_reminder", "arguments": {"invoice": "E-1"}},
                             {"name": "propose_note", "arguments": {"customer": "nobody-like-this", "note": "x"}}]),
                  say(calls=[{"name": "propose_note", "arguments": {"customer": "rohan@northstar.example", "note": "Promised to pay by Friday"}}]),
                  say("I'll remind Rohan about E-1 with a payment link and note his promise.")])
    seen = []

    async def fake(tier, messages, **kw):
        seen.append([m for m in messages if m["role"] == "tool"])
        return next(steps)
    monkeypatch.setattr(copilot, "complete", fake)
    r = await client.post("/org/ask", headers=h["owner"], json={"question": "remind Rohan about E-1 and note he promised Friday"})
    out = r.json()
    assert len(out["plan"]["steps"]) == 2 and out["plan"]["steps"][0].startswith("Remind") and "E-1" in out["plan"]["steps"][0]
    assert "no customer called" in seen[1][1]["content"]  # the bad proposal came back as an error the model could fix
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "email"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    assert sent == []  # nothing happened while planning
    done = (await client.post(f"/org/copilot/plans/{out['plan']['id']}/run", headers=h["owner"])).json()
    assert [x["ok"] for x in done["results"]] == [True, True] and "invoice E-1" in sent[0]
    assert (await client.post(f"/org/copilot/plans/{out['plan']['id']}/run", headers=h["owner"])).status_code == 409  # only once
    async with tenant_session(oid) as conn:
        notes = (await conn.execute(text("select attributes->'notes' from app.contacts where email_norm = 'rohan@northstar.example'"))).scalar_one()
        steps_audited = (await conn.execute(text("select count(*) from app.audit_log where action = 'copilot.step'"))).scalar_one()
    assert notes[0]["text"] == "Promised to pay by Friday" and steps_audited == 2


async def test_permissions_and_agents_shape_what_can_be_proposed(team_org):
    oid, _h = await team_org(["inbox_triage"])
    staff = copilot.Who(oid, "staff")
    names = {a.name for a in await ca.actions_for(staff)}
    assert "propose_invoice_reminder" not in names and "propose_ticket" not in names  # no money permission; no support desk
    assert (await ca.stage(staff, "propose_invoice_reminder", {"invoice": "E-1"}))["error"]
    viewer = copilot.Who(oid, "viewer")
    assert await ca.actions_for(viewer) == []  # viewers only read


async def test_ambiguous_customer_is_asked_not_guessed(team_org):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        await resolve_contact(conn, oid, name="Rohan Mehta", phone="+919810000091", source="test")
        await resolve_contact(conn, oid, name="Rohan Shah", phone="+919810000092", source="test")
    r = await ca.stage(copilot.Who(oid, "owner"), "propose_message", {"customer": "Rohan", "message": "Hi!"})
    assert "more than one customer" in r["error"] and "Ask which one" in r["error"]
    ok = await ca.stage(copilot.Who(oid, "owner"), "propose_message", {"customer": "+91 98100 00092", "message": "Your order is ready."})
    assert ok["summary"].startswith("Message Rohan Shah")


async def test_no_messages_at_night(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"])
    async with tenant_session(oid) as conn:
        await resolve_contact(conn, oid, name="Asha", phone="+919810000093", source="test")
    who = copilot.Who(oid, "owner")
    staged = await ca.stage(who, "propose_message", {"customer": "Asha", "message": "Hello"})
    pid = await ca.save_plan(who, "message Asha", [staged], None)
    monkeypatch.setattr(governance, "is_quiet", lambda now, tz: True)
    r = await ca.run_plan(who, pid, None)
    assert r["results"][0]["ok"] is False and "9 pm" in r["results"][0]["result"]
    assert json.dumps(r)  # serialisable for the API
