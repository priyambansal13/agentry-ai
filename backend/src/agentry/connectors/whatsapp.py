"""WhatsApp Cloud API channel (docs/setup/whatsapp.md).

- Each client connects one WhatsApp Business phone number (phone_number_id + WABA id + access token).
- Meta calls our webhook for incoming messages and delivery statuses. Every POST is verified with the app secret
  (X-Hub-Signature-256); unsigned or wrongly signed requests are rejected.
- Inbound text -> one conversation per contact (wa_id) -> whatsapp.received event -> the client's agent replies.
- Free-form replies are only allowed within 24 hours of the customer's last message; outside it, Meta requires an
  approved template (send_template).
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime

from sqlalchemy import text

from agentry.config import settings
from agentry.connectors.http import client
from agentry.connectors.store import find_by_account, get_connection
from agentry.db import tenant_session
from agentry.events import emit
from agentry.leads import is_opt_out, opt_out, record_consent, resolve_contact

WINDOW_HOURS = 24


class WhatsAppError(Exception):
    pass


def graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{path.lstrip('/')}"


def valid_signature(raw_body: bytes, header: str | None) -> bool:
    if not settings.whatsapp_app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


async def verify_number(phone_number_id: str, access_token: str) -> dict:
    """Check the credentials work and fetch the number's display details."""
    async with client() as c:
        r = await c.get(graph(phone_number_id), params={"fields": "display_phone_number,verified_name,quality_rating"},
                        headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code != 200:
        raise WhatsAppError(f"Meta rejected these credentials: {r.text[:300]}")
    return r.json()


async def _post(conn: dict, payload: dict) -> dict:
    async with client() as c:
        r = await c.post(graph(f"{conn['account_ref']}/messages"), json={"messaging_product": "whatsapp", **payload},
                         headers={"Authorization": f"Bearer {conn['secret']['access_token']}"})
    if r.status_code >= 400:
        raise WhatsAppError(f"WhatsApp send failed ({r.status_code}): {r.text[:300]}")
    return r.json()


async def send_text(org_id: str, to: str, body: str) -> str:
    conn = await get_connection(org_id, "whatsapp")
    if not conn:
        raise WhatsAppError("WhatsApp is not connected")
    return (await _post(conn, {"to": to, "type": "text", "text": {"preview_url": False, "body": body[:4096]}}))["messages"][0]["id"]


async def send_template(org_id: str, to: str, name: str, language: str = "en_US", params: list[str] | None = None) -> str:
    conn = await get_connection(org_id, "whatsapp")
    if not conn:
        raise WhatsAppError("WhatsApp is not connected")
    template: dict = {"name": name, "language": {"code": language}}
    if params:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
    return (await _post(conn, {"to": to, "type": "template", "template": template}))["messages"][0]["id"]


async def download_media(org_id: str, media_id: str) -> tuple[bytes, str]:
    """A photo or document a customer sent: (bytes, mime type). Media URLs need the access token and expire in minutes."""
    conn = await get_connection(org_id, "whatsapp")
    if not conn:
        raise WhatsAppError("WhatsApp is not connected")
    auth = {"Authorization": f"Bearer {conn['secret']['access_token']}"}
    async with client(timeout=120) as c:
        meta = await c.get(graph(media_id), headers=auth)
        if meta.status_code >= 400:
            raise WhatsAppError(f"couldn't find the media ({meta.status_code})")
        r = await c.get(meta.json()["url"], headers=auth)
    if r.status_code >= 400:
        raise WhatsAppError(f"couldn't download the media ({r.status_code})")
    return r.content, meta.json().get("mime_type") or r.headers.get("content-type", "")


async def within_window(org_id: str, conversation_id: str) -> bool:
    async with tenant_session(org_id) as conn:
        last_in = (await conn.execute(text("""select max(created_at) from app.messages
            where conversation_id = :c and direction = 'in'"""), {"c": conversation_id})).scalar_one()
    return bool(last_in) and (datetime.now(UTC) - last_in).total_seconds() < WINDOW_HOURS * 3600


async def handle_webhook(payload: dict) -> dict:
    """Store inbound messages and statuses from one webhook delivery. Returns counts (for logs and tests)."""
    stored, statuses = 0, 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = value.get("metadata", {}).get("phone_number_id")
            conn = await find_by_account("whatsapp", pnid) if pnid else None
            if not conn:
                continue  # a number we don't manage (or was disconnected): ignore
            org_id = conn["org_id"]
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                stored += await _store_inbound(org_id, m, names.get(m.get("from")))
            for st in value.get("statuses", []):
                statuses += await _store_status(org_id, st)
    return {"messages": stored, "statuses": statuses}


def _text_of(m: dict) -> str:
    t = m.get("type")
    if t == "text":
        return m["text"]["body"]
    if t == "button":
        return m["button"].get("text", "")
    if t == "interactive":
        i = m["interactive"]
        return (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
    return f"[{t} message]"  # images, voice notes etc.: recorded, answered by a person for now


async def _store_inbound(org_id: str, m: dict, name: str | None) -> int:
    wa_id, body = m["from"], _text_of(m)
    async with tenant_session(org_id) as conn:
        contact_id = await resolve_contact(conn, org_id, name=name, phone=f"+{wa_id}", source="whatsapp")
        conv_id = (await conn.execute(text("""
            insert into app.conversations (org_id, channel, automation_key, contact_id, subject, external_ref, metadata)
            values (:o, 'whatsapp', 'whatsapp_assistant', :k, 'WhatsApp', :ref, '{"source": "whatsapp"}')
            on conflict (org_id, channel, external_ref) do update set last_message_at = now()
            returning id"""), {"o": org_id, "k": contact_id, "ref": f"wa:{wa_id}"})).scalar_one()
        msg_id = (await conn.execute(text("""
            insert into app.messages (org_id, conversation_id, direction, author, body, metadata, created_at)
            values (:o, :c, 'in', 'contact', :b, cast(:meta as jsonb), to_timestamp(:ts))
            on conflict (org_id, (metadata->>'external_id')) where metadata ? 'external_id' do nothing returning id"""),
            {"o": org_id, "c": conv_id, "b": body, "ts": int(m.get("timestamp", "0")) or datetime.now(UTC).timestamp(),
             "meta": json.dumps({"external_id": f"wa:{m['id']}", "wa_id": wa_id, "type": m.get("type")})})).scalar_one_or_none()
        if msg_id is None:
            return 0  # Meta redelivered a message we already have
        if body.strip().lower() in ("start", "unstop", "subscribe"):
            await conn.execute(text("delete from app.suppressions where channel = 'whatsapp' and address = :a"), {"a": f"+{wa_id}"})
        if is_opt_out(body):
            await opt_out(conn, org_id, contact_id, "whatsapp", source="reply:whatsapp")
            await emit(conn, org_id, "whatsapp.opted_out", {"conversation_id": str(conv_id), "wa_id": wa_id})
            return 1
        # A customer writing to the business consents to replies on WhatsApp (customer-initiated conversation).
        await record_consent(conn, org_id, contact_id, "whatsapp", True, source="inbound")
        await emit(conn, org_id, "whatsapp.received", {"conversation_id": str(conv_id), "message_id": str(msg_id),
                                                      "wa_id": wa_id, "text": body, "type": m.get("type"),
                                                      **({"media": {"id": m[m["type"]].get("id"), "mime": m[m["type"]].get("mime_type"),
                                                                    "filename": m[m["type"]].get("filename")}}
                                                         if m.get("type") in ("image", "document") and isinstance(m.get(m["type"]), dict) else {})})
    return 1


async def _store_status(org_id: str, st: dict) -> int:
    async with tenant_session(org_id) as conn:
        n = (await conn.execute(text("""update app.messages set metadata = metadata || jsonb_build_object(
                'delivery', cast(:s as text), 'delivery_error', cast(:e as text))
            where metadata->>'external_id' = :id"""),
            {"s": st.get("status"), "id": f"wa:{st.get('id')}",
             "e": json.dumps(st["errors"]) if st.get("errors") else None})).rowcount
    return n
