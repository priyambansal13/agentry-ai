"""Replies in Agentry's sales inbox (the Gmail Agentry sends from), read-only over IMAP with the same app password.

Every few minutes the worker looks at recent mail. A message from someone with an open demo request is recorded on
that request; a real reply moves it to "in talks" (stopping follow-ups) and alerts the team. Out-of-office replies are
recorded without changing anything, and bounces about the prospect's address are flagged. Messages are never marked
read or changed (BODY.PEEK, read-only mailbox).
"""
import contextlib
import email
import imaplib
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session

OPEN = ("new", "demo_built", "demo_sent", "in_talks")
AUTO_SUBJECT = re.compile(r"^(automatic reply|auto[- ]?reply|out of (the )?office|away|on leave|vacation)", re.IGNORECASE)


def imap_host() -> str | None:
    if settings.imap_host:
        return settings.imap_host
    return "imap.gmail.com" if (settings.smtp_host or "").endswith("gmail.com") else None


def _text(v: str | None) -> str:
    return str(make_header(decode_header(v or "")))


def body_text(msg: Message, limit: int = 4000) -> str:
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"), None) if msg.is_multipart() else msg
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    return raw.decode(part.get_content_charset() or "utf-8", errors="replace")[:limit]


def snippet(body: str) -> str:
    """The new part of a reply: drop quoted lines and everything from "On ... wrote:"."""
    out = []
    for line in body.splitlines():
        if re.match(r"^\s*On .+wrote:\s*$", line) or line.startswith("-----Original Message"):
            break
        if not line.startswith(">"):
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()[:600]


def classify(msg: Message, open_emails: dict[str, str]) -> tuple[str, str] | None:
    """(kind, demo_request_id) for a message about an open request, else None."""
    sender = (getaddresses([msg.get("From", "")])[0][1] or "").lower()
    if sender in open_emails:
        auto = msg.get("Auto-Submitted", "no").lower() != "no" or AUTO_SUBJECT.match(_text(msg.get("Subject")))
        return ("auto_reply" if auto else "reply"), open_emails[sender]
    if sender.startswith(("mailer-daemon@", "postmaster@")):
        body = body_text(msg, 20000).lower()
        hit = next((e for e in open_emails if e in body), None)
        if hit:
            return "bounce", open_emails[hit]
    return None


def fetch_recent(days: int = 3) -> list[Message]:
    """Messages from the last few days in INBOX, read-only."""
    host = imap_host()
    if not host or not settings.smtp_user or not settings.smtp_password:
        return []
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")
    m = imaplib.IMAP4_SSL(host, timeout=30)
    try:
        m.login(settings.smtp_user, settings.smtp_password)
        m.select("INBOX", readonly=True)
        _, ids = m.search(None, f"(SINCE {since})")
        out = []
        for i in ids[0].split()[-200:]:
            _, data = m.fetch(i, "(BODY.PEEK[])")
            if data and isinstance(data[0], tuple):
                out.append(email.message_from_bytes(data[0][1]))
        return out
    finally:
        with contextlib.suppress(Exception):  # closing a broken connection
            m.logout()


async def process(messages: list[Message]) -> list[dict]:
    """Record new replies/bounces on open demo requests. Returns what was new (for alerts)."""
    async with system_session() as conn:
        rows = (await conn.execute(text("select id::text, lower(email) as email, status from app.demo_requests where status = any(:s)"),
                                   {"s": list(OPEN)})).all()
    open_emails = {r.email: r.id for r in rows}
    status = {r.id: r.status for r in rows}
    new = []
    for msg in messages:
        hit = classify(msg, open_emails)
        mid = (msg.get("Message-ID") or "").strip()
        if not hit or not mid:
            continue
        kind, demo_id = hit
        try:
            received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(UTC)
        except (TypeError, ValueError):
            received = datetime.now(UTC)
        async with system_session() as conn:
            inserted = (await conn.execute(text("""insert into app.demo_request_messages
                (demo_request_id, message_id, kind, from_address, subject, snippet, received_at)
                values (cast(:d as uuid), :m, :k, :f, :s, :sn, :r) on conflict (message_id) do nothing returning id"""),
                {"d": demo_id, "m": mid, "k": kind, "f": getaddresses([msg.get("From", "")])[0][1],
                 "s": _text(msg.get("Subject"))[:300], "sn": snippet(body_text(msg)) if kind != "bounce" else None,
                 "r": received})).first()
        if inserted:
            new.append({"demo_request_id": demo_id, "kind": kind, "subject": _text(msg.get("Subject")),
                        "snippet": snippet(body_text(msg)) if kind == "reply" else None, "status_before": status[demo_id]})
    return new
