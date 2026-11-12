"""CA client portal (docs/PLAN-COMMERCIAL-2026-11.md #3): each of a firm's clients gets a private page, under the firm's
name and colours, to see their filings and due dates and to send documents.

    settings  the firm turns it on and sets the title, colour, logo and a welcome line (org_settings.client_portal)
    links     one private link per client (no password): 90 days, revocable, a new one replaces the old; the token is
              stored hashed. Sent on WhatsApp / email from the client's page, or copied.
    view      the firm's name and brand; the client's open filings with their status and what's still needed; due dates
              for the next four months with where each comes from (and official extensions); files sent recently
    upload    photos / PDFs / spreadsheets go through the document chaser: matched to the checklist item, ticked off,
              filed; an unmatched file is a card for the firm. 20 files a day per link, 20 MB each.
    billing   each client who opens their portal or sends a file in a month counts once (event ca.portal_used); the plan's
              portal_clients price applies.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry import site_audit
from agentry.automations.ca import calendar, chaser, core
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.events import emit

UPLOADS_PER_DAY = 20


class PortalError(site_audit.AuditRefused):
    pass


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def url_for(token: str) -> str:
    return f"{settings.web_url.rstrip('/')}/portal/{token}"


async def get_settings(conn) -> dict:
    row = (await conn.execute(text("""select s.client_portal, s.brand, o.name from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
    p, brand = row["client_portal"] or {}, row["brand"] or {}
    return {"enabled": bool(p.get("enabled")), "title": p.get("title") or f"{row['name']} client portal", "color": p.get("color") or brand.get("color") or "#1f2a1a",
            "logo_url": p.get("logo_url") or brand.get("logo"), "welcome": p.get("welcome") or "Your filings, what we still need from you, and what's due next.",
            "firm": row["name"]}


async def save_settings(conn, data: dict) -> dict:
    import json
    clean = {"enabled": bool(data.get("enabled")), "title": str(data.get("title") or "")[:80] or None,
             "color": str(data.get("color") or "")[:9] or None, "logo_url": str(data.get("logo_url") or "")[:400] or None,
             "welcome": str(data.get("welcome") or "")[:300] or None}
    if clean["color"] and not (clean["color"].startswith("#") and len(clean["color"]) in (4, 7)):
        raise PortalError(422, "colour as #RRGGBB")
    if clean["logo_url"] and not clean["logo_url"].startswith("https://"):
        raise PortalError(422, "the logo must be an https:// address")
    await conn.execute(text("update app.org_settings set client_portal = cast(:p as jsonb)"), {"p": json.dumps(clean)})
    return await get_settings(conn)


