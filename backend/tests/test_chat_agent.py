"""Website chat agent: tool loop, booking through chat, lead capture, handoff, widget security.

The model is scripted (no network): each call returns the next planned step, so the test checks the runtime,
tools, persistence and API, not model quality (that's what `agentry eval` is for)."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from agentry.agents.runtime import run_turn, setup_checkpointer
from agentry.db import tenant_session
from agentry.llm.gateway import LLMResult

IST = ZoneInfo("Asia/Kolkata")


def result(text_: str = "", calls: list[dict] | None = None) -> LLMResult:
    return LLMResult(text_, None, "scripted/model", False, 10, 5, 0.0, 1,
                     [{"id": f"call_{i}", **c} for i, c in enumerate(calls or [])])


class Script:
    """Returns planned results in order; records the tool results the agent saw."""
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    async def __call__(self, tier, messages, **kw):
        self.seen.append([m for m in messages if m["role"] == "tool"])
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


@pytest.fixture(scope="module", autouse=True)
async def checkpointer():
    await setup_checkpointer()


async def new_conversation(org: str) -> str:
    async with tenant_session(org) as conn:
        return str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, external_ref)
            values (:o, 'web_chat', 'website_chat', 'test-chat-' || gen_random_uuid()) returning id"""), {"o": org})).scalar_one())


def next_saturday_10am() -> datetime:
    d = datetime.now(IST).date() + timedelta(days=1)
    while d.weekday() != 5 or d.isoformat() in ("2026-11-08", "2026-11-09"):
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, 10, 0, tzinfo=IST)


