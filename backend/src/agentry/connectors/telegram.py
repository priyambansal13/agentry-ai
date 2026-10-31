"""Telegram Bot API: the calls Agentry makes, and storing a customer's message for a business's own bot.

Two kinds of bot use this:
- a business's own bot (connection provider "telegram"): its customers chat with the business's AI assistant;
- Agentry's team bot (settings.telegram_bot_token): alerts, Needs-you cards and the Tools menu (agentry/telegram_team.py).

Updates arrive by webhook in production, or by polling in local development (no public address): `poll()`.
Bots can only message people who wrote to them first, so the customer channel is reply-only (no cold outreach).
"""
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import text

from agentry.config import settings
from agentry.connectors import http
from agentry.connectors.store import get_connection
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.leads import is_opt_out

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def mode() -> str:
    if settings.telegram_mode in ("polling", "webhook"):
        return settings.telegram_mode
    host = urlparse(settings.api_public_url).hostname or "localhost"
    return "polling" if host in ("localhost", "127.0.0.1") or host.endswith(".local") else "webhook"


async def call(token: str, method: str, **params: object) -> dict:
    async with http.client(timeout=40) as c:
        r = await c.post(f"{API}/bot{token}/{method}", json={k: v for k, v in params.items() if v is not None})
    try:
        data = r.json()
    except ValueError as e:
        raise TelegramError(f"Telegram {method}: HTTP {r.status_code}") from e
    if not data.get("ok"):
        raise TelegramError(f"Telegram {method}: {data.get('description') or r.status_code}")
    return data["result"]


async def get_me(token: str) -> dict:
    return await call(token, "getMe")


async def send(token: str, chat_id: int | str, body: str, buttons: list[list[dict]] | None = None, reply_to: int | None = None) -> dict:
    """Plain text (no parse mode: business text is never interpreted as markup), optional inline buttons."""
    return await call(token, "sendMessage", chat_id=chat_id, text=body[:4096],
                      reply_markup={"inline_keyboard": buttons} if buttons else None,
                      reply_parameters={"message_id": reply_to} if reply_to else None)


async def download(token: str, file_id: str) -> bytes:
    """A file someone sent the bot (the Bot API serves files up to 20 MB)."""
    f = await call(token, "getFile", file_id=file_id)
    async with http.client(timeout=120) as c:
        r = await c.get(f"{API}/file/bot{token}/{f['file_path']}")
    if r.status_code != 200:
        raise TelegramError(f"couldn't download the file (HTTP {r.status_code})")
    return r.content


async def set_webhook(token: str, url: str, secret: str) -> None:
    await call(token, "setWebhook", url=url, secret_token=secret, allowed_updates=["message", "callback_query"], drop_pending_updates=False)


async def delete_webhook(token: str) -> None:
    await call(token, "deleteWebhook")


async def updates(bot: str, token: str) -> list[dict]:
    """Polling: new updates since last time (the offset is stored, so each update is handled once)."""
    async with system_session() as conn:
        offset = (await conn.execute(text("select update_id from app.telegram_offsets where bot = :b"), {"b": bot})).scalar_one_or_none() or 0
    got = await call(token, "getUpdates", offset=offset + 1 if offset else None, timeout=0, allowed_updates=["message", "callback_query"])
    if got:
        async with system_session() as conn:
            await conn.execute(text("""insert into app.telegram_offsets (bot, update_id) values (:b, :u)
                on conflict (bot) do update set update_id = greatest(app.telegram_offsets.update_id, excluded.update_id)"""),
                {"b": bot, "u": max(u["update_id"] for u in got)})
    return got


def new_secret() -> str:
    return secrets.token_urlsafe(24)


# ---------- a business's own bot: its customers ----------

def _name(user: dict) -> str | None:
    return " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or user.get("username")