async def create_link(conn, org_id: str, client_id: str, user_id: str | None) -> dict:
    if not (await get_settings(conn))["enabled"]:
        raise PortalError(409, "switch the client portal on first")
    if not (await conn.execute(text("select 1 from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).first():
        raise PortalError(404, "client not found")
    await conn.execute(text("update app.ca_portal_links set revoked_at = now() where client_id = cast(:c as uuid) and revoked_at is null"), {"c": client_id})
    token = secrets.token_urlsafe(24)
    exp = (await conn.execute(text("""insert into app.ca_portal_links (org_id, client_id, token_hash, created_by) values (:o, cast(:c as uuid), :t, :u)
        returning expires_at"""), {"o": org_id, "c": client_id, "t": _hash(token), "u": user_id})).scalar_one()
    return {"url": url_for(token), "expires_at": exp}


async def revoke(conn, client_id: str) -> int:
    return (await conn.execute(text("update app.ca_portal_links set revoked_at = now() where client_id = cast(:c as uuid) and revoked_at is null"),
                               {"c": client_id})).rowcount or 0


async def link_status(conn, client_id: str) -> dict | None:
    r = (await conn.execute(text("""select created_at, expires_at, last_used_at, uses from app.ca_portal_links where client_id = cast(:c as uuid)
        and revoked_at is null and expires_at > now() order by created_at desc limit 1"""), {"c": client_id})).mappings().first()
    return dict(r) if r else None


async def send_link(org_id: str, client_id: str, user_id: str | None) -> dict:
    """A new link, sent to the client on WhatsApp (in the 24-hour window or with the chaser's template) or email."""
    from agentry.outbound import reach_contact
    async with tenant_session(org_id) as conn:
        link = await create_link(conn, org_id, client_id, user_id)
        s = await get_settings(conn)
        tpl = (await conn.execute(text("select config->>'whatsapp_template' from app.automation_instances where template_key = 'ca_document_chaser'"))).scalar_one_or_none()
        who = await core.who(conn, client_id)
        first = (who.get("contact_name") or "").split()[0] if who.get("contact_name") else ""
        body = (f"{'Hi ' + first + ',' if first else 'Hello,'} here is your private link to {s['title']}: see your filings, what we still need "
                f"from you, and send documents.\n{link['url']}\n\nPlease don't share it. {s['firm']}")
        res = await reach_contact(conn, org_id, who, body, agent="ca_document_chaser", subject=f"Your link to {s['title']}",
                                  email_ref=f"ca-portal:{client_id}", wa_template=tpl, wa_params=[body])
    return link | {"sent": res["status"], "channel": res.get("channel")}


async def _resolve(token: str) -> tuple[str, str]:
    async with system_session() as conn:
        r = (await conn.execute(text("""select org_id, client_id::text from app.ca_portal_links where token_hash = :t and revoked_at is null
            and expires_at > now()"""), {"t": _hash(token or "")})).first()
    if not r:
        raise PortalError(404, "this link has expired or was replaced: ask your accountant for a new one")
    return r.org_id, r.client_id


async def _used(org_id: str, client_id: str, conn) -> None:
    await conn.execute(text("""update app.ca_portal_links set last_used_at = now(), uses = uses + 1 where client_id = cast(:c as uuid)
        and revoked_at is null"""), {"c": client_id})
    month = datetime.now(UTC).strftime("%Y-%m")
    seen = (await conn.execute(text("""select 1 from app.events where type = 'ca.portal_used' and payload->>'client_id' = :c and payload->>'month' = :m"""),
                               {"c": client_id, "m": month})).first()
    if not seen:
        await emit(conn, org_id, "ca.portal_used", {"client_id": client_id, "month": month})


async def view(token: str) -> dict:
    org_id, client_id = await _resolve(token)
    today = datetime.now(UTC).date()
    async with tenant_session(org_id) as conn:
        s = await get_settings(conn)
        if not s["enabled"]:
            raise PortalError(404, "this portal is switched off: contact your accountant")
        c = (await conn.execute(text("select name, kind, profile, gstin from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).mappings().one()
        filings = (await conn.execute(text("""select id::text, kind, period, title, due_on, status, checklist, data->'extension' as extension, filed_on, ack_no
            from app.ca_filings where client_id = cast(:c as uuid) and (status not in ('filed','verified') or filed_on > now() - interval '120 days')
            order by (status in ('filed','verified')), due_on nulls last"""), {"c": client_id})).mappings().all()
        files = (await conn.execute(text("""select filename, doc_type, item_key, created_at from app.ca_files where client_id = cast(:c as uuid)
            order by created_at desc limit 10"""), {"c": client_id})).mappings().all()
        updates = await calendar.active_updates(conn)
        await _used(org_id, client_id, conn)
    dues = calendar.deadlines(c["kind"], c["profile"] or {}, today, today + timedelta(days=120), gstin=c["gstin"], updates=updates)
    return {"firm": {k: s[k] for k in ("firm", "title", "color", "logo_url", "welcome")}, "client": {"name": c["name"]},
            "status_labels": core.STATUS_LABEL,
            "filings": [{"id": f["id"], "title": f["title"], "status": f["status"], "due_on": f["due_on"], "filed_on": f["filed_on"], "ack_no": f["ack_no"],
                         "extension": f["extension"], "needed": [{"key": i["key"], "label": i["label"]} for i in chaser.missing(f["checklist"])],
                         "received": [i["label"] for i in (f["checklist"] or []) if i.get("status") == "received"]} for f in filings],
            "due": [{"title": d["title"], "due_on": d["due_on"], "source": d["source"]} for d in dues][:20],
            "files": [dict(f) for f in files]}


async def upload(token: str, data: bytes, *, filename: str | None, mime: str | None, filing_id: str | None) -> dict:
    org_id, client_id = await _resolve(token)
    if len(data) > core.MAX_FILE:
        raise PortalError(413, "files can be up to 20 MB")
    if not data:
        raise PortalError(422, "the file is empty")
    async with system_session() as conn:
        if not await site_audit.hit(conn, f"portal-up:{client_id}", UPLOADS_PER_DAY, "24 hours"):
            raise PortalError(429, f"{UPLOADS_PER_DAY} files a day: send the rest tomorrow, or on WhatsApp")
    async with tenant_session(org_id) as conn:
        if filing_id and not (await conn.execute(text("select 1 from app.ca_filings where id = cast(:f as uuid) and client_id = cast(:c as uuid)"),
                                                 {"f": filing_id, "c": client_id})).first():
            filing_id = None  # not this client's filing: matched across their filings instead
    try:
        r = await chaser.receive(org_id, client_id, data, mime=mime, filename=filename, source="client_portal", filing_id=filing_id)
    except core.CaError as e:
        raise PortalError(422, str(e)) from e
    async with tenant_session(org_id) as conn:
        await _used(org_id, client_id, conn)
    return {"matched": r.get("label") if r.get("item") else None, "complete": r.get("complete", False), "still_missing": r.get("still_missing", [])}
