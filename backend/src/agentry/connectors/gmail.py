"""Gmail connector (docs/setup/gmail.md).

- Connect: OAuth 2.0 (offline access) with the gmail.modify scope: read mail, add labels, create and send drafts.
  Nothing is ever deleted.
- Sync: every minute, users.history.list from the stored historyId returns new INBOX messages; each becomes an
  email.received event for inbox triage. Message ids are de-duplicated, so overlapping syncs are harmless.
- Labels: "Agentry/<Category>" (+ "Agentry/Urgent"), created on first use.
- Drafts: the AI's reply is a real Gmail draft in the same thread (In-Reply-To / References), so the owner can send it
  from Gmail; approving it in Agentry sends that draft (drafts.send) from the owner's own account.
"""
import base64
import logging
import re
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from html import unescape
from urllib.parse import urlencode

from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.config import settings
from agentry.connectors.http import client
from agentry.connectors.store import get_connection_for, get_connections, update_state
from agentry.db import tenant_session

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/gmail.modify"]
REDIRECT_PATH = "/connect/google/callback"


log = logging.getLogger(__name__)


class GmailError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    return settings.api_public_url.rstrip("/") + REDIRECT_PATH


def auth_url(state: str, login_hint: str | None = None) -> str:
    params = {"client_id": settings.google_client_id, "redirect_uri": redirect_uri(), "response_type": "code",
              "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
              "state": state}
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with client() as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": settings.google_client_id,
                                          "client_secret": settings.google_client_secret,
                                          "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise GmailError(f"Google rejected the sign-in: {r.text[:200]}")
    tok = r.json()
    if "refresh_token" not in tok:
        raise GmailError("Google did not return offline access; remove Agentry from your Google account and connect again")
    granted = set(tok.get("scope", "").split())
    if "https://www.googleapis.com/auth/gmail.modify" not in granted:
        raise GmailError("Gmail access was not granted (the Gmail permission box must be ticked)")
    return {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
            "expires_at": time.time() + tok.get("expires_in", 3600) - 60, "scopes": sorted(granted)}


