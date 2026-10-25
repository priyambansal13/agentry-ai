"""Agentry HQ: platform-wide views for Agentry staff only (system role crosses tenants)."""
import asyncio
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from agentry import audit, billing, clients, demo_studio, sales
from agentry.auth import Principal, require_staff
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.features import enabled_automations
from agentry.knowledge import UnsafeUrl
from agentry.notify.email import send_email
from agentry.packs import list_packs
from agentry.voice import telephony

router = APIRouter(prefix="/hq", tags=["agentry-hq"])


@router.get("/orgs")
async def list_orgs(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with system_session() as conn:
        rows = (await conn.execute(text("""
            select o.id, o.name, o.slug, s.status, s.industry_pack, s.country, s.currency,
                   (select count(*) from auth.member m where m."organizationId" = o.id) as members,
                   (select count(*) from app.automation_instances a where a.org_id = o.id) as automations,
                   (select count(*) from app.onboarding_progress p where p.org_id = o.id and p.status = 'done') as steps_done,
                   (select count(*) from app.onboarding_progress p where p.org_id = o.id) as steps_total,
                   (select string_agg(p.blocker, '; ') from app.onboarding_progress p where p.org_id = o.id and p.status = 'blocked') as blockers
            from auth.organization o left join app.org_settings s on s.org_id = o.id
            order by o.name"""))).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/demo-requests")
async def demo_requests(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with system_session() as conn:
        rows = (await conn.execute(text("select * from app.demo_requests order by created_at desc limit 100"))).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/demo-requests/{demo_id}")
async def demo_request(demo_id: str, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    try:
        d = await sales.get(demo_id)
    except sales.SalesError as e:
        raise HTTPException(404, str(e)) from e
    async with system_session() as conn:
        proposals = (await conn.execute(text("""select id, token, sent_at, first_viewed_at, views from app.proposals
            where demo_request_id = cast(:i as uuid) order by sent_at desc"""), {"i": demo_id})).mappings().all()
        messages = (await conn.execute(text("""select kind, from_address, subject, snippet, received_at from app.demo_request_messages
            where demo_request_id = cast(:i as uuid) order by received_at desc"""), {"i": demo_id})).mappings().all()
    return d | {"demo_url": sales.demo_link(d), "link_problem": sales.public_link_problem(),
                "proposals": [dict(p) | {"url": sales.proposal_link(p["token"])} for p in proposals],
                "messages": [dict(m) for m in messages],
                "suggested_pack": sales.NICHE_PACK.get(d["niche"] or ""),
                "follow_up_days": list(sales.FOLLOW_UP_DAYS)}


class DemoRequestUpdate(BaseModel):
    status: Literal["new", "demo_built", "demo_sent", "in_talks", "won", "lost"] | None = None
    notes: Annotated[str | None, Field(max_length=5000)] = None
    demo_org_id: str | None = None  # after "Build demo"
    client_org_id: str | None = None  # after "Convert to client"


@router.patch("/demo-requests/{demo_id}")
async def update_demo_request(demo_id: str, body: DemoRequestUpdate, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    fields = body.model_dump(exclude_none=True)
    if body.demo_org_id:
        async with system_session() as conn:
            fields["demo_slug"] = (await conn.execute(text("select slug from auth.organization where id = :o"), {"o": body.demo_org_id})).scalar_one_or_none()
        fields.setdefault("status", "demo_built")
    if body.client_org_id:
        fields.setdefault("status", "won")
    try:
        return await sales.update(demo_id, **fields)
    except sales.SalesError as e:
        raise HTTPException(404, str(e)) from e


class DemoSend(BaseModel):
    video_url: Annotated[str | None, Field(max_length=500, pattern=r"^https?://")] = None
    note: Annotated[str | None, Field(max_length=2000)] = None


class ProposalSend(BaseModel):
    email: EmailStr
    snapshot: dict  # ProposalDocument props, exactly as shown in the builder
    plan: dict | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    demo_request_id: str | None = None


@router.post("/proposals", status_code=201)
async def send_proposal(body: ProposalSend, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Save the proposal as it was shown, give it a private link on the website and email it to the client."""
    if problem := sales.public_link_problem():
        raise HTTPException(409, problem.replace("Demo links", "Proposal links"))
    if not body.snapshot.get("agents"):
        raise HTTPException(422, "choose at least one agent")
    p = await sales.create_proposal(email=body.email, snapshot=body.snapshot, plan=body.plan, note=body.note,
                                    demo_request_id=body.demo_request_id, sent_by=staff.user_id)
    contact = body.snapshot.get("contact")
    try:
        await asyncio.to_thread(send_email, body.email, *sales.proposal_email(body.snapshot, contact, p["url"], body.note))
    except OSError as e:
        raise HTTPException(502, f"couldn't send the email: {e}") from e
    if body.demo_request_id:
        d = await sales.get(body.demo_request_id)
        if d["status"] in ("new", "demo_built", "demo_sent"):
            await sales.update(body.demo_request_id, status="in_talks")  # a proposal means you're talking: no more demo follow-ups
    return {"id": str(p["id"]), "url": p["url"], "sent_at": p["sent_at"]}


@router.post("/demo-requests/{demo_id}/preview-email")
async def preview_demo_email(demo_id: str, body: DemoSend, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    d = await sales.get(demo_id)
    if not d["demo_slug"]:
        raise HTTPException(409, "build their demo first")
    subject, text_ = sales.demo_email(d, body.video_url, body.note)
    return {"to": d["email"], "subject": subject, "body": text_}


@router.post("/demo-requests/{demo_id}/send")
async def send_demo(demo_id: str, body: DemoSend, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Email the prospect their demo link (and the walkthrough video), then follow up on days 2, 5 and 10 unless the
    status changes (they reply -> mark "in talks")."""
    d = await sales.get(demo_id)
    if not d["demo_slug"]:
        raise HTTPException(409, "build their demo first")
    if problem := sales.public_link_problem():
        raise HTTPException(409, problem)
    subject, text_ = sales.demo_email(d, body.video_url, body.note)
    try:
        await asyncio.to_thread(send_email, d["email"], subject, text_)
    except OSError as e:
        raise HTTPException(502, f"couldn't send the email: {e}") from e
    sent_at = datetime.now(UTC)
    row = await sales.update(demo_id, status="demo_sent", video_url=body.video_url, demo_sent_at=sent_at, followups_sent=0)
    async with system_session() as conn:
        await emit(conn, None, "demo.sent", {"demo_request_id": demo_id, "sent_at": sent_at.isoformat(), "by": staff.user_id})
    return row


@router.get("/packs")
async def packs(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    return {"items": list_packs()}


class DemoPreview(BaseModel):
    url: Annotated[str, Field(min_length=4, max_length=500)]


@router.post("/demos/preview")
async def demo_preview(body: DemoPreview, _: Annotated[Principal, Depends(require_staff)]) -> dict:
    try:
        return await demo_studio.preview(body.url)
    except (UnsafeUrl, ValueError) as e:
        raise HTTPException(422, str(e)) from e


class DemoBuild(BaseModel):
    org_id: str
    url: Annotated[str, Field(min_length=4, max_length=500)]
    pack: Literal["b2b-agency", "dental-clinic", "home-services"]


@router.post("/demos", status_code=201)
async def build_demo(body: DemoBuild, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    try:
        result = await demo_studio.build_demo(body.org_id, url=body.url, pack_key=body.pack, created_by=staff.user_id)
    except (UnsafeUrl, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    async with system_session() as conn:
        await audit.record(conn, org_id=body.org_id, actor_type="agentry_staff", actor_user_id=staff.user_id,
                           action="demo.built", target_type="organization", target_id=body.org_id,
                           metadata={"url": body.url, "pack": body.pack})
    return result


@router.get("/demos")
async def list_demos(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with system_session() as conn:
        rows = (await conn.execute(text("""
            select o.id, o.name, o.slug, s.website, s.industry_pack, s.demo_expires_at, s.brand,
                   (select count(*) from app.conversations c where c.org_id = o.id and c.channel = 'web_chat') as chats
            from app.org_settings s join auth.organization o on o.id = s.org_id
            where s.status = 'demo' order by s.created_at desc"""))).mappings().all()
    return {"items": [dict(r) for r in rows]}


# ---------- onboarding clients ----------

@router.get("/catalog")
async def automation_catalog(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    return {"automations": clients.catalog()}


class NewClient(BaseModel):
    org_id: Annotated[str, Field(min_length=8, max_length=64)]
    country: Literal["IN", "US", "GB", "AE", "SG", "AU", "CA"] = "IN"
    timezone: Annotated[str, Field(min_length=3, max_length=64)] = "Asia/Kolkata"
    currency: Literal["INR", "USD", "EUR", "GBP", "AED"] = "INR"
    website: Annotated[str | None, Field(max_length=300)] = None
    automations: Annotated[list[str], Field(min_length=1, max_length=20)]
    plan: billing.PricingPlan | None = None


@router.post("/clients", status_code=201)
async def create_client(body: NewClient, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Provision a client the dashboard has just created (organisation + owner invitation)."""
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise HTTPException(422, "unknown timezone") from e
    if body.plan and body.plan.currency != body.currency:
        raise HTTPException(422, "the plan's currency must match the client's currency")
    async with system_session() as conn:
        name = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": body.org_id})).scalar_one_or_none()
    if name is None:
        raise HTTPException(404, "organisation not found")
    async with tenant_session(body.org_id) as conn:
        try:
            features = await clients.provision(conn, body.org_id, name=name, country=body.country, timezone=body.timezone,
                                               currency=body.currency, website=body.website, automations=body.automations,
                                               plan=body.plan, staff_user_id=staff.user_id)
        except clients.ProvisionError as e:
            raise HTTPException(409, str(e)) from e
    return {"org_id": body.org_id, **features}


class AutomationSwitch(BaseModel):
    enabled: bool


@router.put("/orgs/{org_id}/automations/{key}")
async def switch_automation(org_id: str, key: str, body: AutomationSwitch, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    async with tenant_session(org_id) as conn:
        try:
            return await clients.set_automation(conn, org_id, key, body.enabled, staff.user_id)
        except clients.ProvisionError as e:
            raise HTTPException(409, str(e)) from e


@router.post("/orgs/{org_id}/open")
async def open_portal(org_id: str, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Agentry staff open a client's portal (to do their setup). Recorded in the client's audit log."""
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select o.name, o.slug, s.status from app.org_settings s
            join auth.organization o on o.id = s.org_id"""))).mappings().first()
        if not row:
            raise HTTPException(404, "client not found or not set up")
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id, action="staff.opened_portal")
    return {"id": org_id, **dict(row)}


# ---------- phone numbers (PHASE-4-VOICE.md 4.3) ----------

@router.get("/phone-numbers")
async def phone_numbers(_: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Agentry's numbers on LiveKit and the client each one answers for."""
    try:
        nums = await telephony.project_numbers()
    except telephony.TelephonyError as e:
        raise HTTPException(502, str(e)) from e
    async with system_session() as conn:
        owners = {r.account_ref: {"org_id": r.org_id, "name": r.name} for r in (await conn.execute(text("""
            select c.account_ref, c.org_id, o.name from app.connections c join auth.organization o on o.id = c.org_id
            where c.provider = 'phone' and c.status <> 'revoked'"""))).all()}
    return {"items": [n | {"client": owners.get(n["number"])} for n in nums]}


class PhoneAssign(BaseModel):
    number: str = Field(min_length=8, max_length=20)


@router.put("/orgs/{org_id}/phone")
async def assign_phone(org_id: str, body: PhoneAssign, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    """Give a client one of Agentry's numbers: calls to it are answered by the client's AI receptionist."""
    async with tenant_session(org_id) as conn:
        if "ai_receptionist" not in await enabled_automations(conn):
            raise HTTPException(409, "switch on the AI receptionist for this client first")
    try:
        r = await telephony.assign(org_id, body.number, staff.user_id)
    except telephony.TelephonyError as e:
        raise HTTPException(409, str(e)) from e
    async with tenant_session(org_id) as conn:
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id,
                           action="phone.assigned", target_type="connection", target_id=r["number"])
    return r


@router.delete("/orgs/{org_id}/phone/{number}")
async def unassign_phone(org_id: str, number: str, staff: Annotated[Principal, Depends(require_staff)]) -> dict:
    await telephony.unassign(org_id, number)
    async with tenant_session(org_id) as conn:
        await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff.user_id,
                           action="phone.unassigned", target_type="connection", target_id=number)
    return {"number": number, "assigned": False}
