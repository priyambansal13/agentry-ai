"""Ask your business in the portal, personal access tokens, and the Agentry MCP server (ROADMAP-V2 2.6, 9.1 part 2).

MCP: Streamable HTTP, JSON-RPC over POST {api}/mcp with "Authorization: Bearer agt_...". Read-only tools only (the same
as the portal's Ask), each checked against the token owner's current role in that business.
"""
import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit, copilot
from agentry.auth import OrgContext, client_ip, current_org
from agentry.config import settings
from agentry.db import system_session, tenant_session

router = APIRouter()
PROTOCOL = "2025-06-18"


def _who(ctx: OrgContext) -> copilot.Who:
    return copilot.Who(ctx.org_id, ctx.role, ctx.principal.is_staff)


class Question(BaseModel):
    question: Annotated[str, Field(min_length=2, max_length=2000)]
    history: list[dict] = Field(default_factory=list, max_length=12)


@router.post("/org/ask")
async def ask(b: Question, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not ctx.can("dashboard", "read"):
        raise HTTPException(403, "no access")
    out = await copilot.answer(_who(ctx), b.question, b.history)
    return {**out, "can_ask_about": [t.name for t in copilot.tools_for(_who(ctx))]}


# ---------- personal access tokens ----------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/org/api-tokens")
async def list_tokens(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, name, prefix, created_at, last_used_at from app.api_tokens
            where user_id = :u and revoked_at is null order by created_at desc"""), {"u": ctx.principal.user_id})).mappings().all()
    return {"items": [dict(r) for r in rows], "mcp_url": settings.api_public_url.rstrip("/") + "/mcp"}


class NewToken(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=60)]


@router.post("/org/api-tokens", status_code=201)
async def create_token(b: NewToken, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not ctx.can("dashboard", "read"):
        raise HTTPException(403, "no access")
    token = "agt_" + secrets.token_urlsafe(32)
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("select count(*) from app.api_tokens where user_id = :u and revoked_at is null"), {"u": ctx.principal.user_id})).scalar_one()
        if n >= 10:
            raise HTTPException(409, "you have 10 tokens: remove one first")
        tid = (await conn.execute(text("""insert into app.api_tokens (org_id, user_id, name, token_hash, prefix) values (:o, :u, :n, :h, :p)
            returning id::text"""), {"o": ctx.org_id, "u": ctx.principal.user_id, "n": b.name, "h": _hash(token), "p": token[:10]})).scalar_one()
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="api_token.created",
                           target_type="api_token", target_id=tid, ip=client_ip(request), metadata={"name": b.name})
    return {"id": tid, "token": token, "mcp_url": settings.api_public_url.rstrip("/") + "/mcp"}


@router.delete("/org/api-tokens/{tid}")
async def revoke_token(tid: str, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.api_tokens set revoked_at = now() where id = cast(:i as uuid) and user_id = :u
            and revoked_at is null"""), {"i": tid, "u": ctx.principal.user_id})).rowcount
        if n:
            await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="api_token.revoked",
                               target_type="api_token", target_id=tid, ip=client_ip(request))
    if not n:
        raise HTTPException(404, "not found")
    return {"revoked": True}


async def token_owner(authorization: str | None) -> copilot.Who | None:
    """The business and person behind a token, with their role as it is now (None: unknown, revoked or no longer a member)."""
    if not authorization or not authorization.lower().startswith("bearer agt_"):
        return None
    async with system_session() as conn:
        row = (await conn.execute(text("""select t.id, t.org_id, t.user_id, m.role, u.role as platform_role from app.api_tokens t
            join auth."user" u on u.id = t.user_id
            left join auth.member m on m."userId" = t.user_id and m."organizationId" = t.org_id
            where t.token_hash = :h and t.revoked_at is null"""), {"h": _hash(authorization.split(" ", 1)[1].strip())})).mappings().first()
        if not row or (row["role"] is None and row["platform_role"] != "admin"):
            return None
        await conn.execute(text("update app.api_tokens set last_used_at = now() where id = :i"), {"i": row["id"]})
    return copilot.Who(row["org_id"], row["role"], row["platform_role"] == "admin")


# ---------- MCP ----------

def _rpc(id_, result=None, error: tuple[int, str] | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": id_, **({"error": {"code": error[0], "message": error[1]}} if error else {"result": result})}


@router.get("/mcp", include_in_schema=False)
async def mcp_get() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})  # no server-initiated stream


@router.post("/mcp", include_in_schema=False)
async def mcp(request: Request) -> Response:
    who = await token_owner(request.headers.get("authorization"))
    if not who:
        return JSONResponse({"error": "invalid or revoked token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        msg = await request.json()
    except ValueError:
        return JSONResponse(_rpc(None, error=(-32700, "parse error")), status_code=400)
    if isinstance(msg, list):
        out = [r for r in [await _handle(who, m) for m in msg] if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    r = await _handle(who, msg)
    return JSONResponse(r) if r is not None else Response(status_code=202)


async def _handle(who: copilot.Who, m: dict) -> dict | None:
    method, id_ = m.get("method"), m.get("id")
    if id_ is None:  # a notification (e.g. notifications/initialized): nothing to answer
        return None
    if method == "initialize":
        async with tenant_session(who.org_id) as conn:
            name = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": who.org_id})).scalar_one_or_none()
        return _rpc(id_, {"protocolVersion": (m.get("params") or {}).get("protocolVersion") or PROTOCOL,
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "agentry", "title": f"Agentry: {name or 'your business'}", "version": "1.0"},
                          "instructions": f"Read-only facts about {name or 'the business'} from Agentry. Use the tools; amounts are in the business's currency."})
    if method == "ping":
        return _rpc(id_, {})
    if method == "tools/list":
        return _rpc(id_, {"tools": [{"name": t.name, "description": t.description, "annotations": {"readOnlyHint": True},
                                     "inputSchema": {"type": "object", "properties": t.params}} for t in copilot.tools_for(who)]})
    if method == "tools/call":
        p = m.get("params") or {}
        import json
        out = await copilot.call_tool(who, p.get("name", ""), p.get("arguments") or {})
        return _rpc(id_, {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "structuredContent": out, "isError": "error" in out})
    return _rpc(id_, error=(-32601, f"method not found: {method}"))