class Gmail:
    """Thin Gmail API client bound to one connection; refreshes the access token when it expires."""

    def __init__(self, org_id: str, connection: dict):
        self.org_id, self.conn = org_id, connection
        self.secret = dict(connection["secret"])

    async def _token(self) -> str:
        if self.secret.get("access_token") and self.secret.get("expires_at", 0) > time.time():
            return self.secret["access_token"]
        async with client() as c:
            r = await c.post(TOKEN_URL, data={"client_id": settings.google_client_id,
                                              "client_secret": settings.google_client_secret,
                                              "refresh_token": self.secret["refresh_token"], "grant_type": "refresh_token"})
        if r.status_code != 200:
            await update_state(self.org_id, self.conn["id"], error=f"token refresh failed: {r.text[:200]}")
            raise GmailError("Gmail access was revoked or expired; please reconnect Gmail")
        tok = r.json()
        self.secret.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
        await update_state(self.org_id, self.conn["id"], secret=self.secret)
        return self.secret["access_token"]

    async def call(self, method: str, path: str, **kw) -> dict:
        async with client() as c:
            r = await c.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {await self._token()}"}, **kw)
        if r.status_code >= 400:
            raise GmailError(f"Gmail {method} {path} -> {r.status_code}: {r.text[:300]}", r.status_code)
        return r.json() if r.content else {}

    # ---- labels ----
    async def label_ids(self, names: list[str]) -> list[str]:
        known: dict = dict(self.conn["state"].get("labels", {}))
        missing = [n for n in names if n not in known]
        if missing:
            existing = {lbl["name"]: lbl["id"] for lbl in (await self.call("GET", "/labels")).get("labels", [])}
            for name in missing:
                known[name] = existing.get(name) or (await self.call("POST", "/labels", json={
                    "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}))["id"]
            self.conn["state"]["labels"] = known
            await update_state(self.org_id, self.conn["id"], state={"labels": known})
        return [known[n] for n in names]

    async def modify(self, message_id: str, add: list[str], remove: list[str] | None = None) -> None:
        await self.call("POST", f"/messages/{message_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove or []})

    # ---- drafts ----
    async def save_draft(self, *, thread_id: str, to: str, subject: str, in_reply_to: str | None, body: str,
                         draft_id: str | None = None) -> str:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"message": {"raw": raw, "threadId": thread_id}}
        if draft_id:
            return (await self.call("PUT", f"/drafts/{draft_id}", json={"id": draft_id, **payload}))["id"]
        return (await self.call("POST", "/drafts", json=payload))["id"]

    async def send_new(self, *, to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
        """An email from the connected account; with thread_id it continues that thread (same subject, Re:).
        Returns {"id", "threadId"}."""
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(), **({"threadId": thread_id} if thread_id else {})}
        return await self.call("POST", "/messages/send", json=payload)

    async def send_draft(self, draft_id: str) -> str:
        return (await self.call("POST", "/drafts/send", json={"id": draft_id}))["id"]


def parse_message(m: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
    return {"id": m["id"], "thread_id": m["threadId"], "from": parseaddr(headers.get("from", ""))[1].lower(),
            "from_name": parseaddr(headers.get("from", ""))[0], "subject": headers.get("subject", ""),
            "message_id": headers.get("message-id"), "labels": m.get("labelIds", []),
            "reply_to": parseaddr(headers.get("reply-to", ""))[1].lower(), "to": parseaddr(headers.get("to", ""))[1].lower(),
            "internal_ms": int(m.get("internalDate", "0")), "body": _body(m.get("payload", {})) or m.get("snippet", ""),
            "attachments": _attachments(m.get("payload", {}))}


READABLE = (".pdf", ".docx", ".txt", ".md", ".csv")
MAX_ATTACHMENT = 5 * 1024 * 1024


def _attachments(part: dict) -> list[dict]:
    """Attachment parts of a message: name, type, size and the id to download them by."""
    out = []
    if part.get("filename") and part.get("body", {}).get("attachmentId"):
        out.append({"filename": part["filename"], "mime": part.get("mimeType", ""), "size": part["body"].get("size", 0),
                    "attachment_id": part["body"]["attachmentId"]})
    for p in part.get("parts", []):
        out += _attachments(p)
    return out


async def read_attachments(g: "Gmail", message_id: str, attachments: list[dict], max_files: int = 3) -> list[dict]:
    """Text of the readable attachments (#14): used for sorting and drafting, and an excerpt shown on the conversation.
    Images and other files are listed by name only."""
    from agentry.knowledge import UnreadableFile, extract_text
    out = []
    for a in attachments:
        item = {"filename": a["filename"], "mime": a["mime"], "size": a["size"]}
        if (len([x for x in out if x.get("text")]) < max_files and a["filename"].lower().endswith(READABLE)
                and 0 < a["size"] <= MAX_ATTACHMENT):
            try:
                data = await g.call("GET", f"/messages/{message_id}/attachments/{a['attachment_id']}")
                raw = base64.urlsafe_b64decode(data["data"] + "=" * (-len(data["data"]) % 4))
                item["text"] = extract_text(a["filename"], raw)[:4000]
            except (GmailError, UnreadableFile, ValueError, KeyError) as e:
                log.info("attachment %s not read: %s", a["filename"], e)
        out.append(item)
    return out


def _body(part: dict) -> str:
    mime, data = part.get("mimeType", ""), part.get("body", {}).get("data")
    if mime == "text/plain" and data:
        return _b64(data)
    texts = [_body(p) for p in part.get("parts", []) if p.get("mimeType", "").startswith(("text/plain", "multipart/"))]
    if any(texts):
        return next(t for t in texts if t)
    if mime == "text/html" and data:
        return _html_to_text(_b64(data))
    for p in part.get("parts", []):
        if p.get("mimeType") == "text/html":
            return _html_to_text(_b64(p.get("body", {}).get("data", "")))
    return ""


def _b64(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", " ", html)).strip()


async def watch(g: "Gmail") -> dict | None:
    """Gmail push (#5): ask Gmail to publish changes to Agentry's Pub/Sub topic. Lasts 7 days; renewed daily.
    Polling keeps running as a safety net."""
    if not settings.gmail_pubsub_topic:
        return None
    r = await g.call("POST", "/watch", json={"topicName": settings.gmail_pubsub_topic, "labelIds": ["INBOX", "SENT"],
                                             "labelFilterBehavior": "INCLUDE"})
    await update_state(g.org_id, g.conn["id"], state={"watch_expiration": r.get("expiration")})
    return r


async def renew_watches() -> int:
    """Daily: renew every Gmail inbox's push subscription."""
    from agentry.connectors.store import all_connected
    if not settings.gmail_pubsub_topic:
        return 0
    n = 0
    for row in await all_connected("gmail"):
        conn = next((c for c in await get_connections(row["org_id"], "gmail") if str(c["id"]) == str(row["id"])), None)
        if conn:
            try:
                await watch(Gmail(row["org_id"], conn))
                n += 1
            except GmailError as e:
                log.info("gmail watch renewal failed for %s: %s", conn["account_ref"], e)
    return n


async def _baseline(g: "Gmail", threads: int = 60) -> float | None:
    """How fast the business replied before Agentry: median minutes, from the last 30 days of real conversations.
    Measured once at connection (a few dozen API calls); never blocks connecting."""
    from agentry.automations.inbox_triage.insights import baseline_minutes
    try:
        listed = await g.call("GET", "/threads", params={"q": "in:inbox newer_than:30d -category:promotions -category:social "
                                                          "-category:updates -category:forums", "maxResults": threads})
        full = [await g.call("GET", f"/threads/{t['id']}", params={"format": "minimal"}) for t in listed.get("threads", [])]
        return baseline_minutes(full, int(time.time() * 1000))
    except GmailError as e:
        log.info("gmail baseline skipped: %s", e)
        return None


async def record_sent(org_id: str, m: dict) -> bool:
    """A reply the business sent from Gmail itself (see mailbox.record_sent_reply)."""
    from agentry.connectors.mailbox import record_sent_reply
    return await record_sent_reply(org_id, thread_ref=f"gmail:{m['thread_id']}", external_id=f"gmail:{m['id']}", body=m["body"],
                                   sent_at=datetime.fromtimestamp(m["internal_ms"] / 1000, UTC), sent_from="gmail")


async def sync(org_id: str, max_messages: int = 50) -> int:
    """Every connected Gmail inbox of this client (#16), one after the other; a broken one doesn't stop the others."""
    total, failed = 0, None
    for conn in await get_connections(org_id, "gmail"):
        if conn["status"] == "revoked":
            continue
        try:
            total += await sync_account(org_id, conn, max_messages)
        except GmailError as e:
            failed = e
    if failed and not total:
        raise failed
    return total


async def sync_account(org_id: str, conn: dict, max_messages: int = 50) -> int:
    """Pull new mail since the stored historyId: INBOX messages go to inbox triage; the account's own SENT messages are
    recorded as replies in conversations Agentry already has (for response times and "handled"), never triaged."""
    g = Gmail(org_id, conn)
    try:
        start = conn["state"].get("history_id")
        if not start:  # first sync: start from now, don't triage the whole mailbox history
            profile = await g.call("GET", "/profile")
            state = {"history_id": profile["historyId"]}
            if (base := await _baseline(g)) is not None:
                state["baseline_response_minutes"] = base
            try:
                await watch(g)
            except GmailError as e:
                log.info("gmail push not set up for %s: %s", conn["account_ref"], e)
            await update_state(org_id, conn["id"], state=state, synced=True)
            from agentry.events import emit
            async with tenant_session(org_id) as c:  # learn how they write, in the worker (#1)
                await emit(c, org_id, "inbox.learn_style", {"mailbox": conn["account_ref"]})
            return 0
        ids, page, newest = [], None, start
        while True:
            params = {"startHistoryId": start, "historyTypes": "messageAdded", "maxResults": 100}
            if page:
                params["pageToken"] = page
            try:
                h = await g.call("GET", "/history", params=params)
            except GmailError as e:
                if " 404" in str(e):  # historyId too old: resume from now (Gmail keeps about a week of history)
                    profile = await g.call("GET", "/profile")
                    await update_state(org_id, conn["id"], state={"history_id": profile["historyId"]}, synced=True)
                    return 0
                raise
            for rec in h.get("history", []):
                ids += [x["message"]["id"] for x in rec.get("messagesAdded", [])]
            newest = h.get("historyId", newest)
            page = h.get("nextPageToken")
            if not page:
                break
        count = 0
        for mid in list(dict.fromkeys(ids))[:max_messages]:
            try:
                m = parse_message(await g.call("GET", f"/messages/{mid}", params={"format": "full"}))
            except GmailError as e:
                if e.status == 404:  # deleted, moved or a draft that was sent before we got to it: nothing to triage
                    log.info("gmail %s: message %s is gone, skipped", org_id, mid)
                    continue
                raise
            if "DRAFT" in m["labels"]:
                continue
            if "SENT" in m["labels"] and m["from"] == conn["account_ref"].lower():
                await record_sent(org_id, m)
                continue
            if "INBOX" not in m["labels"] or m["from"] == conn["account_ref"].lower():
                continue
            files = await read_attachments(g, m["id"], m["attachments"]) if m["attachments"] else []
            created = await ingest_email(org_id, sender=m["from"], subject=m["subject"], body=m["body"][:100_000],
                                         thread_ref=f"gmail:{m['thread_id']}", external_id=f"gmail:{m['id']}",
                                         extra={"from_name": m["from_name"], "reply_to": m["reply_to"], "mailbox": conn["account_ref"],
                                                **({"attachments": files} if files else {}),
                                                "gmail": {"message_id": m["id"], "thread_id": m["thread_id"],
                                                          "rfc822_id": m["message_id"], "from_name": m["from_name"]}})
            count += bool(created)
        await update_state(org_id, conn["id"], state={"history_id": newest}, synced=True)
        return count
    except GmailError as e:
        await update_state(org_id, conn["id"], error=str(e)[:500])
        raise


class GmailMailbox:
    """Mailbox protocol (connectors/mailbox.py) backed by the organisation's Gmail."""

    async def _ctx(self, org_id: str, conversation_id: str) -> tuple[Gmail, dict]:
        async with tenant_session(org_id) as c:
            mailbox = (await c.execute(text("select metadata->>'mailbox' from app.conversations where id = :c"),
                                       {"c": conversation_id})).scalar_one_or_none()
        conn = await get_connection_for(org_id, "gmail", mailbox)  # reply from the inbox the email arrived in
        if not conn:
            raise GmailError("Gmail is not connected")
        async with tenant_session(org_id) as c:
            meta = (await c.execute(text("""select m.metadata->'gmail' as g, m.metadata->>'from' as sender, cv.subject,
                cv.metadata->>'gmail_draft_id' as draft_id from app.messages m join app.conversations cv on cv.id = m.conversation_id
                where m.conversation_id = :c and m.direction = 'in' and m.metadata ? 'gmail' order by m.created_at desc limit 1"""),
                {"c": conversation_id})).mappings().first()
        if not meta:
            raise GmailError("conversation has no Gmail message")
        return Gmail(org_id, conn), dict(meta)

    async def apply_labels(self, org_id: str, conversation_id: str, labels: list[str], archive: bool) -> None:
        g, meta = await self._ctx(org_id, conversation_id)
        await g.modify(meta["g"]["message_id"], await g.label_ids(labels), ["INBOX"] if archive else [])

    async def create_draft(self, org_id: str, conversation_id: str, body: str) -> str:
        g, meta = await self._ctx(org_id, conversation_id)
        draft_id = await g.save_draft(thread_id=meta["g"]["thread_id"], to=meta["sender"], subject=meta["subject"] or "",
                                      in_reply_to=meta["g"].get("rfc822_id"), body=body)
        async with tenant_session(org_id) as c:
            await c.execute(text("""update app.conversations set metadata = metadata || jsonb_build_object(
                'gmail_draft_id', cast(:d as text), 'draft', cast(:b as text)) where id = :c"""),
                {"d": draft_id, "b": body, "c": conversation_id})
        return draft_id

    async def relabel(self, org_id: str, conversation_id: str, add: list[str], remove: list[str]) -> None:
        g, meta = await self._ctx(org_id, conversation_id)
        await g.modify(meta["g"]["message_id"], await g.label_ids(add), await g.label_ids(remove) if remove else [])

    async def replied_since(self, org_id: str, conversation_id: str, since: datetime) -> bool:
        """Replied through Agentry, or straight from Gmail (the thread has a sent message after `since`)."""
        from agentry.connectors.mailbox import reply_recorded
        if await reply_recorded(org_id, conversation_id, since):
            return True
        g, meta = await self._ctx(org_id, conversation_id)
        thread = await g.call("GET", f"/threads/{meta['g']['thread_id']}", params={"format": "minimal"})
        cutoff = since.timestamp() * 1000
        return any("SENT" in m.get("labelIds", []) and int(m.get("internalDate", 0)) > cutoff for m in thread.get("messages", []))

    async def send_reply(self, org_id: str, conversation_id: str, body: str) -> str:
        """Approved in Agentry: update the draft with the final text and send it from the owner's Gmail."""
        g, meta = await self._ctx(org_id, conversation_id)
        draft_id = await g.save_draft(thread_id=meta["g"]["thread_id"], to=meta["sender"], subject=meta["subject"] or "",
                                      in_reply_to=meta["g"].get("rfc822_id"), body=body, draft_id=meta.get("draft_id"))
        return await g.send_draft(draft_id)
