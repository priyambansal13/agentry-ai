"""`agentry voice`: the LiveKit Agents worker. One job per call.

Pipeline (docs/PHASE-4-VOICE.md §3, option B): speech-to-text -> Agentry's agent brain (agents/runtime.run_turn, the
same LangGraph agent, tools, knowledge and booking as website chat) -> text-to-speech. The worker is dispatched by name
("agentry-voice"), so it only joins calls Agentry routes to it:
- browser test calls: job metadata {org_id, conversation_id} (POST /org/voice/test-call);
- phone calls: job metadata {number} from the number's dispatch rule (voice/telephony.py); the client is the one that
  owns the number, the caller's number (SIP attribute sip.phoneNumber) becomes the conversation's contact.
"""
import json
import logging
import shutil
import time
from pathlib import Path

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, llm
from livekit.plugins import openai, silero
from sqlalchemy import text

from agentry.agents.runtime import run_turn
from agentry.agents.spec import load_spec
from agentry.config import settings
from agentry.connectors.store import find_by_account
from agentry.db import tenant_session
from agentry.events import emit
from agentry.knowledge import format_hits, search
from agentry.leads import resolve_contact
from agentry.llm.gateway import AllModelsFailed

AGENT_NAME = "agentry-voice"
log = logging.getLogger("agentry.voice")


def disclosure(business: str, name: str) -> str:
    return f"Hi, you're speaking with {name}, {business}'s AI assistant. This call may be recorded. How can I help?"


class AgentryVoice(Agent):
    """Every caller turn goes to Agentry's own agent (so tools, knowledge, booking and hand-off behave exactly like chat)."""

    def __init__(self, org_id: str, conversation_id: str, instructions: str) -> None:
        super().__init__(instructions=instructions)
        self.org_id, self.conversation_id = org_id, conversation_id
        self.turn_ms: list[int] = []  # how long the brain took per turn (knowledge + model + tools), for ops alerts
        self.failed_turns = 0  # turns where every model failed and the caller got the fallback line

    async def llm_node(self, chat_ctx: llm.ChatContext, tools, model_settings) -> str:
        said = next((m.text_content for m in reversed(chat_ctx.items)
                     if getattr(m, "type", "message") == "message" and getattr(m, "role", "") == "user" and m.text_content), "")
        if not said.strip():
            return "Sorry, I didn't catch that. Could you say it again?"
        # Look the knowledge up first and hand it over with the question: the agent can usually answer in one model
        # round trip instead of two (decide to search -> search -> answer), which matters on a phone call.
        t0 = time.monotonic()
        hits = await search(self.org_id, said, k=3, min_score=0.3)
        context = ("Knowledge already looked up for this question (answer from it; search again only if it doesn't cover it):\n"
                   + format_hits(hits)) if hits else None
        try:
            r = await run_turn(self.org_id, self.conversation_id, said, source="voice", channel="voice", context=context)
        except AllModelsFailed:
            self.failed_turns += 1
            return "Sorry, I'm having trouble right now. Let me have someone from the team call you back."
        finally:
            self.turn_ms.append(round((time.monotonic() - t0) * 1000))
        return r["reply"]


server = AgentServer(ws_url=settings.livekit_url, api_key=settings.livekit_api_key, api_secret=settings.livekit_api_secret,
                     num_idle_processes=settings.voice_idle_processes,
                     # a dev laptop is always busy (builds, browsers): only a dedicated server should refuse calls on load
                     load_threshold=settings.voice_load_threshold if settings.voice_load_threshold is not None
                     else (0.85 if settings.env == "production" else float("inf")))


