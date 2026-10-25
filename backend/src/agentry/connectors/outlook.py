"""Outlook / Microsoft 365 mailboxes through Microsoft Graph (#6), the same job as connectors/gmail.py.

- Connect: Microsoft sign-in (OAuth 2.0, the client's own account) with offline access, Mail.ReadWrite, Mail.Send.
  Business tenants may need their admin to approve the app once (docs/setup/outlook.md).
- Sync: every minute, Graph delta queries on Inbox (new mail -> inbox triage) and Sent Items (the business's own
  replies -> recorded, never triaged). The first sync only looks forward from the moment of connecting.
- Labels: Outlook categories ("Agentry/Client", ...); archive moves promotions and spam to Archive.
- Drafts: createReply in the thread; approving in Agentry fills in the final text and sends it.
"""
import base64
import logging
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.config import settings
from agentry.connectors.http import client
from agentry.connectors.store import get_connection_for, get_connections, update_state
from agentry.db import tenant_session

log = logging.getLogger("agentry.outlook")
API = "https://graph.microsoft.com/v1.0"
SCOPES = ["offline_access", "openid", "email", "User.Read", "Mail.ReadWrite", "Mail.Send"]
REDIRECT_PATH = "/connect/microsoft/callback"
SELECT = "id,conversationId,from,replyTo,subject,body,receivedDateTime,sentDateTime,internetMessageId,hasAttachments,categories"


class OutlookError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def login_base() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_tenant}/oauth2/v2.0"


def configured() -> bool:
    return bool(settings.microsoft_client_id and settings.microsoft_client_secret)


def redirect_uri() -> str:
    return settings.api_public_url.rstrip("/") + REDIRECT_PATH


def auth_url(state: str, login_hint: str | None = None) -> str:
    params = {"client_id": settings.microsoft_client_id, "redirect_uri": redirect_uri(), "response_type": "code",
              "response_mode": "query", "scope": " ".join(SCOPES), "state": state, "prompt": "select_account"}
    if login_hint:
        params["login_hint"] = login_hint
    return f"{login_base()}/authorize?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with client() as c:
        r = await c.post(f"{login_base()}/token", data={"client_id": settings.microsoft_client_id, "client_secret": settings.microsoft_client_secret,
                                                         "code": code, "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
                                                         "scope": " ".join(SCOPES)})
    if r.status_code != 200:
        raise OutlookError(f"Microsoft rejected the sign-in: {r.text[:200]}")
    tok = r.json()
    if "refresh_token" not in tok:
        raise OutlookError("Microsoft did not return offline access; connect again and accept all permissions")
    granted = {s.split("/")[-1] for s in tok.get("scope", "").split()}
    if not {"Mail.ReadWrite", "Mail.Send"} <= granted:
        raise OutlookError("Mail access was not granted (your Microsoft 365 admin may need to approve Agentry)")
    return {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
            "expires_at": time.time() + tok.get("expires_in", 3600) - 60, "scopes": sorted(granted)}


class Outlook:
    """Thin Graph client bound to one connection; refreshes the access token when it expires."""

    def __init__(self, org_id: str, connection: dict):
        self.org_id, self.conn = org_id, connection
        self.secret = dict(connection["secret"])

    async def _token(self) -> str:
        if self.secret.get("access_token") and self.secret.get("expires_at", 0) > time.time():
            return self.secret["access_token"]
        async with client() as c:
            r = await c.post(f"{login_base()}/token", data={"client_id": settings.microsoft_client_id,
                                                             "client_secret": settings.microsoft_client_secret,
                                                             "refresh_token": self.secret["refresh_token"], "grant_type": "refresh_token",
                                                             "scope": " ".join(SCOPES)})
        if r.status_code != 200:
            await update_state(self.org_id, self.conn["id"], error=f"token refresh failed: {r.text[:200]}")
            raise OutlookError("Outlook access was revoked or expired; please reconnect Outlook")
        tok = r.json()
        self.secret.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
        if tok.get("refresh_token"):
            self.secret["refresh_token"] = tok["refresh_token"]  # Microsoft rotates refresh tokens
        await update_state(self.org_id, self.conn["id"], secret=self.secret)
        return self.secret["access_token"]

    async def send_new(self, *, to: str, subject: str, body: str) -> dict:
        """A new email from this mailbox (reminders). Returns {"id", "conversationId"}."""
        return await _send_new(self, to=to, subject=subject, body=body)

    async def call(self, method: str, path_or_url: str, **kw) -> dict:
        url = path_or_url if path_or_url.startswith("https://") else f"{API}{path_or_url}"
        headers = {"Authorization": f"Bearer {await self._token()}", "Prefer": 'outlook.body-content-type="text"', **kw.pop("headers", {})}
        async with client() as c:
            r = await c.request(method, url, headers=headers, **kw)
        if r.status_code >= 400:
            raise OutlookError(f"Outlook {method} {url.replace(API, '')} -> {r.status_code}: {r.text[:300]}", r.status_code)
        return r.json() if r.content else {}


