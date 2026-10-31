"""Conversational agent runtime (LangGraph): one graph, any channel.

    START -> agent --(tool calls?)--> tools -> agent ... -> END

State (the OpenAI-format message list) is checkpointed per conversation in Postgres (schema "agent"), so a
conversation continues across requests and server restarts. The system prompt is rebuilt every turn from the
current AgentSpec, so changes to persona, services or knowledge apply immediately.

The LLM call is injectable (tests script it). With no model configured the gateway returns mock results and a small
rule-based policy answers from the knowledge base, so demos work offline.
"""
import json
import operator
import re
from collections.abc import Awaitable, Callable
from typing import Annotated, TypedDict
from urllib.parse import quote

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from agentry.agents.spec import AgentSpec, load_spec
from agentry.agents.tools import TOOL_DEFS, run_tool
from agentry.config import settings
from agentry.db import tenant_session
from agentry.knowledge import search
from agentry.llm.gateway import LLMResult, complete
from agentry.runs import run

MAX_TOOL_ROUNDS = 5
LLM = Callable[..., Awaitable[LLMResult]]


class ChatState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    tool_rounds: int
    events: Annotated[list[dict], operator.add]  # tool calls made this conversation (for the portal timeline)


def checkpoint_url() -> str:
    return (f"postgresql://agentry_system:{quote(settings.db_system_password, safe='')}@{settings.db_host}:{settings.db_port}/"
            f"{settings.db_name}?options=-csearch_path%3Dagent")


async def setup_checkpointer() -> None:
    async with AsyncPostgresSaver.from_conn_string(checkpoint_url()) as saver:
        await saver.setup()