async def _contact(conn, org_id: str, user: dict, phone: str | None) -> str:
    """One contact per Telegram user (matched on their Telegram id, then phone if they shared it)."""
    tid = str(user["id"])
    row = (await conn.execute(text("select id from app.contacts where attributes->>'telegram_id' = :t and merged_into is null limit 1"),
                              {"t": tid})).first()
    if row:
        if phone:
            from agentry.leads import normalize_phone
            await conn.execute(text("update app.contacts set phone = coalesce(phone, :p), phone_e164 = coalesce(phone_e164, :e) where id = :i"),
                               {"p": phone, "e": normalize_phone(phone), "i": row.id})
        return str(row.id)
    from agentry.leads import resolve_contact
    cid = await resolve_contact(conn, org_id, name=_name(user), phone=phone, source="telegram")
    await conn.execute(text("""update app.contacts set attributes = attributes || jsonb_build_object('telegram_id', cast(:t as text),
        'telegram_username', cast(:u as text)) where id = cast(:i as uuid)"""), {"t": tid, "u": user.get("username"), "i": cid})
    return cid


async def ingest_customer(connection: dict, update: dict) -> int:
    """A customer wrote to the business's bot: one conversation per chat, then telegram.received for the assistant."""
    m = update.get("message")
    if not m or m.get("chat", {}).get("type") != "private" or m.get("from", {}).get("is_bot"):
        return 0  # groups and other bots are ignored
    org_id, chat_id = connection["org_id"], m["chat"]["id"]
    phone = (m.get("contact") or {}).get("phone_number")
    body = m.get("text") or m.get("caption") or ("[shared their phone number]" if phone else f"[{_kind(m)} message]")
    kind = "text" if m.get("text") else ("contact" if phone else _kind(m))
    async with tenant_session(org_id) as conn:
        contact_id = await _contact(conn, org_id, m["from"], phone)
        conv_id = (await conn.execute(text("""
            insert into app.conversations (org_id, channel, automation_key, contact_id, subject, external_ref, metadata)
            values (:o, 'telegram', 'telegram_assistant', :k, 'Telegram', :ref, cast(:meta as jsonb))
            on conflict (org_id, channel, external_ref) do update set last_message_at = now()
            returning id"""), {"o": org_id, "k": contact_id, "ref": f"tg:{chat_id}",
                               "meta": json.dumps({"source": "telegram", "connection_id": str(connection["id"])})})).scalar_one()
        msg_id = (await conn.execute(text("""
            insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
            values (:o, :c, 'in', 'contact', :b, cast(:meta as jsonb), to_timestamp(:ts))
            on conflict (org_id, (metadata->>'external_id')) where metadata ? 'external_id' do nothing returning id"""),
            {"o": org_id, "c": conv_id, "b": body, "ts": m.get("date") or datetime.now(UTC).timestamp(),
             "meta": json.dumps({"external_id": f"tg:{chat_id}:{m['message_id']}", "type": kind})})).scalar_one_or_none()
        if msg_id is None:
            return 0  # delivered twice
        if is_opt_out(body):
            await conn.execute(text("update app.conversations set status = 'closed', metadata = metadata || '{\"opted_out\": true}' where id = :c"),
                               {"c": conv_id})
            await emit(conn, org_id, "telegram.opted_out", {"conversation_id": str(conv_id), "chat_id": chat_id})
            return 1
        await conn.execute(text("""update app.conversations set metadata = metadata - 'opted_out',
            status = case when status = 'closed' and metadata ? 'opted_out' then 'open' else status end where id = :c"""), {"c": conv_id})
        await emit(conn, org_id, "telegram.received", {"conversation_id": str(conv_id), "message_id": str(msg_id), "chat_id": chat_id,
                                                      "text": "Hi" if body.strip() == "/start" else body, "type": kind,
                                                      **({"file": _file(m)} if kind in ("photo", "document") else {})})
    return 1


def _file(m: dict) -> dict:
    """The file to download for a photo (its largest size) or a document."""
    if m.get("photo"):
        return {"file_id": m["photo"][-1]["file_id"], "mime": "image/jpeg", "name": None}
    d = m.get("document") or {}
    return {"file_id": d.get("file_id"), "mime": d.get("mime_type"), "name": d.get("file_name")}


def _kind(m: dict) -> str:
    return next((k for k in ("voice", "audio", "video", "photo", "document", "sticker", "location") if k in m), "other")


async def send_to_customer(org_id: str, chat_id: int | str, body: str) -> int:
    conn = await get_connection(org_id, "telegram")
    if not conn:
        raise TelegramError("Telegram isn't connected")
    return (await send(conn["secret"]["bot_token"], chat_id, body))["message_id"]
