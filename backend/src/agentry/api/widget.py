"""Public website-chat API used by the embeddable widget (apps/widget).

Mounted as its own sub-app with open CORS, because it is called from clients' websites. Visitors are anonymous:
an organisation is identified by its public widget key, and each conversation by an unguessable id plus an HMAC
token, so one visitor can never read or post into another's conversation.
"""
import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.agents.runtime import run_turn
from agentry.agents.spec import load_spec
from agentry.auth import client_ip
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.llm.gateway import AllModelsFailed

widget_app = FastAPI(title="Agentry widget API", docs_url=None, redoc_url=None, openapi_url=None)
widget_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                          allow_headers=["Content-Type"], allow_credentials=False)

_hits: dict[str, deque[float]] = defaultdict(deque)
MAX_MESSAGES_PER_CONVERSATION = 60


def _limit(key: str, n: int, window: float) -> None:
    now, q = time.monotonic(), _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many messages, please wait a moment.")
    q.append(now)


def _token(conversation_id: str) -> str:
    return hmac.new(settings.widget_secret.encode(), conversation_id.encode(), hashlib.sha256).hexdigest()[:32]


async def _org_for_key(key: str) -> dict:
    async with system_session() as conn:
        row = (await conn.execute(text("""select s.org_id, s.status, s.brand, s.demo_expires_at, o.name
            from app.org_settings s join auth.organization o on o.id = s.org_id
            left join app.automation_instances a on a.org_id = s.org_id and a.template_key = 'website_chat'
            where s.widget_key = :k and (a.status in ('live', 'approval_mode') or s.status = 'demo')"""),
            {"k": key})).mappings().first()
    if not row:
        raise HTTPException(404, "chat is not enabled for this site")
    if row["demo_expires_at"] is not None and row["demo_expires_at"].timestamp() < time.time():
        raise HTTPException(410, "this demo has expired")
    return dict(row)


@widget_app.get("/{key}")
async def widget_config(key: str) -> dict:
    org = await _org_for_key(key)
    spec = await load_spec(org["org_id"])
    brand = org["brand"] or {}
    return {"business": org["name"], "agent_name": spec.name, "greeting": spec.greeting,
            "color": brand.get("color") or "#c9f24b", "logo": brand.get("logo")}


@widget_app.post("/{key}/conversations", status_code=201)
async def start_conversation(key: str, request: Request) -> dict:
    _limit(f"start:{client_ip(request)}", 10, 600)
    org = await _org_for_key(key)
    spec = await load_spec(org["org_id"])
    async with tenant_session(org["org_id"]) as conn:
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, metadata)
            values (:o, 'web_chat', 'website_chat', 'Website chat', jsonb_build_object('page', cast(:p as text)))
            returning id"""), {"o": org["org_id"], "p": request.headers.get("referer", "")})).scalar_one())
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
            values (:o, :c, 'out', 'agent', :b)"""), {"o": org["org_id"], "c": cid, "b": spec.greeting})
    return {"conversation_id": cid, "token": _token(cid), "greeting": spec.greeting}


class VisitorMessage(BaseModel):
    token: str
    text: Annotated[str, Field(min_length=1, max_length=2000)]


@widget_app.post("/{key}/conversations/{conversation_id}/messages")
async def send_message(key: str, conversation_id: str, m: VisitorMessage, request: Request) -> dict:
    if not hmac.compare_digest(m.token, _token(conversation_id)):
        raise HTTPException(403, "invalid conversation token")
    _limit(f"msg:{client_ip(request)}", 30, 600)
    org = await _org_for_key(key)
    async with tenant_session(org["org_id"]) as conn:
        conv = (await conn.execute(text("""select status, (select count(*) from app.messages where conversation_id = c.id) n
            from app.conversations c where id = :c and channel = 'web_chat'"""), {"c": conversation_id})).first()
    if not conv:
        raise HTTPException(404, "conversation not found")
    if conv.n >= MAX_MESSAGES_PER_CONVERSATION:
        raise HTTPException(429, "This conversation is very long; please contact the business directly.")
    if conv.status == "handed_off":
        async with tenant_session(org["org_id"]) as conn:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
                values (:o, :c, 'in', 'contact', :b)"""), {"o": org["org_id"], "c": conversation_id, "b": m.text})
        return {"reply": None, "status": "handed_off"}
    try:
        result = await run_turn(org["org_id"], conversation_id, m.text)
    except AllModelsFailed:
        return {"reply": "Sorry, I'm having trouble right now. Please try again in a minute.", "booking": None}
    return {"reply": result["reply"], "booking": result["booking"], "handed_off": "handoff_to_human" in result["tools"]}


@widget_app.get("/{key}/conversations/{conversation_id}")
async def history(key: str, conversation_id: str, token: str) -> dict:
    if not hmac.compare_digest(token, _token(conversation_id)):
        raise HTTPException(403, "invalid conversation token")
    org = await _org_for_key(key)
    async with tenant_session(org["org_id"]) as conn:
        rows = (await conn.execute(text("""select id, direction, author, body, created_at, metadata #>> '{sent_by,name}' as by from app.messages
            where conversation_id = :c order by created_at"""), {"c": conversation_id})).mappings().all()
        status = (await conn.execute(text("select status from app.conversations where id = :c"), {"c": conversation_id})).scalar_one_or_none()
    # a person's reply carries their first name, so visitors know when they're talking to a human, not the AI
    return {"status": status, "messages": [{"id": str(r["id"]), "from": "visitor" if r["direction"] == "in" else r["author"], "text": r["body"],
                                            **({"by": (r["by"] or "").split(" ")[0] or None} if r["author"] == "human" else {})}
                                           for r in rows]}
