"""The free website audit on the marketing site (agentry/site_audit.py). No login; limits and captcha in site_audit."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from agentry import instant_demo, site_audit
from agentry.auth import client_ip

router = APIRouter(prefix="/public", tags=["public"])


class AuditIn(BaseModel):
    url: Annotated[str, Field(min_length=4, max_length=200)]
    city: Annotated[str, Field(min_length=2, max_length=80)]
    service: Annotated[str, Field(min_length=2, max_length=80)]
    token: Annotated[str | None, Field(max_length=4000)] = None  # Cloudflare Turnstile
    source: Annotated[str | None, Field(max_length=300)] = None  # utm / gclid from the page
    company_url: str | None = None  # honeypot


@router.post("/audits", status_code=201)
async def start(body: AuditIn, request: Request) -> dict:
    if body.company_url:
        raise HTTPException(422, "please try again")
    ip = client_ip(request)
    if not await site_audit.verify_turnstile(body.token, ip):
        raise HTTPException(400, "the human check didn't pass: please try again")
    try:
        return await site_audit.request(body.url, body.city, body.service, ip=ip, source=body.source)
    except site_audit.AuditRefused as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/audits/{audit_id}")
async def get(audit_id: str) -> dict:
    try:
        a = await site_audit.get(audit_id)
    except Exception as e:
        raise HTTPException(404, "audit not found") from e
    if not a:
        raise HTTPException(404, "audit not found or expired")
    return a


class UnlockIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Annotated[str | None, Field(max_length=32)] = None
    company_url: str | None = None  # honeypot


@router.post("/audits/{audit_id}/report")
async def report(audit_id: str, body: UnlockIn, request: Request) -> dict:
    if body.company_url:
        return {"ok": True}
    from agentry.db import system_session
    async with system_session() as conn:
        if not await site_audit.hit(conn, f"unlock:{site_audit.ip_hash(client_ip(request))}", 10, "1 hour"):
            raise HTTPException(429, "too many requests: try again later")
    try:
        return await site_audit.unlock(audit_id, name=body.name, email=str(body.email), phone=body.phone)
    except site_audit.AuditRefused as e:
        raise HTTPException(e.status, str(e)) from e


# ---------- instant demo (agentry/instant_demo.py) ----------

class TryIn(BaseModel):
    url: Annotated[str, Field(min_length=4, max_length=200)]
    token: Annotated[str | None, Field(max_length=4000)] = None
    source: Annotated[str | None, Field(max_length=300)] = None
    company_url: str | None = None  # honeypot


@router.post("/try", status_code=201)
async def try_start(body: TryIn, request: Request) -> dict:
    if body.company_url:
        raise HTTPException(422, "please try again")
    ip = client_ip(request)
    if not await site_audit.verify_turnstile(body.token, ip):
        raise HTTPException(400, "the human check didn't pass: please try again")
    try:
        return await instant_demo.create(body.url, ip=ip, source=body.source)
    except site_audit.AuditRefused as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/try/{demo_id}")
async def try_get(demo_id: str) -> dict:
    try:
        d = await instant_demo.get(demo_id)
    except Exception as e:
        raise HTTPException(404, "demo not found") from e
    if not d:
        raise HTTPException(404, "demo not found")
    return d


class Msg(BaseModel):
    role: Annotated[str, Field(pattern="^(user|assistant)$")]
    content: Annotated[str, Field(max_length=1000)]


class ChatIn(BaseModel):
    messages: Annotated[list[Msg], Field(min_length=1, max_length=40)]


@router.post("/try/{demo_id}/messages")
async def try_chat(demo_id: str, body: ChatIn, request: Request) -> dict:
    try:
        return await instant_demo.reply(demo_id, [m.model_dump() for m in body.messages], ip=client_ip(request))
    except site_audit.AuditRefused as e:
        raise HTTPException(e.status, str(e)) from e


# ---------- try-it boxes on the agent pages (agentry/playground.py) ----------

class PlayIn(BaseModel):
    input: dict = Field(default_factory=dict)
    token: Annotated[str | None, Field(max_length=4000)] = None  # Turnstile, for the AI-backed boxes
    company_url: str | None = None  # honeypot


@router.get("/playground/{kind}/sample")
async def play_sample(kind: str) -> dict:
    from agentry import playground
    try:
        return playground.sample(kind)
    except playground.TryRefused as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/playground/{kind}")
async def play(kind: str, body: PlayIn, request: Request) -> dict:
    from agentry import playground
    if body.company_url:
        raise HTTPException(422, "please try again")
    try:
        return await playground.run(kind, body.input, ip=client_ip(request), token=body.token)
    except site_audit.AuditRefused as e:
        raise HTTPException(e.status, str(e)) from e
