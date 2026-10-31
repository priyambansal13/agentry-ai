"""The Calendar page (9.3): appointments by day, marking attendance, and the waitlist the concierge offers freed slots to."""
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, current_org
from agentry.automations import appointment_concierge as concierge
from agentry.db import tenant_session
from agentry.features import enabled_automations
from agentry.leads import resolve_contact

router = APIRouter()


def _need(ctx: OrgContext, action: str) -> None:
    if not ctx.can("calendar", action):
        raise HTTPException(403, "you can't see the calendar" if action == "read" else "you can't change appointments")


@router.get("/org/calendar")
async def calendar(ctx: Annotated[OrgContext, Depends(current_org)], start: date | None = None, days: Annotated[int, Query(ge=1, le=31)] = 7) -> dict:
    _need(ctx, "read")
    async with tenant_session(ctx.org_id) as conn:
        tz = ZoneInfo((await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata")
        start = start or datetime.now(tz).date()
        lo = datetime.combine(start, time.min, tz)
        rows = (await conn.execute(text("""select b.id::text, b.starts_at, b.ends_at, b.status, b.source, b.concierge, b.cancel_reason,
                s.name as service, st.name as staff, k.name as contact, k.phone_e164 as phone, k.email, b.conversation_id::text
            from app.bookings b join app.services s on s.id = b.service_id join app.staff st on st.id = b.staff_id
            left join app.contacts k on k.id = b.contact_id
            where b.starts_at >= :lo and b.starts_at < :hi order by b.starts_at"""), {"lo": lo, "hi": lo + timedelta(days=days)})).mappings().all()
        waitlist = (await conn.execute(text("""select w.id::text, w.status, w.notes, w.offered, w.created_at, s.name as service, s.key as service_key,
                k.name as contact, k.phone_e164 as phone, k.email
            from app.waitlist w join app.services s on s.id = w.service_id join app.contacts k on k.id = w.contact_id
            where w.status in ('waiting','offered') order by w.created_at"""))).mappings().all()
        services = (await conn.execute(text("select key, name, minutes from app.services where active order by name"))).mappings().all()
        status, _cfg = await concierge.config(conn)
        on = "appointment_concierge" in await enabled_automations(conn)
    show_contact = ctx.can("conversation", "read")
    items = []
    for r in rows:
        d = dict(r)
        d["day"] = r["starts_at"].astimezone(tz).date().isoformat()
        d["time"] = r["starts_at"].astimezone(tz).strftime("%I:%M %p").lstrip("0")
        d["awaiting"] = (r["concierge"] or {}).get("awaiting")
        if not show_contact:
            d["phone"] = d["email"] = None
        items.append(d)
    return {"start": start.isoformat(), "days": days, "timezone": str(tz), "items": items,
            "waitlist": [dict(w, phone=w["phone"] if show_contact else None, email=w["email"] if show_contact else None) for w in waitlist],
            "services": [dict(s) for s in services], "concierge": status if on else None, "can_act": ctx.can("calendar", "act")}


class Mark(BaseModel):
    status: Literal["showed", "no_show", "cancelled", "confirmed"]


@router.post("/org/bookings/{booking_id}/status")
async def mark(booking_id: str, b: Mark, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    _need(ctx, "act")
    async with tenant_session(ctx.org_id) as conn:
        cur = (await conn.execute(text("select status from app.bookings where id = cast(:i as uuid)"), {"i": booking_id})).scalar_one_or_none()
    if cur is None:
        raise HTTPException(404, "appointment not found")
    if cur == "cancelled":
        raise HTTPException(409, "this appointment was cancelled")
    try:
        out = await concierge.mark(ctx.org_id, booking_id, b.status, ctx.principal.user_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="booking.marked",
                           target_type="booking", target_id=booking_id, ip=client_ip(request), metadata={"status": b.status})
    return out


class WaitlistIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    phone: str | None = None
    email: str | None = None
    service_key: str
    notes: Annotated[str | None, Field(max_length=500)] = None


@router.post("/org/waitlist")
async def add_waitlist(b: WaitlistIn, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    _need(ctx, "act")
    if not (b.phone or b.email):
        raise HTTPException(422, "add a phone number or an email so we can reach them")
    async with tenant_session(ctx.org_id) as conn:
        sid = (await conn.execute(text("select id from app.services where key = :k and active"), {"k": b.service_key})).scalar_one_or_none()
        if not sid:
            raise HTTPException(422, "unknown service")
        cid = await resolve_contact(conn, ctx.org_id, name=b.name, phone=b.phone, email=b.email, source="waitlist")
        if (await conn.execute(text("select 1 from app.waitlist where contact_id = :c and service_id = :s and status in ('waiting','offered')"),
                               {"c": cid, "s": sid})).first():
            raise HTTPException(409, "they're already on the waitlist for this")
        wid = (await conn.execute(text("""insert into app.waitlist (org_id, contact_id, service_id, notes, created_by)
            values (:o, :c, :s, :n, :u) returning id::text"""), {"o": ctx.org_id, "c": cid, "s": sid, "n": b.notes, "u": ctx.principal.user_id})).scalar_one()
    return {"id": wid}


@router.delete("/org/waitlist/{wid}")
async def remove_waitlist(wid: str, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    _need(ctx, "act")
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("update app.waitlist set status = 'removed' where id = cast(:i as uuid) and status in ('waiting','offered')"),
                                {"i": wid})).rowcount
    if not n:
        raise HTTPException(404, "not on the waitlist")
    return {"removed": True}