async def test_price_question_uses_knowledge(orgs, faqs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    await faqs(org, [{"q": "How much is teeth cleaning?", "a": "Scaling & polishing (cleaning) costs Rs 1500 and takes 45 minutes."}])
    script = Script([
        result(calls=[{"name": "search_knowledge", "arguments": {"query": "cleaning price"}}]),
        lambda msgs: result("Scaling & polishing is Rs 1500 and takes 45 minutes. Would you like to book?"),
    ])
    r = await run_turn(org, conv, "How much is teeth cleaning?", llm=script)
    assert "1500" in r["reply"] and r["tools"] == ["search_knowledge"]
    knowledge_seen = json.loads(script.seen[1][0]["content"])["results"]
    assert isinstance(knowledge_seen, list) and any("1500" in hit["content"] for hit in knowledge_seen)


async def test_full_booking_journey_through_chat(orgs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    sat = next_saturday_10am()
    t1 = Script([
        result(calls=[{"name": "save_lead", "arguments": {"need": "teeth cleaning", "timeline": "this Saturday"}},
                      {"name": "check_availability", "arguments": {"service_key": "cleaning", "date": sat.date().isoformat(),
                                                                   "part_of_day": "morning"}}]),
        lambda msgs: result("Saturday morning I have 10:00 or 10:30 AM. Which suits you?"),
    ])
    r1 = await run_turn(org, conv, "I need a cleaning, Saturday morning if possible", llm=t1)
    slots = json.loads(t1.seen[1][1]["content"])["slots"]
    assert slots[0]["start"] == sat.isoformat() and r1["booking"] is None

    t2 = Script([
        result(calls=[{"name": "book_appointment", "arguments": {"service_key": "cleaning", "start": sat.isoformat(),
                                                                 "name": "Meera Test", "phone": "+91-90000-77701"}},
                      {"name": "save_lead", "arguments": {"qualified": True}}]),
        lambda msgs: result("You're booked! See you Saturday at 10:00 AM."),
    ])
    r2 = await run_turn(org, conv, "10 works. Meera Test, 9000077701", llm=t2)
    assert r2["booking"]["booked"] and r2["booking"]["when"].endswith("10:00 AM")

    async with tenant_session(org) as conn:
        lead = (await conn.execute(text("select stage, qualification from app.leads where conversation_id = :c"), {"c": conv})).one()
        msgs = (await conn.execute(text("select direction from app.messages where conversation_id = :c order by created_at"),
                                   {"c": conv})).scalars().all()
        await conn.execute(text("delete from app.bookings where conversation_id = :c"), {"c": conv})
    assert lead.stage == "booked" and lead.qualification["need"] == "teeth cleaning"
    assert msgs == ["in", "out", "in", "out"]


async def test_checkpoint_carries_context_between_turns(orgs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    captured = {}

    async def first(tier, messages, **kw):
        return result("Sure, what's your name?")

    async def second(tier, messages, **kw):
        captured["history"] = [m["content"] for m in messages if m["role"] in ("user", "assistant")]
        return result("Thanks Ravi!")

    await run_turn(org, conv, "Hi there", llm=first)
    await run_turn(org, conv, "Ravi", llm=second)
    assert captured["history"] == ["Hi there", "Sure, what's your name?", "Ravi"]


async def test_handoff_creates_needs_you_item(orgs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    script = Script([
        result(calls=[{"name": "handoff_to_human", "arguments": {"reason": "Visitor wants to talk to the doctor"}}]),
        lambda msgs: result("I've asked the team to take over; someone will reply here shortly."),
    ])
    await run_turn(org, conv, "I want to talk to a real person", llm=script)
    async with tenant_session(org) as conn:
        status = (await conn.execute(text("select status from app.conversations where id = :c"), {"c": conv})).scalar_one()
        kinds = (await conn.execute(text("select kind from app.approvals where conversation_id = :c"), {"c": conv})).scalars().all()
    assert status == "handed_off" and kinds == ["handoff"]


async def test_runaway_tool_loop_is_capped(orgs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    calls = {"n": 0}

    async def loops(tier, messages, tools=None, **kw):
        calls["n"] += 1
        if tools is None:
            return result("Here's what I found.")
        return result(calls=[{"name": "search_knowledge", "arguments": {"query": "x"}}])

    r = await run_turn(org, conv, "hello", llm=loops)
    assert r["reply"] == "Here's what I found." and calls["n"] == 6  # 5 tool rounds, then forced answer


async def test_widget_api_security(client, orgs):
    async with tenant_session(orgs["smilecraft"]) as conn:
        key = (await conn.execute(text("select widget_key from app.org_settings"))).scalar_one()
    cfg = (await client.get(f"/widget/{key}")).json()
    assert cfg["agent_name"] == "Asha" and "AI assistant" in cfg["greeting"]
    started = (await client.post(f"/widget/{key}/conversations")).json()
    cid, token = started["conversation_id"], started["token"]
    bad = await client.post(f"/widget/{key}/conversations/{cid}/messages", json={"token": "0" * 32, "text": "hi"})
    assert bad.status_code == 403
    assert (await client.get("/widget/wk_does_not_exist")).status_code == 404
    hist = (await client.get(f"/widget/{key}/conversations/{cid}", params={"token": token})).json()
    assert hist["messages"][0]["text"] == started["greeting"]
    # Brightpath has no website chat automation installed: its key must not work.
    async with tenant_session(orgs["brightpath"]) as conn:
        bp = (await conn.execute(text("select widget_key from app.org_settings"))).scalar_one()
    assert (await client.get(f"/widget/{bp}")).status_code == 404
    async with tenant_session(orgs["smilecraft"]) as conn:
        await conn.execute(text("delete from app.conversations where id = :c"), {"c": cid})


async def test_mock_mode_answers_from_knowledge(orgs, faqs):
    org, conv = orgs["smilecraft"], await new_conversation(orgs["smilecraft"])
    await faqs(org, [{"q": "Is parking available?", "a": "Yes, free parking is available behind the clinic."}])
    r = await run_turn(org, conv, "Is parking available?")  # real gateway, no model configured -> mock policy
    assert "parking" in r["reply"].lower() and "Demo mode" in r["reply"]


async def test_widget_works_from_any_client_website(client, orgs):
    """The widget is embedded on clients' own domains: its preflight and calls must pass CORS from any origin,
    while the portal API stays limited to Agentry's own sites."""
    async with tenant_session(orgs["smilecraft"]) as conn:
        key = (await conn.execute(text("select widget_key from app.org_settings"))).scalar_one()
    origin = {"Origin": "https://www.some-clinic.example"}
    pre = await client.options(f"/widget/{key}", headers=origin | {"Access-Control-Request-Method": "POST",
                                                                   "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] in ("*", origin["Origin"])
    got = await client.get(f"/widget/{key}", headers=origin)
    assert got.status_code == 200 and got.headers["access-control-allow-origin"] in ("*", origin["Origin"])
    portal = await client.options("/org/approvals", headers=origin | {"Access-Control-Request-Method": "GET"})
    assert portal.status_code == 400  # the portal API doesn't answer other websites

