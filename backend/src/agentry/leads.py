"""Lead engine core (docs/automations/boring-machine.md §3): one person, one voice, one pipeline.

- Identity: phones normalised to E.164 (org's country as default region), emails lower-cased. A contact is found by
  phone first, then email; imports and every channel go through resolve_contact, so the same person arriving by
  form, WhatsApp and old-leads CSV is one contact. merge_contacts folds duplicates.
- Consent & suppression: can_contact() is checked before every outbound touch. Opt-out words revoke consent and add the
  address to the suppression list for that channel.
- One voice: at most one automation owns the conversation with a lead. Higher priority (inbound, warmer) takes over;
  a booking ends outbound sequences.
"""
import re

import phonenumbers
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Inbound beats outbound; hot beats cold (receptionist > chat > speed-to-lead > WhatsApp > reactivation > cold email).
PRIORITY = {"ai_receptionist": 60, "website_chat": 50, "whatsapp_assistant": 45, "speed_to_lead": 40, "inbox_triage": 35,
            "invoice_follow_up": 30, "lead_reactivation": 20, "cold_email": 10}
CONSENT_REQUIRED = {"whatsapp", "sms", "voice"}  # email to businesses relies on legitimate interest + unsubscribe
# "STOP" counts only as a reply on its own ("stop by tomorrow" is not an opt-out); clear phrases count anywhere.
_STOP_ALONE = re.compile(r"^\W*(stop|unsubscribe|opt[\s-]?out|band karo|mat bhejo)\W*(please|now|it|all)?\W*$", re.IGNORECASE)
_OPT_OUT_PHRASE = re.compile(r"\b(unsubscribe|opt[\s-]?out|remove me from|stop (messaging|texting|sending|contacting|emailing)|"
                             r"don'?t (contact|message|text|email) me|no more (messages|emails))\b", re.IGNORECASE)
STAGE_ORDER = ["new", "contacted", "engaged", "qualified", "booked", "showed", "won"]
TERMINAL = {"won", "lost", "disqualified", "opted_out"}


def normalize_phone(raw: str | None, region: str = "IN") -> str | None:
    if not raw or not re.search(r"\d{6,}", re.sub(r"\D", "", raw) or ""):
        return None
    try:
        n = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164) if phonenumbers.is_valid_number(n) else None


def normalize_email(raw: str | None) -> str | None:
    e = (raw or "").strip().lower()
    return e if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) else None


async def _region(conn: AsyncConnection) -> str:
    return (await conn.execute(text("select country from app.org_settings"))).scalar_one_or_none() or "IN"


async def resolve_contact(conn: AsyncConnection, org_id: str, *, name: str | None = None, email: str | None = None,
                          phone: str | None = None, company: str | None = None, source: str) -> str:
    """Find-or-create the one contact for this person; fills in fields that were missing. Runs in the caller's
    tenant transaction."""
    e164 = normalize_phone(phone, await _region(conn))
    em = normalize_email(email)
    row = None
    if e164:
        row = (await conn.execute(text("""select id from app.contacts where phone_e164 = :p and merged_into is null
            order by created_at limit 1"""), {"p": e164})).first()
    if row is None and em:
        row = (await conn.execute(text("""select id from app.contacts where email_norm = :e and merged_into is null
            order by created_at limit 1"""), {"e": em})).first()
    if row:
        await conn.execute(text("""update app.contacts set name = coalesce(name, :n), email = coalesce(email, :e),
            email_norm = coalesce(email_norm, :en), phone = coalesce(phone, :p), phone_e164 = coalesce(phone_e164, :pe),
            company = coalesce(company, :c) where id = :id"""),
            {"n": name, "e": email, "en": em, "p": phone, "pe": e164, "c": company, "id": row.id})
        return str(row.id)
    return str((await conn.execute(text("""insert into app.contacts (org_id, name, email, email_norm, phone, phone_e164, company, source)
        values (:o, :n, :e, :en, :p, :pe, :c, :s) returning id"""),
        {"o": org_id, "n": name, "e": email, "en": em, "p": phone, "pe": e164, "c": company, "s": source})).scalar_one())


async def backfill_identity(conn: AsyncConnection) -> int:
    region = await _region(conn)
    rows = (await conn.execute(text("select id, phone, email from app.contacts where phone_e164 is null or email_norm is null"))).all()
    for r in rows:
        await conn.execute(text("update app.contacts set phone_e164 = coalesce(phone_e164, :p), email_norm = coalesce(email_norm, :e) where id = :id"),
                           {"p": normalize_phone(r.phone, region), "e": normalize_email(r.email), "id": r.id})
    return len(rows)


async def merge_contacts(conn: AsyncConnection, keep: str, dup: str) -> None:
    """Fold `dup` into `keep`: every reference moves over; `dup` stays as a tombstone pointing at `keep`."""
    for table in ("leads", "conversations", "bookings", "invoices", "sequence_enrollments"):
        await conn.execute(text(f"update app.{table} set contact_id = :k where contact_id = :d"), {"k": keep, "d": dup})
    await conn.execute(text("""insert into app.consents (org_id, contact_id, channel, status, source, at)
        select org_id, :k, channel, status, source, at from app.consents where contact_id = :d
        on conflict (org_id, contact_id, channel) do nothing"""), {"k": keep, "d": dup})
    await conn.execute(text("""update app.contacts k set name = coalesce(k.name, d.name), email = coalesce(k.email, d.email),
        email_norm = coalesce(k.email_norm, d.email_norm), phone = coalesce(k.phone, d.phone),
        phone_e164 = coalesce(k.phone_e164, d.phone_e164), company = coalesce(k.company, d.company)
        from app.contacts d where k.id = :k and d.id = :d"""), {"k": keep, "d": dup})
    await conn.execute(text("update app.contacts set merged_into = :k where id = :d"), {"k": keep, "d": dup})


