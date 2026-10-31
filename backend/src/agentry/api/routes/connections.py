"""Connecting a client's Gmail and WhatsApp. Tokens go in encrypted and never come back out."""
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, membership_role, require
from agentry.config import settings
from agentry.connectors import gmail, instagram, outlook, whatsapp
from agentry.connectors.http import client
from agentry.connectors.store import get_connection, public_view, save_connection
from agentry.db import tenant_session
from agentry.features import require_connection
from agentry.secrets import SecretError, sign_state, verify_state

router = APIRouter(tags=["connections"])


@router.get("/org/connections")
async def list_connections(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id, provider, account_ref, display_name, status, scopes, last_sync_at,
            last_error, created_at, state->>'assign_to' as assign_to, state->>'alert_template' as alert_template, state->>'url' as url, (state->>'baseline_response_minutes')::numeric as baseline_minutes
            from app.connections where status <> 'revoked' order by provider, created_at"""))).mappings().all()
    return {"items": [dict(r) for r in rows],
            "available": {"gmail": gmail.configured(), "outlook": outlook.configured(),
                          "whatsapp": bool(settings.whatsapp_app_secret and settings.whatsapp_verify_token),
                          "instagram": instagram.configured(), "google_sheets": gmail.configured()},
            "whatsapp_webhook": {"url": settings.api_public_url.rstrip("/") + "/webhooks/whatsapp",
                                 "verify_token_set": bool(settings.whatsapp_verify_token)}}


# ---------- Gmail ----------

@router.post("/org/connections/gmail/start", dependencies=[Depends(require_connection("gmail"))])
async def gmail_start(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    if not gmail.configured():
        raise HTTPException(503, "Gmail isn't set up on this Agentry server yet (Google OAuth client missing)")
    state = sign_state({"org": ctx.org_id, "uid": ctx.principal.user_id, "p": "gmail"})
    return {"url": gmail.auth_url(state, login_hint=ctx.principal.email)}


@router.post("/org/connections/google-sheets/start", dependencies=[Depends(require_connection("google_sheets"))])
async def sheets_start(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    if not gmail.configured():
        raise HTTPException(503, "Google isn't set up on this Agentry server yet (Google OAuth client missing)")
    from agentry.connectors import sheets
    return {"url": sheets.auth_url(sign_state({"org": ctx.org_id, "uid": ctx.principal.user_id, "p": "sheets"}), login_hint=ctx.principal.email)}


async def _sheets_callback(request: Request, s: dict, code: str, back) -> RedirectResponse:
    from agentry.connectors import sheets
    try:
        tokens = await sheets.exchange_code(code)
        async with tenant_session(s["org"]) as conn:
            name = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": s["org"]})).scalar_one_or_none() or "Agentry"
        book = await sheets.create(tokens, s["org"], f"Agentry expenses: {name}")
    except sheets.SheetsError as e:
        hint = " Is the Google Sheets API enabled in the Google Cloud project?" if "403" in str(e) or "disabled" in str(e).lower() else ""
        return back(error=f"{e}{hint}")
    await save_connection(s["org"], provider="google_sheets", account_ref=book["id"], display_name="Agentry expenses", secret=tokens,
                          state={"url": book["url"]}, connected_by=s["uid"])
    async with tenant_session(s["org"]) as conn:
        await audit.record(conn, org_id=s["org"], actor_type="user", actor_user_id=s["uid"], action="connection.google_sheets.connected",
                           target_type="connection", target_id=book["id"], ip=client_ip(request))
        await conn.execute(text("update app.documents set sheet_synced_at = null"))  # the new sheet gets everything filed so far
    from agentry.automations.bookkeeping import push_to_sheets
    await push_to_sheets(s["org"])
    return back(connected="google_sheets", account="Agentry expenses")


@router.get("/connect/google/callback", include_in_schema=False)
async def google_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None):
    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{settings.dashboard_url}/settings/connections?{urlencode(params)}", status_code=303)

    try:
        s = verify_state(state)
    except (SecretError, ValueError):
        return back(error="This sign-in link expired or was tampered with. Please try again.")
    if s.get("p") == "sheets" and code and not error:
        if await membership_role(s["uid"], s["org"]) is None and not await _is_staff(s["uid"]):
            return back(error="You no longer have access to this organisation.")
        return await _sheets_callback(request, s, code, back)
    if error or not code:
        return back(error="Google sign-in was cancelled." if error == "access_denied" else f"Google returned: {error}")
    # The user who started the flow must still be a member (or staff) of the organisation.
    if await membership_role(s["uid"], s["org"]) is None and not await _is_staff(s["uid"]):
        return back(error="You no longer have access to this organisation.")
    try:
        tokens = await gmail.exchange_code(code)
        async with client() as c:
            profile = (await c.get(f"{gmail.API}/profile", headers={"Authorization": f"Bearer {tokens['access_token']}"})).json()
    except gmail.GmailError as e:
        return back(error=str(e))
    email = profile["emailAddress"].lower()
    await save_connection(s["org"], provider="gmail", account_ref=email, display_name=email, secret=tokens,
                          scopes=tokens["scopes"], state={"history_id": profile["historyId"]}, connected_by=s["uid"])
    async with tenant_session(s["org"]) as conn:
        await audit.record(conn, org_id=s["org"], actor_type="user", actor_user_id=s["uid"], action="connection.gmail.connected",
                           target_type="connection", target_id=email, ip=client_ip(request))
        await conn.execute(text("""insert into app.onboarding_progress (org_id, step_key, status, done_by) values (:o, 'connect', 'done', 'client')
            on conflict (org_id, step_key) do update set status = 'done', blocker = null"""), {"o": s["org"]})
    return back(connected="gmail", account=email)


async def _is_staff(user_id: str) -> bool:
    from agentry.db import system_session
    async with system_session() as conn:
        return (await conn.execute(text('select role from auth."user" where id = :u'), {"u": user_id})).scalar_one_or_none() == "admin"


@router.post("/org/connections/gmail/sync", dependencies=[Depends(require_connection("gmail"))])
async def gmail_sync_now(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    try:
        return {"new_emails": await gmail.sync(ctx.org_id)}
    except gmail.GmailError as e:
        raise HTTPException(502, str(e)) from e


# ---------- Instagram (content publishing, 6.5) ----------

@router.post("/org/connections/instagram/start", dependencies=[Depends(require_connection("instagram"))])
async def instagram_start(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    if not instagram.configured():
        raise HTTPException(503, "Instagram isn't set up on this Agentry server yet (Meta app or login configuration missing)")
    return {"url": instagram.auth_url(sign_state({"org": ctx.org_id, "uid": ctx.principal.user_id, "p": "instagram"}))}


@router.get("/connect/instagram/callback", include_in_schema=False)
async def instagram_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None,
                             error_description: str | None = None):
    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{settings.dashboard_url}/settings/connections?{urlencode(params)}", status_code=303)

    try:
        s = verify_state(state)
    except (SecretError, ValueError):
        return back(error="This sign-in link expired or was tampered with. Please try again.")
    if error or not code:
        return back(error="Instagram sign-in was cancelled." if error == "access_denied" else f"Meta returned: {error_description or error}")
    if await membership_role(s["uid"], s["org"]) is None and not await _is_staff(s["uid"]):
        return back(error="You no longer have access to this organisation.")
    try:
        token = await instagram.exchange_code(code)
        found = await instagram.accounts(token["access_token"])
    except instagram.InstagramError as e:
        return back(error=str(e))
    if not found:
        shared = instagram.LAST_SHARED
        detail = (f" Meta shared: {', '.join(f'{k} ({v})' for k, v in shared.get('scopes', {}).items()) or 'no accounts'}."
                  if "scopes" in shared else (f" Meta said: {shared['debug_error']}" if shared.get("debug_error") else ""))
        return back(error="No Instagram professional account was shared. In Meta's window, pick your Instagram account in the "
                          "'Instagram account' list (it must be a Business or Creator account in your business portfolio)." + detail)
    ig = found[0]
    await save_connection(s["org"], provider="instagram", account_ref=ig["id"], display_name=f"@{ig['username']}", secret=token,
                          state={"username": ig["username"], "page": ig["page"], "others": [a["username"] for a in found[1:]]},
                          connected_by=s["uid"])
    async with tenant_session(s["org"]) as conn:
        await audit.record(conn, org_id=s["org"], actor_type="user", actor_user_id=s["uid"], action="connection.instagram.connected",
                           target_type="connection", target_id=ig["id"], ip=client_ip(request), metadata={"username": ig["username"]})
    return back(connected="instagram", account=f"@{ig['username']}")


# ---------- Outlook / Microsoft 365 (#6) ----------

@router.post("/org/connections/outlook/start", dependencies=[Depends(require_connection("outlook"))])
async def outlook_start(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    if not outlook.configured():
        raise HTTPException(503, "Outlook isn't set up on this Agentry server yet (Microsoft app registration missing)")
    state = sign_state({"org": ctx.org_id, "uid": ctx.principal.user_id, "p": "outlook"})
    return {"url": outlook.auth_url(state, login_hint=ctx.principal.email)}


@router.get("/connect/microsoft/callback", include_in_schema=False)
async def microsoft_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None,
                             error_description: str | None = None):
    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{settings.dashboard_url}/settings/connections?{urlencode(params)}", status_code=303)

    try:
        s = verify_state(state)
    except (SecretError, ValueError):
        return back(error="This sign-in link expired or was tampered with. Please try again.")
    if error or not code:
        if error == "access_denied":
            return back(error="Microsoft sign-in was cancelled.")
        if "AADSTS65001" in (error_description or "") or "admin" in (error_description or "").lower():
            return back(error="Your Microsoft 365 admin needs to approve Agentry first (one time). See the setup guide.")
        return back(error=f"Microsoft returned: {error}")
    if await membership_role(s["uid"], s["org"]) is None and not await _is_staff(s["uid"]):
        return back(error="You no longer have access to this organisation.")
    try:
        tokens = await outlook.exchange_code(code)
        async with client() as c:
            me = (await c.get(f"{outlook.API}/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})).json()
    except outlook.OutlookError as e:
        return back(error=str(e))
    email = (me.get("mail") or me.get("userPrincipalName") or "").lower()
    if not email:
        return back(error="Microsoft didn't tell us this account's email address")
    await save_connection(s["org"], provider="outlook", account_ref=email, display_name=email, secret=tokens, scopes=tokens["scopes"],
                          state={}, connected_by=s["uid"])
    async with tenant_session(s["org"]) as conn:
        await audit.record(conn, org_id=s["org"], actor_type="user", actor_user_id=s["uid"], action="connection.outlook.connected",
                           target_type="connection", target_id=email, ip=client_ip(request))
        await conn.execute(text("""insert into app.onboarding_progress (org_id, step_key, status, done_by) values (:o, 'connect', 'done', 'client')
            on conflict (org_id, step_key) do update set status = 'done', blocker = null"""), {"o": s["org"]})
    return back(connected="outlook", account=email)


@router.post("/org/connections/outlook/sync", dependencies=[Depends(require_connection("outlook"))])
async def outlook_sync_now(ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    try:
        return {"new_emails": await outlook.sync(ctx.org_id)}
    except outlook.OutlookError as e:
        raise HTTPException(502, str(e)) from e


# ---------- Gmail push (#5) ----------

@router.post("/webhooks/gmail", include_in_schema=False)
async def gmail_push(request: Request, token: str = "") -> dict:
    """Google Pub/Sub push: Gmail says an inbox changed, so it is synced now instead of at the next minute.
    The push URL carries AGENTRY_GMAIL_PUSH_TOKEN; anything else is refused."""
    import base64
    import hmac
    import json

    from agentry.connectors.store import find_by_account
    from agentry.events import emit
    if not settings.gmail_push_token or not hmac.compare_digest(token, settings.gmail_push_token):
        raise HTTPException(403, "bad token")
    try:
        data = json.loads(base64.b64decode((await request.json())["message"]["data"]))
        account = data["emailAddress"].lower()
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, "not a Gmail push message") from e
    conn = await find_by_account("gmail", account)
    if conn:
        async with tenant_session(conn["org_id"]) as c:
            await emit(c, conn["org_id"], "gmail.push", {"account": account, "history_id": data.get("historyId")})
    return {"ok": True}  # 2xx always for a valid token: otherwise Pub/Sub retries a message we can't use


# ---------- WhatsApp ----------

class WhatsAppCreds(BaseModel):
    phone_number_id: Annotated[str, Field(pattern=r"^\d{5,30}$")]
    waba_id: Annotated[str, Field(pattern=r"^\d{5,30}$")]
    access_token: Annotated[str, Field(min_length=20, max_length=1000)]


class Routing(BaseModel):
    assign_to: str | None = None  # user id: cards from this inbox are assigned to them (#16)


@router.put("/org/connections/{connection_id}/routing")
async def set_routing(connection_id: str, body: Routing, request: Request,
                      ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    """Per-inbox routing: e.g. everything to accounts@ goes to the finance person, sales@ to the front desk."""
    async with tenant_session(ctx.org_id) as conn:
        if body.assign_to and not (await conn.execute(text("""select exists(select 1 from auth.member where "organizationId" = :o
                and "userId" = :u)"""), {"o": ctx.org_id, "u": body.assign_to})).scalar_one():
            raise HTTPException(422, "that person isn't on this team")
        done = (await conn.execute(text("""update app.connections set state = state || jsonb_build_object('assign_to', cast(:u as text))
            where id = cast(:i as uuid) and provider in ('gmail', 'outlook') returning id"""), {"u": body.assign_to, "i": connection_id})).first()
        if not done:
            raise HTTPException(404, "not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="connection.routing", target_type="connection", target_id=connection_id, ip=client_ip(request),
                           metadata={"assign_to": body.assign_to})
    return {"id": connection_id, "assign_to": body.assign_to}


class AlertTemplate(BaseModel):
    template: str | None = Field(None, pattern=r"^[a-z0-9_]{1,512}$")
    language: str = Field("en", pattern=r"^[a-z]{2}(_[A-Z]{2})?$")


@router.put("/org/connections/{connection_id}/alert-template")
async def set_alert_template(connection_id: str, body: AlertTemplate, request: Request,
                             ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    """The Meta-approved template that carries alerts on this WhatsApp number (#3): body "{{1}}" + "{{2}}"
    (title, details). Without it, WhatsApp alerts fall back to email."""
    async with tenant_session(ctx.org_id) as conn:
        done = (await conn.execute(text("""update app.connections set state = (state - 'alert_template' - 'alert_template_language')
            || jsonb_strip_nulls(jsonb_build_object('alert_template', cast(:t as text), 'alert_template_language', cast(:l as text)))
            where id = cast(:i as uuid) and provider = 'whatsapp' returning id"""), {"t": body.template, "l": body.language, "i": connection_id})).first()
        if not done:
            raise HTTPException(404, "not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="connection.alert_template", target_type="connection", target_id=connection_id, ip=client_ip(request),
                           metadata=body.model_dump())
    return body.model_dump()


@router.post("/org/connections/whatsapp", status_code=201, dependencies=[Depends(require_connection("whatsapp"))])
async def connect_whatsapp(body: WhatsAppCreds, request: Request,
                           ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    try:
        info = await whatsapp.verify_number(body.phone_number_id, body.access_token)
    except whatsapp.WhatsAppError as e:
        raise HTTPException(422, str(e)) from e
    display = info.get("display_phone_number")
    await save_connection(ctx.org_id, provider="whatsapp", account_ref=body.phone_number_id,
                          display_name=f"{display} ({info.get('verified_name', '')})".strip(),
                          secret={"access_token": body.access_token}, state={"waba_id": body.waba_id},
                          connected_by=ctx.principal.user_id)
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="connection.whatsapp.connected", target_type="connection", target_id=body.phone_number_id,
                           ip=client_ip(request))
        await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config)
            values (:o, 'whatsapp_assistant', 'approval_mode', '{}') on conflict (org_id, template_key) do nothing"""), {"o": ctx.org_id})
    return {"connected": True, "display": display, "verified_name": info.get("verified_name")}


