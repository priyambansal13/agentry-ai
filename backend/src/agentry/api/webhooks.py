"""Provider webhooks (public). Each request is authenticated by the provider's signature, never by our auth."""
import hashlib
import hmac
import json
import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from agentry.config import settings
from agentry.connectors import whatsapp
from agentry.connectors.store import get_connection
from agentry.db import system_session, tenant_session
from agentry.invoices import apply_payment, match_invoice

router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)


@router.get("/whatsapp")
async def whatsapp_verify(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                          challenge: str = Query("", alias="hub.challenge")) -> PlainTextResponse:
    """Meta's subscription handshake: echo the challenge if the verify token matches ours."""
    if mode == "subscribe" and settings.whatsapp_verify_token and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "verification failed")


@router.post("/whatsapp")
async def whatsapp_events(request: Request) -> dict:
    raw = await request.body()
    if not whatsapp.valid_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "bad signature")
    if len(raw) > 2_000_000:
        raise HTTPException(413, "too large")
    result = await whatsapp.handle_webhook(json.loads(raw))
    return {"ok": True, **result}  # 200 quickly; the agent replies asynchronously via the worker


# ---------- payment gateways (each client's own Razorpay / Stripe account) ----------





async def _gateway(connection_id: str, provider: str) -> dict:
    async with system_session() as conn:
        org = (await conn.execute(text("select org_id from app.connections where id = cast(:i as uuid) and provider = :p and status = 'connected'"),
                                  {"i": connection_id, "p": provider})).scalar_one_or_none()
    if not org:
        raise HTTPException(404, "unknown webhook")
    return await get_connection(org, provider)


@router.post("/razorpay/{connection_id}")
async def razorpay_events(connection_id: str, request: Request) -> dict:
    gw = await _gateway(connection_id, "razorpay")
    raw = await request.body()
    expected = hmac.new(gw["secret"]["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("x-razorpay-signature", ""), expected):
        raise HTTPException(401, "bad signature")
    ev = json.loads(raw)
    if ev.get("event") not in ("payment.captured", "payment_link.paid"):
        return {"ok": True, "ignored": ev.get("event")}
    pay = ev["payload"]["payment"]["entity"]
    notes = {**(ev["payload"].get("payment_link", {}).get("entity", {}).get("notes") or {}), **(pay.get("notes") or {})}
    async with tenant_session(gw["org_id"]) as conn:
        amount = Decimal(pay["amount"]) / 100
        inv, strength = await match_invoice(conn, invoice_hint=notes.get("invoice_id"), amount=amount,
                                            email=pay.get("email"), phone=pay.get("contact"))
        pid = await apply_payment(conn, gw["org_id"], invoice_id=inv, amount=amount, currency=pay.get("currency", "INR"),
                                  gateway="razorpay", reference=pay["id"], match=strength, raw=pay)
    return {"ok": True, "duplicate": pid is None, "match": strength}


@router.post("/stripe/{connection_id}")
async def stripe_events(connection_id: str, request: Request) -> dict:
    gw = await _gateway(connection_id, "stripe")
    raw = await request.body()
    parts = dict(p.split("=", 1) for p in request.headers.get("stripe-signature", "").split(",") if "=" in p)
    t = parts.get("t", "0")
    expected = hmac.new(gw["secret"]["webhook_secret"].encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts.get("v1", ""), expected) or abs(time.time() - int(t)) > 300:
        raise HTTPException(401, "bad signature")
    ev = json.loads(raw)
    obj = ev.get("data", {}).get("object", {})
    if ev.get("type") == "checkout.session.completed":
        amount, ref, email = obj.get("amount_total"), obj.get("payment_intent") or obj["id"], (obj.get("customer_details") or {}).get("email")
    elif ev.get("type") == "payment_intent.succeeded":
        amount, ref, email = obj.get("amount_received"), obj["id"], obj.get("receipt_email")
    else:
        return {"ok": True, "ignored": ev.get("type")}
    async with tenant_session(gw["org_id"]) as conn:
        value = Decimal(amount) / 100
        inv, strength = await match_invoice(conn, invoice_hint=(obj.get("metadata") or {}).get("invoice_id"), amount=value,
                                            email=email, phone=None)
        pid = await apply_payment(conn, gw["org_id"], invoice_id=inv, amount=value, currency=(obj.get("currency") or "usd").upper(),
                                  gateway="stripe", reference=ref, match=strength, raw=obj)
    return {"ok": True, "duplicate": pid is None, "match": strength}


# ---------- Agentry's own billing (clients paying their statements) ----------

@router.post("/billing/razorpay")
async def billing_razorpay(request: Request) -> dict:
    raw = await request.body()
    secret = settings.billing_razorpay_webhook_secret
    if not secret or not hmac.compare_digest(request.headers.get("x-razorpay-signature", ""),
                                              hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()):
        raise HTTPException(401, "bad signature")
    ev = json.loads(raw)
    notes = (ev.get("payload", {}).get("payment_link", {}).get("entity", {}).get("notes")) or {}
    if ev.get("event") != "payment_link.paid" or not notes.get("statement_id"):
        return {"ok": True, "ignored": True}
    from agentry.billing import mark_paid
    pay_id = ev["payload"]["payment"]["entity"]["id"]
    async with tenant_session(notes["org_id"]) as conn:
        await mark_paid(conn, notes["statement_id"], f"razorpay:{pay_id}")
    return {"ok": True}


@router.post("/billing/stripe")
async def billing_stripe(request: Request) -> dict:
    raw = await request.body()
    secret = settings.billing_stripe_webhook_secret or ""
    parts = dict(p.split("=", 1) for p in request.headers.get("stripe-signature", "").split(",") if "=" in p)
    t = parts.get("t", "0")
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(parts.get("v1", ""), expected) or abs(time.time() - int(t)) > 300:
        raise HTTPException(401, "bad signature")
    ev = json.loads(raw)
    meta = ev.get("data", {}).get("object", {}).get("metadata") or {}
    if ev.get("type") != "checkout.session.completed" or not meta.get("statement_id"):
        return {"ok": True, "ignored": True}
    from agentry.billing import mark_paid
    async with tenant_session(meta["org_id"]) as conn:
        await mark_paid(conn, meta["statement_id"], f"stripe:{ev['data']['object']['id']}")
    return {"ok": True}


# ---------- Telegram: Agentry's team bot and each business's own bot (production: webhook mode) ----------

def _tg_secret_ok(request: Request, expected: str | None) -> bool:
    got = request.headers.get("x-telegram-bot-api-secret-token") or ""
    return bool(expected) and hmac.compare_digest(got, expected)


@router.post("/telegram/agentry")
async def telegram_team(request: Request) -> dict:
    from agentry import telegram_team
    if not _tg_secret_ok(request, settings.telegram_webhook_secret):
        raise HTTPException(403, "bad secret")
    await telegram_team.handle_update(await request.json())
    return {"ok": True}


@router.post("/telegram/{connection_id}")
async def telegram_business(connection_id: str, request: Request) -> dict:
    from agentry.connectors import telegram
    from agentry.connectors.store import _with_secret
    async with system_session() as conn:
        row = (await conn.execute(text("""select * from app.connections where id::text = :i and provider = 'telegram' and status <> 'revoked'"""),
                                  {"i": connection_id})).mappings().first()
    c = _with_secret(row)
    if not c or not _tg_secret_ok(request, (c.get("state") or {}).get("webhook_secret")):
        raise HTTPException(403, "bad secret")
    return {"stored": await telegram.ingest_customer(c, await request.json())}
