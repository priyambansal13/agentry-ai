"""Self-serve start (agentry/signups.py): the website's plans and checkout, the portal's account opening, and HQ's view."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from agentry import signups, site_audit
from agentry.auth import OrgContext, Principal, client_ip, current_org, require_staff

router = APIRouter(tags=["signups"])


@router.get("/public/plans")
async def plans(currency: Literal["INR", "USD"] = "INR") -> dict:
    return {"plans": await signups.plans(currency)}


class StartIn(BaseModel):
    pack: Annotated[str, Field(min_length=2, max_length=40)]
    business: Annotated[str, Field(min_length=2, max_length=120)]
    website: Annotated[str | None, Field(max_length=200)] = None
    name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Annotated[str | None, Field(max_length=32)] = None
    country: Literal["IN", "US", "GB", "AE", "SG", "AU", "CA"] = "IN"
    token: Annotated[str | None, Field(max_length=4000)] = None  # Turnstile
    source: Annotated[str | None, Field(max_length=300)] = None
    company_url: str | None = None  # honeypot


@router.post("/public/signups", status_code=201)
async def start(body: StartIn, request: Request) -> dict:
    if body.company_url:
        raise HTTPException(422, "please try again")
    ip = client_ip(request)
    if not await site_audit.verify_turnstile(body.token, ip):
        raise HTTPException(400, "the human check didn't pass: please try again")
    try:
        return await signups.start(pack=body.pack, business=body.business, website=body.website, name=body.name, email=str(body.email),
                                   phone=body.phone, country=body.country, ip=ip, source=body.source)
    except signups.SignupError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/public/signups/{sid}")
async def status(sid: str, k: str | None = None) -> dict:
    try:
        return await signups.status(sid, k)
    except signups.SignupError as e:
        raise HTTPException(e.status, str(e)) from e
    except Exception as e:  # a malformed id
        raise HTTPException(404, "not found") from e


class ClaimIn(BaseModel):
    k: Annotated[str, Field(min_length=10, max_length=100)]
    org_id: Annotated[str, Field(min_length=10, max_length=64)]


@router.post("/public/signups/{sid}/claim")
async def claim(sid: str, body: ClaimIn) -> dict:
    try:
        return {"claimed": await signups.claim(sid, body.k, body.org_id)}
    except signups.SignupError as e:
        raise HTTPException(e.status, str(e)) from e


class ProvisionIn(BaseModel):
    k: Annotated[str, Field(min_length=10, max_length=100)]


@router.post("/signups/{sid}/provision")
async def provision(sid: str, body: ProvisionIn, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if ctx.role != "owner":
        raise HTTPException(403, "only the owner can finish setting up")
    try:
        return await signups.provision(sid, body.k, org_id=ctx.org_id, user_email=ctx.principal.email)
    except signups.SignupError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/hq/signups")
async def hq_list(p: Annotated[Principal, Depends(require_staff)]) -> dict:
    return {"items": await signups.listing()}


@router.post("/hq/signups/{sid}/resend")
async def hq_resend(sid: str, p: Annotated[Principal, Depends(require_staff)]) -> dict:
    try:
        await signups.resend(sid)
    except signups.SignupError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"ok": True}