class TestSend(BaseModel):
    to: Annotated[str, Field(pattern=r"^\+?\d{8,15}$")]


@router.post("/org/connections/whatsapp/test", dependencies=[Depends(require_connection("whatsapp"))])
async def whatsapp_test(body: TestSend, ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    """Sends Meta's built-in hello_world template (allowed outside the 24-hour window, works with test numbers)."""
    try:
        wamid = await whatsapp.send_template(ctx.org_id, body.to.lstrip("+"), "hello_world")
    except whatsapp.WhatsAppError as e:
        raise HTTPException(502, str(e)) from e
    return {"sent": True, "message_id": wamid}


@router.delete("/org/connections/{connection_id}")
async def disconnect(connection_id: str, request: Request, ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        row = (await conn.execute(text("select provider from app.connections where id = :i"), {"i": connection_id})).first()
    if not row:
        raise HTTPException(404, "not found")
    full = await get_connection(ctx.org_id, row.provider)
    if row.provider == "gmail" and full:
        async with client() as c:  # best effort: revoke at Google too
            await c.post("https://oauth2.googleapis.com/revoke", data={"token": full["secret"]["refresh_token"]})
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""update app.connections set status = 'revoked', secret_enc = :blank where id = :i"""),
                           {"i": connection_id, "blank": "revoked"})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"connection.{row.provider}.disconnected", target_type="connection", target_id=connection_id,
                           ip=client_ip(request))
    return {"disconnected": True, "provider": row.provider, "view": public_view({"id": connection_id, "provider": row.provider})}


# ---------- Telegram: the business's own bot, for its customers ----------

class TelegramBot(BaseModel):
    bot_token: Annotated[str, Field(min_length=20, max_length=100, pattern=r"^\d+:[\w-]+$")]


@router.post("/org/connections/telegram", status_code=201, dependencies=[Depends(require_connection("telegram"))])
async def connect_telegram(body: TelegramBot, request: Request, ctx: Annotated[OrgContext, Depends(require("connection", "manage"))]) -> dict:
    """The token BotFather gave the business. Agentry checks it, then receives the bot's messages (webhook or polling)."""
    from agentry.connectors import telegram
    try:
        me = await telegram.get_me(body.bot_token)
    except telegram.TelegramError as e:
        raise HTTPException(422, "Telegram didn't accept that token. Copy it again from @BotFather.") from e
    secret = telegram.new_secret()
    cid = await save_connection(ctx.org_id, provider="telegram", account_ref=str(me["id"]), display_name=f"@{me['username']}",
                                secret={"bot_token": body.bot_token}, state={"webhook_secret": secret, "username": me["username"]},
                                connected_by=ctx.principal.user_id)
    mode = telegram.mode()
    try:
        if mode == "webhook":
            await telegram.set_webhook(body.bot_token, f"{settings.api_public_url.rstrip('/')}/webhooks/telegram/{cid}", secret)
        else:
            await telegram.delete_webhook(body.bot_token)  # polling can't run while a webhook is set
    except telegram.TelegramError as e:
        raise HTTPException(502, f"Connected, but Telegram refused the delivery setup: {e}") from e
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="connection.telegram.connected", target_type="connection", target_id=cid, ip=client_ip(request))
        await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config)
            values (:o, 'telegram_assistant', 'approval_mode', '{}') on conflict (org_id, template_key) do nothing"""), {"o": ctx.org_id})
    return {"connected": True, "username": me["username"], "link": f"https://t.me/{me['username']}", "delivery": mode}