async def dedupe(conn: AsyncConnection) -> int:
    """Merge contacts sharing a phone or email (oldest wins). Returns how many were merged."""
    merged = 0
    for key in ("phone_e164", "email_norm"):
        groups = (await conn.execute(text(f"""select array_agg(id::text order by created_at) ids from app.contacts
            where {key} is not null and merged_into is null group by {key} having count(*) > 1"""))).scalars().all()
        for ids in groups:
            for dup in ids[1:]:
                await merge_contacts(conn, ids[0], dup)
                merged += 1
    return merged


# ---------- consent & suppression ----------

async def address_for(conn: AsyncConnection, contact_id: str, channel: str) -> str | None:
    c = (await conn.execute(text("select phone_e164, email_norm from app.contacts where id = :c"), {"c": contact_id})).first()
    if not c:
        return None
    return c.email_norm if channel == "email" else c.phone_e164


async def can_contact(conn: AsyncConnection, contact_id: str, channel: str) -> tuple[bool, str]:
    addr = await address_for(conn, contact_id, channel)
    if not addr:
        return False, f"no {channel} address"
    suppressed = (await conn.execute(text("""select reason from app.suppressions where address = :a and channel in (:ch, 'all')"""),
                                     {"a": addr, "ch": channel})).scalar_one_or_none()
    if suppressed:
        return False, f"suppressed ({suppressed})"
    if channel in CONSENT_REQUIRED:
        status = (await conn.execute(text("select status from app.consents where contact_id = :c and channel = :ch"),
                                     {"c": contact_id, "ch": channel})).scalar_one_or_none()
        if status != "granted":
            return False, f"no {channel} consent" if status is None else f"{channel} consent revoked"
    return True, "ok"


async def record_consent(conn: AsyncConnection, org_id: str, contact_id: str, channel: str, granted: bool, source: str) -> None:
    await conn.execute(text("""insert into app.consents (org_id, contact_id, channel, status, source) values (:o, :c, :ch, :s, :src)
        on conflict (org_id, contact_id, channel) do update set status = excluded.status, source = excluded.source, at = now()"""),
        {"o": org_id, "c": contact_id, "ch": channel, "s": "granted" if granted else "revoked", "src": source})


async def opt_out(conn: AsyncConnection, org_id: str, contact_id: str, channel: str, source: str) -> None:
    """Customer said stop: revoke consent, suppress the address, end outbound sequences, mark leads opted out."""
    addr = await address_for(conn, contact_id, channel)
    await record_consent(conn, org_id, contact_id, channel, False, source)
    if addr:
        await conn.execute(text("""insert into app.suppressions (org_id, channel, address, reason) values (:o, :ch, :a, 'opt_out')
            on conflict do nothing"""), {"o": org_id, "ch": channel, "a": addr})
    await conn.execute(text("""update app.sequence_enrollments set status = 'stopped', stop_reason = 'opted_out', updated_at = now()
        where contact_id = :c and status in ('active','paused')"""), {"c": contact_id})
    await conn.execute(text("update app.leads set stage = 'opted_out', updated_at = now() where contact_id = :c and stage not in ('won')"),
                       {"c": contact_id})


def is_opt_out(message: str) -> bool:
    m = message or ""
    return bool(_STOP_ALONE.search(m) or _OPT_OUT_PHRASE.search(m))


# ---------- one voice + pipeline ----------

async def claim(conn: AsyncConnection, lead_id: str, automation: str, *, inbound: bool = False, idle_days: int = 14) -> bool:
    """May `automation` talk to this lead now? Takes ownership if allowed. Inbound contact always takes over."""
    row = (await conn.execute(text("select owner_automation, owner_since, stage from app.leads where id = :l for update"),
                              {"l": lead_id})).first()
    if row is None or row.stage in TERMINAL:
        return False
    owner = row.owner_automation
    idle = row.owner_since is None or (await conn.execute(
        text("select now() - cast(:t as timestamptz) > make_interval(days => :d)"), {"t": row.owner_since, "d": idle_days})).scalar_one()
    allowed = inbound or owner in (None, automation) or idle or PRIORITY.get(automation, 0) > PRIORITY.get(owner, 0)
    if allowed and owner != automation:
        await conn.execute(text("update app.leads set owner_automation = :a, owner_since = now(), updated_at = now() where id = :l"),
                           {"a": automation, "l": lead_id})
        if owner:  # the previous owner's outbound sequences stop: one voice
            await conn.execute(text("""update app.sequence_enrollments e set status = 'stopped', stop_reason = :r, updated_at = now()
                from app.sequences s where s.id = e.sequence_id and e.subject_id = :l and s.automation_key = :prev
                and e.status in ('active','paused')"""), {"r": f"taken over by {automation}", "l": lead_id, "prev": owner})
    return allowed


async def advance(conn: AsyncConnection, lead_id: str, stage: str) -> None:
    """Move a lead forward in the pipeline (never backwards past booked, never out of a terminal stage)."""
    cur = (await conn.execute(text("select stage from app.leads where id = :l"), {"l": lead_id})).scalar_one_or_none()
    if cur is None or cur in TERMINAL:
        return
    if stage in STAGE_ORDER and cur in STAGE_ORDER and STAGE_ORDER.index(stage) <= STAGE_ORDER.index(cur):
        return
    await conn.execute(text("update app.leads set stage = :s, updated_at = now() where id = :l"), {"s": stage, "l": lead_id})