async def start_phone_call(number: str | None, caller: str | None) -> tuple[str, str] | None:
    """A call to one of Agentry's numbers: find the client that owns it and open a voice conversation.
    None when the number isn't assigned or the client's receptionist is off or paused."""
    owner = await find_by_account("phone", number) if number else None
    if not owner or owner["status"] != "connected":
        return None
    org_id = owner["org_id"]
    spec = await load_spec(org_id)
    async with tenant_session(org_id) as conn:
        status = (await conn.execute(text("select status from app.automation_instances where template_key = 'ai_receptionist'"))).scalar()
        if status in (None, "paused"):
            return None
        contact_id = await resolve_contact(conn, org_id, phone=caller, source="voice") if caller else None
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, contact_id, subject, metadata)
            values (:o, 'voice', 'ai_receptionist', cast(:k as uuid), :s, cast(:m as jsonb)) returning id"""),
            {"o": org_id, "k": contact_id, "s": f"Call from {caller or 'a hidden number'}",
             "m": json.dumps({"inbound": True, "from": caller, "to": number})})).scalar_one())
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
            values (:o, cast(:c as uuid), 'out', 'agent', :b)"""), {"o": org_id, "c": cid, "b": disclosure(spec.business, spec.name)})
        await emit(conn, org_id, "call.started", {"conversation_id": cid, "from": caller, "to": number})
    return org_id, cid


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    await ctx.connect()
    if "conversation_id" in meta:  # browser test call
        org_id, conversation_id = meta["org_id"], meta["conversation_id"]
    else:  # phone call
        participant = await ctx.wait_for_participant()
        caller = participant.attributes.get("sip.phoneNumber") or None
        number = meta.get("number") or participant.attributes.get("sip.trunkPhoneNumber")
        started = await start_phone_call(number, caller)
        if not started:
            log.warning("phone call to %s not answered: number unassigned or receptionist off", number)
            ctx.shutdown(reason="number not in service")
            return
        org_id, conversation_id = started
        log.info("phone call org=%s from=%s to=%s", org_id, caller, number)
    spec = await load_spec(org_id)
    session = AgentSession(
        stt=openai.STT(model=settings.voice_stt_model, language=settings.voice_language),
        # never called: llm_node above answers every turn; LiveKit only replies when an LLM is configured
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(model=settings.voice_tts_model, voice=settings.voice_tts_voice,
                       instructions=f"Speak warmly and naturally, like a friendly receptionist. Tone: {spec.tone}."),
        vad=silero.VAD.load(),
    )
    started = time.time()
    agent = AgentryVoice(org_id, conversation_id, spec.system_prompt("voice"))

    async def finish(_reason: str = "") -> None:
        """Call over: keep the recording, note the duration, and let the worker write the summary."""
        await session.aclose()  # flushes the recorder
        recorder = session._recorder_io
        saved = await save_recording(org_id, conversation_id, recorder.output_path if recorder else None)
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.conversations set status = 'closed', metadata = metadata || cast(:m as jsonb)
                where id = cast(:c as uuid)"""), {"c": conversation_id, "m": json.dumps(
                    {"duration_seconds": round(time.time() - started), "recording": saved, "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "turns": len(agent.turn_ms), "failed_turns": agent.failed_turns,
                     "latency_ms": {"avg": round(sum(agent.turn_ms) / len(agent.turn_ms)), "max": max(agent.turn_ms)} if agent.turn_ms else None})})
            await emit(conn, org_id, "call.completed", {"conversation_id": conversation_id})
        log.info("voice call ended org=%s conversation=%s recording=%s", org_id, conversation_id, saved)

    ctx.add_shutdown_callback(finish)
    # audio only: traces and logs would go to LiveKit Cloud's observability, which a self-hosted setup doesn't use
    await session.start(agent=agent, room=ctx.room,
                        record={"audio": settings.voice_record, "traces": False, "logs": False})
    await session.say(disclosure(spec.business, spec.name), allow_interruptions=False)
    log.info("voice call started org=%s conversation=%s room=%s", org_id, conversation_id, ctx.room.name)


async def save_recording(org_id: str, conversation_id: str, source: Path | None) -> str | None:
    """Move the call recording (stereo Ogg Opus: caller left, agent right) into Agentry's recordings folder.
    Returns its path relative to settings.recordings_dir, or None if there is nothing to keep."""
    if not source or not Path(source).exists() or Path(source).stat().st_size < 1024:
        return None
    rel = f"{org_id}/{conversation_id}.ogg"
    dest = Path(settings.recordings_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return rel


def main() -> None:
    import sys
    sys.argv = [sys.argv[0], "start"]  # LiveKit's CLI: run as a production worker
    cli.run_app(server)