async def _send_new(o: "Outlook", *, to: str, subject: str, body: str) -> dict:
    draft = await o.call("POST", "/me/messages", json={"subject": subject, "body": {"contentType": "Text", "content": body},
                                                       "toRecipients": [{"emailAddress": {"address": to}}]})
    await o.call("POST", f"/me/messages/{draft['id']}/send")
    return {"id": draft["id"], "conversationId": draft.get("conversationId", draft["id"])}


def parse_message(m: dict) -> dict:
    sender = ((m.get("from") or {}).get("emailAddress") or {})
    reply_to = next(iter(m.get("replyTo") or []), {}).get("emailAddress", {})
    when = m.get("receivedDateTime") or m.get("sentDateTime")
    return {"id": m["id"], "conversation_id": m.get("conversationId", m["id"]), "from": (sender.get("address") or "").lower(),
            "from_name": sender.get("name") or "", "reply_to": (reply_to.get("address") or "").lower(), "subject": m.get("subject") or "",
            "body": (m.get("body") or {}).get("content", ""), "message_id": m.get("internetMessageId"),
            "at": datetime.fromisoformat(when) if when else datetime.now(UTC),
            "has_attachments": bool(m.get("hasAttachments")), "categories": m.get("categories") or []}


async def read_attachments(o: Outlook, message_id: str, max_files: int = 3) -> list[dict]:
    """Text of readable attachments (#14), like Gmail: PDF, Word, text, CSV under 5 MB; others by name only."""
    from agentry.connectors.gmail import MAX_ATTACHMENT, READABLE
    from agentry.knowledge import UnreadableFile, extract_text
    out = []
    for a in (await o.call("GET", f"/me/messages/{message_id}/attachments")).get("value", []):
        item = {"filename": a.get("name", "attachment"), "mime": a.get("contentType", ""), "size": a.get("size", 0)}
        if (len([x for x in out if x.get("text")]) < max_files and item["filename"].lower().endswith(READABLE)
                and 0 < item["size"] <= MAX_ATTACHMENT and a.get("contentBytes")):
            try:
                item["text"] = extract_text(item["filename"], base64.b64decode(a["contentBytes"]))[:4000]
            except (UnreadableFile, ValueError) as e:
                log.info("attachment %s not read: %s", item["filename"], e)
        out.append(item)
    return out


async def _delta(o: Outlook, folder: str, link: str | None, since: str) -> tuple[list[dict], str]:
    """New messages in a folder since the stored deltaLink (first time: from `since` on). Returns (messages, deltaLink)."""
    url = link or f"{API}/me/mailFolders/{folder}/messages/delta?" + urlencode(
        {"$select": SELECT, "$filter": f"receivedDateTime ge {since}"})
    out = []
    while True:
        page = await o.call("GET", url)
        out += [m for m in page.get("value", []) if "@removed" not in m]
        if page.get("@odata.nextLink"):
            url = page["@odata.nextLink"]
            continue
        return out, page.get("@odata.deltaLink", url)


async def sync_account(org_id: str, conn: dict, max_messages: int = 50) -> int:
    from agentry.connectors.mailbox import record_sent_reply
    o = Outlook(org_id, conn)
    st = conn["state"] or {}
    since = st.get("since") or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        inbox, inbox_link = await _delta(o, "inbox", st.get("inbox_delta"), since)
        sent, sent_link = await _delta(o, "sentitems", st.get("sent_delta"), since)
        count = 0
        for raw in inbox[:max_messages]:
            m = parse_message(raw)
            if m["from"] == conn["account_ref"].lower():
                continue
            files = await read_attachments(o, m["id"]) if m["has_attachments"] else []
            created = await ingest_email(org_id, sender=m["from"], subject=m["subject"], body=m["body"][:100_000],
                                         thread_ref=f"outlook:{m['conversation_id']}", external_id=f"outlook:{m['id']}",
                                         received_at=m["at"].isoformat(),
                                         extra={"from_name": m["from_name"], "reply_to": m["reply_to"], "mailbox": conn["account_ref"],
                                                **({"attachments": files} if files else {}),
                                                "outlook": {"message_id": m["id"], "conversation_id": m["conversation_id"],
                                                            "internet_message_id": m["message_id"]}})
            count += bool(created)
        for raw in sent:
            m = parse_message(raw)
            await record_sent_reply(org_id, thread_ref=f"outlook:{m['conversation_id']}", external_id=f"outlook:{m['id']}",
                                    body=m["body"], sent_at=m["at"], sent_from="outlook")
        await update_state(org_id, conn["id"], state={"since": since, "inbox_delta": inbox_link, "sent_delta": sent_link}, synced=True)
        return count
    except OutlookError as e:
        await update_state(org_id, conn["id"], error=str(e)[:500])
        raise


