"""Unauthenticated endpoints used by the marketing site."""
import time
from collections import defaultdict, deque
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import text

from agentry import sales
from agentry.auth import client_ip
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.events import emit

router = APIRouter(prefix="/public", tags=["public"])

_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str, limit: int = 5, window: float = 600) -> None:
    """Small in-process limiter for the public form (5 requests / 10 min / IP). Replace with Redis when scaled out."""
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, please try again later.")
    q.append(now)


class DemoRequest(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Annotated[str | None, Field(max_length=32)] = None
    company: Annotated[str | None, Field(max_length=160)] = None
    website: HttpUrl | None = None
    niche: Literal["agency_or_firm", "clinic_or_appointments", "home_services", "other"] | None = None
    message: Annotated[str | None, Field(max_length=2000)] = None
    # Honeypot: real users never see this field.
    company_url: str | None = None


@router.post("/demo-requests", status_code=status.HTTP_201_CREATED)
async def create_demo_request(body: DemoRequest, request: Request) -> dict:
    _rate_limit(client_ip(request) or "unknown")
    if body.company_url:
        return {"ok": True}  # bot: pretend success, store nothing
    async with system_session() as conn:
        row = await conn.execute(
            text("""insert into app.demo_requests (name, email, phone, company, website, niche, message)
                    values (:name, :email, :phone, :company, :website, :niche, :message) returning id"""),
            {**body.model_dump(exclude={"company_url"}), "website": str(body.website) if body.website else None},
        )
        demo_id = str(row.scalar_one())
        await emit(conn, None, "demo_request.created", {"demo_request_id": demo_id})
    return {"ok": True, "id": demo_id}


@router.get("/demos/{slug}")
async def public_demo(slug: str) -> dict:
    """What a prospect's demo page needs: their name, brand, services and the widget key. Expired demos 410."""
    async with system_session() as conn:
        row = (await conn.execute(text("""
            select o.id, o.name, s.website, s.brand, s.widget_key, s.persona, s.demo_expires_at, s.industry_pack
            from auth.organization o join app.org_settings s on s.org_id = o.id
            where o.slug = :slug and s.status = 'demo'"""), {"slug": slug})).mappings().first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "demo not found")
        if row["demo_expires_at"] and row["demo_expires_at"].timestamp() < time.time():
            raise HTTPException(status.HTTP_410_GONE, "this demo has expired")
        services = (await conn.execute(text("select name, minutes, price from app.services where org_id = :o and active order by name"),
                                       {"o": row["id"]})).mappings().all()
    return {"name": row["name"], "website": row["website"], "brand": row["brand"], "widget_key": row["widget_key"],
            "agent_name": (row["persona"] or {}).get("name"), "pack": row["industry_pack"],
            "expires_at": row["demo_expires_at"], "services": [dict(s) for s in services]}


@router.get("/site-chat")
async def site_chat() -> dict:
    """The widget key for Agentry's own website chat (the landing page dogfoods the product)."""
    async with system_session() as conn:
        key = (await conn.execute(text("""select s.widget_key from app.org_settings s
            join auth.organization o on o.id = s.org_id where o.slug = 'agentry'"""))).scalar_one_or_none()
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site chat not configured")
    return {"widget_key": key}


@router.get("/proposals/{token}")
async def public_proposal(token: str) -> dict:
    """A sent proposal, for its private link on the website. The first view alerts the Agentry team."""
    p, first = await sales.view_proposal(token)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if first:
        async with system_session() as conn:
            await emit(conn, None, "proposal.viewed", {"proposal_id": str(p["id"])})
    return {"snapshot": p["snapshot"], "sent_at": p["sent_at"], "reply_to": settings.smtp_user or settings.ops_email}


# ---------- cold email unsubscribe (Phase 5.4): the link in every email, and one-click List-Unsubscribe ----------

async def _unsub_target(token: str) -> tuple[str, str]:
    from agentry.secrets import SecretError, verify_state
    try:
        data = verify_state(token)
    except (SecretError, ValueError, KeyError) as e:
        raise HTTPException(404, "this unsubscribe link isn't valid") from e
    if data.get("t") != "unsub":
        raise HTTPException(404, "this unsubscribe link isn't valid")
    return data["org"], data["p"]