def build_graph(spec: AgentSpec, *, conversation_id: str, source: str, llm: LLM, channel: str, context: str | None = None):
    async def agent(state: ChatState) -> dict:
        system = spec.system_prompt(channel) + (f"\n\n{context}" if context else "")
        msgs = [{"role": "system", "content": system}, *state["messages"]]
        force_answer = state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS
        res = await llm("voice" if channel == "voice" else "conversation", msgs, org_id=spec.org_id, prompt_key="chat_agent", prompt_version="v1",
                        tools=None if force_answer else TOOL_DEFS, mock_response="")
        if res.mock:
            return {"messages": [{"role": "assistant", "content": await mock_reply(spec, state["messages"])}]}
        if res.tool_calls and not force_answer:
            return {"messages": [{"role": "assistant", "content": res.text or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for c in res.tool_calls]}]}
        return {"messages": [{"role": "assistant", "content": res.text.strip() or "Sorry, could you say that again?"}]}

    async def tools(state: ChatState) -> dict:
        last = state["messages"][-1]
        out, events = [], []
        for call in last.get("tool_calls", []):
            args = json.loads(call["function"]["arguments"] or "{}")
            result = await run_tool(call["function"]["name"], args, org_id=spec.org_id,
                                    conversation_id=conversation_id, source=source)
            out.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
            events.append({"tool": call["function"]["name"], "args": args, "result": result})
        return {"messages": out, "events": events, "tool_rounds": state.get("tool_rounds", 0) + 1}

    def route(state: ChatState) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    g = StateGraph(ChatState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g


AGENT_BY_CHANNEL = {"web_chat": "website_chat", "whatsapp": "whatsapp_assistant", "telegram": "telegram_assistant", "voice": "ai_receptionist"}


async def run_turn(org_id: str, conversation_id: str, user_text: str, *, llm: LLM = complete,
                   source: str = "web_chat", channel: str = "web_chat", persist_inbound: bool = True,
                   persist_reply: bool = True, context: str | None = None) -> dict:
    """One customer message through the agent, recorded as a run (agentry/runs.py)."""
    async with run(org_id, AGENT_BY_CHANNEL.get(channel, channel), "chat.turn", subject=("conversation", conversation_id)) as r:
        out = await _run_turn(org_id, conversation_id, user_text, llm=llm, source=source, channel=channel, persist_inbound=persist_inbound,
                              persist_reply=persist_reply, context=context)
        tools = [t.get("tool") if isinstance(t, dict) else str(t) for t in out.get("tools") or []]
        r.step("answered", tools=tools or None, booked=bool(out.get("booking")))
        return out


async def _run_turn(org_id: str, conversation_id: str, user_text: str, *, llm: LLM = complete,
                    source: str = "web_chat", channel: str = "web_chat", persist_inbound: bool = True,
                    persist_reply: bool = True, context: str | None = None) -> dict:
    """Run one visitor message through the agent and return the reply.

    persist_inbound=False when the channel already stored the inbound message (WhatsApp webhook);
    persist_reply=False when the reply must wait for approval instead of being recorded as sent."""
    spec = await load_spec(org_id)
    async with AsyncPostgresSaver.from_conn_string(checkpoint_url()) as saver:
        graph = build_graph(spec, conversation_id=conversation_id, source=source, llm=llm, channel=channel,
                            context=context).compile(checkpointer=saver)
        config = {"configurable": {"thread_id": f"{org_id}:{conversation_id}"}, "recursion_limit": 2 * MAX_TOOL_ROUNDS + 4}
        before = await graph.aget_state(config)
        n_events = len((before.values or {}).get("events", []))
        final = await graph.ainvoke({"messages": [{"role": "user", "content": user_text}], "tool_rounds": 0}, config)
    reply = final["messages"][-1]["content"]
    new_events = final.get("events", [])[n_events:]
    booking = next((e["result"] for e in new_events if e["tool"] == "book_appointment" and e["result"].get("booked")), None)
    reply_id = None
    async with tenant_session(org_id) as conn:
        if persist_inbound:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
                values (:o, :c, 'in', 'contact', :b)"""), {"o": org_id, "c": conversation_id, "b": user_text})
        if persist_reply:
            # clock_timestamp: the question above was saved in this same transaction (now() would give both the same time)
            reply_id = str((await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
                values (:o, :c, 'out', 'agent', :b, cast(:m as jsonb), clock_timestamp()) returning id"""),
                {"o": org_id, "c": conversation_id, "b": reply,
                 "m": json.dumps({"tools": [{"tool": e["tool"], "args": e["args"]} for e in new_events],
                                  "booking": booking}, default=str)})).scalar_one())
        await conn.execute(text("update app.conversations set last_message_at = now() where id = :c"), {"c": conversation_id})
    return {"reply": reply, "booking": booking, "tools": [e["tool"] for e in new_events], "message_id": reply_id}


# ---------- mock policy: offline demos without a model ----------

# "available" alone is not booking intent ("Is parking available?"), so it is deliberately not in this list.
_BOOK = re.compile(r"\b(book|booking|appointment|slot|schedule|availability|free time|come in)\b", re.IGNORECASE)


async def mock_reply(spec: AgentSpec, messages: list[dict]) -> str:
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    hits = await search(spec.org_id, user, k=1, min_score=0.15)
    if hits and not _BOOK.search(user):
        answer = hits[0].content.split("A: ", 1)[-1].strip()
        return f"{answer[:300]} (Demo mode: an AI model isn't connected yet.)"
    if _BOOK.search(user) and spec.services:
        from agentry.booking import availability
        slots, tz, svc = await availability(spec.org_id, spec.services[0]["key"], limit=3)
        if slots:
            return (f"I can book a {svc['name'].lower()} for you. The next free times are "
                    + ", ".join(s.label(tz) for s in slots) + ". (Demo mode: an AI model isn't connected yet.)")
    asked = sum(1 for m in messages if m["role"] == "assistant")
    if asked < len(spec.qualification):
        return spec.qualification[asked]["question"] + " (Demo mode: an AI model isn't connected yet.)"
    return "Thanks! A member of the team will follow up with you. (Demo mode: an AI model isn't connected yet.)"