async def sync(org_id: str, max_messages: int = 50) -> int:
    """Every connected Outlook mailbox of this client, one after the other."""
    total, failed = 0, None
    for conn in await get_connections(org_id, "outlook"):
        try:
            total += await sync_account(org_id, conn, max_messages)
        except OutlookError as e:
            failed = e
    if failed and not total:
        raise failed
    return total


class OutlookMailbox:
    """Mailbox protocol (connectors/mailbox.py) backed by the organisation's Outlook."""

    async def _ctx(self, org_id: str, conversation_id: str) -> tuple[Outlook, dict]:
        async with tenant_session(org_id) as c:
            row = (await c.execute(text("""select cv.metadata->>'mailbox' as mailbox, m.metadata->'outlook' as o, m.metadata->>'from' as sender,
                cv.subject, cv.metadata->>'outlook_draft_id' as draft_id
                from app.messages m join app.conversations cv on cv.id = m.conversation_id
                where m.conversation_id = :c and m.direction = 'in' and m.metadata ? 'outlook' order by m.created_at desc limit 1"""),
                {"c": conversation_id})).mappings().first()
        if not row:
            raise OutlookError("conversation has no Outlook message")
        conn = await get_connection_for(org_id, "outlook", row["mailbox"])
        if not conn:
            raise OutlookError("Outlook is not connected")
        return Outlook(org_id, conn), dict(row)

    async def apply_labels(self, org_id: str, conversation_id: str, labels: list[str], archive: bool) -> None:
        o, meta = await self._ctx(org_id, conversation_id)
        mid = meta["o"]["message_id"]
        current = (await o.call("GET", f"/me/messages/{mid}", params={"$select": "categories"})).get("categories", [])
        await o.call("PATCH", f"/me/messages/{mid}", json={"categories": list(dict.fromkeys(current + labels))})
        if archive:
            await o.call("POST", f"/me/messages/{mid}/move", json={"destinationId": "archive"})

    async def relabel(self, org_id: str, conversation_id: str, add: list[str], remove: list[str]) -> None:
        o, meta = await self._ctx(org_id, conversation_id)
        mid = meta["o"]["message_id"]
        current = (await o.call("GET", f"/me/messages/{mid}", params={"$select": "categories"})).get("categories", [])
        await o.call("PATCH", f"/me/messages/{mid}", json={"categories": [c for c in current if c not in remove] + [c for c in add if c not in current]})

    async def create_draft(self, org_id: str, conversation_id: str, body: str) -> str:
        o, meta = await self._ctx(org_id, conversation_id)
        draft = await o.call("POST", f"/me/messages/{meta['o']['message_id']}/createReply")
        await o.call("PATCH", f"/me/messages/{draft['id']}", json={"body": {"contentType": "Text", "content": body}})
        async with tenant_session(org_id) as c:
            await c.execute(text("""update app.conversations set metadata = metadata || jsonb_build_object(
                'outlook_draft_id', cast(:d as text), 'draft', cast(:b as text)) where id = :c"""), {"d": draft["id"], "b": body, "c": conversation_id})
        return draft["id"]

    async def send_reply(self, org_id: str, conversation_id: str, body: str) -> str:
        """Approved in Agentry: the final text goes into the reply draft (made now if missing), which is sent."""
        o, meta = await self._ctx(org_id, conversation_id)
        draft_id = meta.get("draft_id")
        if not draft_id:
            draft_id = (await o.call("POST", f"/me/messages/{meta['o']['message_id']}/createReply"))["id"]
        await o.call("PATCH", f"/me/messages/{draft_id}", json={"body": {"contentType": "Text", "content": body}})
        await o.call("POST", f"/me/messages/{draft_id}/send")
        return draft_id

    async def replied_since(self, org_id: str, conversation_id: str, since: datetime) -> bool:
        from agentry.connectors.mailbox import reply_recorded
        if await reply_recorded(org_id, conversation_id, since):
            return True
        o, meta = await self._ctx(org_id, conversation_id)
        conv = meta["o"]["conversation_id"].replace("'", "''")
        found = await o.call("GET", "/me/mailFolders/sentitems/messages", params={
            "$filter": f"conversationId eq '{conv}' and sentDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}", "$select": "id", "$top": 1})
        return bool(found.get("value"))