@router.get("/unsubscribe/{token}")
async def unsubscribe_info(token: str) -> dict:
    org_id, pid = await _unsub_target(token)
    from agentry.db import tenant_session
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select o.name, p.email, p.status, p.stop_reason from app.prospects p
            join auth.organization o on o.id = p.org_id where p.id = cast(:p as uuid)"""), {"p": pid})).mappings().first()
    if not row:
        raise HTTPException(404, "this unsubscribe link isn't valid")
    return {"business": row["name"], "email": row["email"], "unsubscribed": row["stop_reason"] == "unsubscribed"}


@router.post("/unsubscribe/{token}")
async def unsubscribe(token: str) -> dict:
    """No sign-in, no questions: the address is never emailed again by this business (RFC 8058 one-click)."""
    from agentry.automations.cold_email.replies import unsubscribe as do_unsubscribe
    from agentry.db import tenant_session
    org_id, pid = await _unsub_target(token)
    async with tenant_session(org_id) as conn:
        if not await do_unsubscribe(conn, org_id, pid, "unsubscribe_link"):
            raise HTTPException(404, "this unsubscribe link isn't valid")
    return {"unsubscribed": True}


@router.get("/content-image/{token}", include_in_schema=False)
async def content_image(token: str):
    """A quote card at a signed, expiring public address: Instagram fetches the image from a URL when posting (JPEG only)."""
    import io

    from fastapi.responses import Response
    from PIL import Image

    from agentry.automations.content import sources
    from agentry.db import tenant_session
    from agentry.secrets import SecretError, verify_state
    try:
        t = verify_state(token)
    except (SecretError, ValueError) as e:
        raise HTTPException(404, "not found") from e
    if t.get("p") != "content-image":
        raise HTTPException(404, "not found")
    async with tenant_session(t["org"]) as conn:
        rel = (await conn.execute(text("select image_path from app.content_posts where id = cast(:i as uuid)"), {"i": t["post"]})).scalar_one_or_none()
    path = sources.resolve(rel)
    if not path:
        raise HTTPException(404, "not found")
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=92)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=600"})


@router.get("/quotes/{token}.pdf", include_in_schema=False)
async def quote_pdf(token: str) -> Response:
    """A quote sent to a customer (the link is the secret: 32 random characters)."""
    from agentry.automations.catalog_quotes import pdf, settings_of
    from agentry.automations.content import brand
    if len(token) < 20:
        raise HTTPException(404, "not found")
    async with system_session() as conn:
        org = (await conn.execute(text("select org_id from app.quotes where token = :t"), {"t": token})).scalar_one_or_none()
    if not org:
        raise HTTPException(404, "not found")
    async with tenant_session(org) as conn:
        q = (await conn.execute(text("select * from app.quotes where token = :t"), {"t": token})).mappings().one()
        _s, cfg = await settings_of(conn)
        kit = await brand.get_kit(conn, org)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org})).scalar_one_or_none() or ""
    return Response(pdf(dict(q), business, cfg, kit), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{q["number"]}.pdf"', "Cache-Control": "private, max-age=300"})


# ---------- hiring: the public apply link (ROADMAP-V3 A5) ----------

async def _job(token: str) -> tuple[str, dict]:
    if len(token) < 16:
        raise HTTPException(404, "not found")
    async with system_session() as conn:
        org = (await conn.execute(text("select org_id from app.jobs where token = :t and status = 'open'"), {"t": token})).scalar_one_or_none()
    if not org:
        raise HTTPException(404, "This job isn't open any more.")
    async with tenant_session(org) as conn:
        job = dict((await conn.execute(text("""select j.*, o.name as business from app.jobs j join auth.organization o on o.id = j.org_id
            where j.token = :t"""), {"t": token})).mappings().one())
    return org, job


@router.get("/jobs/{token}", include_in_schema=False)
async def job_page(token: str) -> Response:
    from html import escape
    _org, j = await _job(token)
    must = "".join(f"<li>{escape(m)}</li>" for m in j["must_have"])
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(j['title'])} at {escape(j['business'])}</title><style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:32px auto;padding:0 16px;color:#1f2a1a;background:#fbfbf7}}
label{{display:block;margin:12px 0 4px;font-weight:600}}input{{width:100%;padding:10px;border:2px solid #d8d8cf;border-radius:10px;box-sizing:border-box}}
button{{margin-top:16px;padding:12px 20px;border:0;border-radius:10px;background:#1f2a1a;color:#fff;font-weight:700}}p.m{{color:#6b6b60}}</style></head><body>
<p class="m">{escape(j['business'])}</p><h1>{escape(j['title'])}</h1><p class="m">{escape(j.get('location') or '')}</p>
<p style="white-space:pre-wrap">{escape(j['description'])}</p>{f'<h3>What you need</h3><ul>{must}</ul>' if must else ''}
<h2>Apply</h2><form method="post" action="/public/jobs/{escape(token)}/apply" enctype="multipart/form-data">
<label for="n">Your name</label><input id="n" name="name" required maxlength="120"><label for="e">Email</label><input id="e" name="email" type="email" required>
<label for="p">Mobile / WhatsApp</label><input id="p" name="phone" maxlength="20"><label for="c">CV (PDF or Word, up to 5 MB)</label>
<input id="c" name="cv" type="file" accept=".pdf,.docx,.txt" required><button type="submit">Send my application</button></form>
<p class="m" style="margin-top:24px;font-size:13px">Your CV is read by {escape(j['business'])}'s hiring assistant (AI) and their team. It isn't shared with anyone else.</p></body></html>"""
    return Response(page, media_type="text/html")


@router.post("/jobs/{token}/apply", include_in_schema=False)
async def job_apply(token: str, request: Request) -> Response:
    from agentry.automations.hiring import add_candidate
    _rate_limit(f"apply:{client_ip(request)}", limit=5, window=3600)
    org, j = await _job(token)
    form = await request.form()
    cv = form.get("cv")
    if not cv or not hasattr(cv, "read"):
        raise HTTPException(422, "attach your CV")
    data = await cv.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(422, "the CV can be up to 5 MB")
    try:
        await add_candidate(org, str(j["id"]), data, cv.filename or "cv.pdf", source="apply_link", name=str(form.get("name") or "")[:120] or None,
                            email=str(form.get("email") or "")[:200] or None, phone=str(form.get("phone") or "")[:20] or None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return Response("<!doctype html><meta charset=utf-8><body style='font-family:system-ui;max-width:640px;margin:48px auto;padding:0 16px'>"
                    "<h1>Thank you!</h1><p>Your application has been sent. The team will be in touch.</p>", media_type="text/html")
