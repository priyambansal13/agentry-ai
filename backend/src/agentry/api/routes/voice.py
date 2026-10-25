"""Voice test console (Phase 4.1): talk to your agent in the browser, no phone line needed.

POST /org/voice/test-call creates a test conversation (channel voice, never counted in results) and returns a short-lived
LiveKit token whose room configuration dispatches the `agentry-voice` worker with {org_id, conversation_id}.
"""
import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from livekit import api as lk
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.agents.spec import load_spec
from agentry.auth import OrgContext, client_ip, require
from agentry.config import settings
from agentry.db import tenant_session
from agentry.features import enabled_automations
from agentry.voice.worker import AGENT_NAME, disclosure

router = APIRouter(prefix="/org/voice", tags=["voice"])
CONVERSATIONAL = {"website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"}


@router.post("/test-call", status_code=201)
async def test_call(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        if not CONVERSATIONAL & set(await enabled_automations(conn)):
            raise HTTPException(404, "voice needs a conversational agent (website chat, WhatsApp, receptionist or a lead agent)")
    spec = await load_spec(ctx.org_id)
    async with tenant_session(ctx.org_id) as conn:
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, metadata)
            values (:o, 'voice', 'ai_receptionist', 'Test call', '{"test": true}') returning id"""), {"o": ctx.org_id})).scalar_one())
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
            values (:o, :c, 'out', 'agent', :b)"""), {"o": ctx.org_id, "c": cid, "b": disclosure(spec.business, spec.name)})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="voice.test_call", target_type="conversation", target_id=cid)
    room = f"voice-{cid}"
    token = (lk.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
             .with_identity(f"tester-{ctx.principal.user_id}").with_name(ctx.principal.name or "Tester")
             .with_ttl(timedelta(minutes=30))
             .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
             .with_room_config(lk.RoomConfiguration(name=room, empty_timeout=60, agents=[
                 lk.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=json.dumps({"org_id": ctx.org_id, "conversation_id": cid}))]))
             .to_jwt())
    return {"url": settings.livekit_public_url or settings.livekit_url, "token": token, "room": room, "conversation_id": cid,
            "agent": spec.name}


class VoiceSettings(BaseModel):
    recording_retention_days: int = Field(ge=7, le=730)


@router.get("/settings")
async def get_settings(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        days = (await conn.execute(text("select recording_retention_days from app.org_settings"))).scalar()
    return {"recording_retention_days": days or 90, "recording": settings.voice_record}


@router.put("/settings")
async def put_settings(v: VoiceSettings, request: Request,
                       ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """How long this client keeps call recordings (the daily clean-up deletes older ones)."""
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""insert into app.org_settings (org_id, recording_retention_days) values (:o, :d)
            on conflict (org_id) do update set recording_retention_days = excluded.recording_retention_days"""),
                           {"o": ctx.org_id, "d": v.recording_retention_days})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="voice.settings", target_type="org", target_id=ctx.org_id, ip=client_ip(request),
                           metadata=v.model_dump())
    return v.model_dump()
