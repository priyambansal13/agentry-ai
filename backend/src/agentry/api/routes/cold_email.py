"""Cold email in the portal (Phase 5.1-5.3): build prospect lists, see the funnel, review first lines, export.

Who can do what: owners and managers create campaigns and approve, edit or drop lines (automation:configure);
front desk can look (conversation:read); finance and viewers can't see prospects at all.
"""
import csv
import io
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, client_ip, require
from agentry.automations.cold_email import replies, sending
from agentry.automations.cold_email.pipeline import create_campaign, funnel
from agentry.config import settings
from agentry.db import tenant_session
from agentry.features import require_page
from agentry.invoices import parse_file

router = APIRouter(prefix="/org/cold-email", dependencies=[Depends(require_page("cold-email"))])
Viewer = Annotated[OrgContext, Depends(require("conversation", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]
MAX_ROWS = 500


async def _config(conn) -> dict:
    cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'cold_email'"))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(404, "cold email isn't switched on for this business")
    return cfg or {}


class NewCampaign(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    query: Annotated[str, Field(min_length=2, max_length=120)]  # e.g. "dental clinic"
    city: Annotated[str, Field(min_length=2, max_length=80)]
    limit: Annotated[int, Field(ge=5, le=200)] = 50
    min_rating: Annotated[float | None, Field(ge=1, le=5)] = None
    min_reviews: Annotated[int | None, Field(ge=0, le=100000)] = None


async def _create(conn, ctx: OrgContext, request: Request, name: str, settings: dict, rows: list[dict] | None = None) -> str:
    cfg = await _config(conn)
    settings |= {"allow_catch_all": bool(cfg.get("allow_catch_all")), "allow_eu_uk": bool(cfg.get("allow_eu_uk"))}
    cid = await create_campaign(conn, ctx.org_id, name=name, settings=settings, user_id=ctx.principal.user_id, rows=rows)
    await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                       action="cold_email.campaign_created", target_type="campaign", target_id=cid, ip=client_ip(request),
                       metadata={"name": name, "source": settings["source"]})
    return cid


@router.post("/campaigns", status_code=201)
async def new_campaign(body: NewCampaign, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        cid = await _create(conn, ctx, request, body.name, {"source": "places", **body.model_dump(exclude={"name"})})
    return {"id": cid, "build_status": "building"}


@router.post("/campaigns/csv", status_code=201)
async def new_campaign_from_file(request: Request, ctx: Editor, name: Annotated[str, Form(min_length=2, max_length=120)],
                                 file: Annotated[UploadFile, File()], min_rating: Annotated[float | None, Form()] = None,
                                 min_reviews: Annotated[int | None, Form()] = None) -> dict:
    """A list exported from Apollo, a directory or a spreadsheet: one business per row (name and website at least)."""
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 5 MB)")
    rows = parse_file(data, file.filename or "list.csv")
    keys = {"company": "name", "business": "name", "business_name": "name", "company_name": "name", "url": "website",
            "site": "website", "domain": "website", "rating": "rating", "reviews": "reviews", "review_count": "reviews"}
    norm = []
    for r in rows:
        d = {}
        for k, v in r.items():
            k2 = str(k or "").strip().lower().replace(" ", "_")
            d[keys.get(k2, k2)] = str(v).strip() if v is not None else None
        if d.get("name") or d.get("website"):
            norm.append(d)
    if not norm:
        raise HTTPException(422, "no businesses found: the file needs a name or website column")
    if len(norm) > MAX_ROWS:
        raise HTTPException(422, f"at most {MAX_ROWS} businesses per campaign")
    async with tenant_session(ctx.org_id) as conn:
        cid = await _create(conn, ctx, request, name, {"source": "csv", "min_rating": min_rating, "min_reviews": min_reviews}, norm)
    return {"id": cid, "build_status": "building", "businesses": len(norm)}


@router.get("/campaigns")
async def list_campaigns(ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _config(conn)
        rows = (await conn.execute(text("""
            select c.id, c.name, c.status, c.settings, c.build_status, c.build_error, c.stats, c.created_at,
                   (select count(*) from app.prospect_companies pc where pc.campaign_id = c.id) as found,
                   (select count(*) from app.prospects p where p.campaign_id = c.id) as verified,
                   (select count(*) from app.prospects p where p.campaign_id = c.id and p.review = 'approved') as approved,
                   (select count(*) from app.prospects p where p.campaign_id = c.id and p.review in ('pending','needs_attention')) as to_review,
                   (select count(distinct prospect_id) from app.email_events ev where ev.campaign_id = c.id and ev.kind = 'sent') as emailed,
                   (select count(*) from app.prospects p where p.campaign_id = c.id and p.reply_kind = 'interested') as interested
            from app.campaigns c where c.kind = 'cold_email' order by c.created_at desc"""))).mappings().all()
    return {"items": [dict(r) for r in rows], "can_edit": ctx.can("automation", "configure")}


async def _campaign(conn, cid: str) -> dict:
    c = (await conn.execute(text("""select id, name, status, settings, build_status, build_error, stats, created_at from app.campaigns
        where id = cast(:c as uuid) and kind = 'cold_email'"""), {"c": cid})).mappings().first()
    if not c:
        raise HTTPException(404, "campaign not found")
    return dict(c)


@router.get("/campaigns/{cid}")
async def get_campaign(cid: str, ctx: Viewer) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        c = await _campaign(conn, cid)
        return {**c, "funnel": await funnel(conn, cid), "sending": await _sending(conn, cid), "can_edit": ctx.can("automation", "configure"),
                "mock": settings.cold_email_providers == "mock"}


async def _sending(conn, cid: str) -> dict:
    ev = dict((await conn.execute(text("""select kind, count(distinct prospect_id) from app.email_events where campaign_id = cast(:c as uuid)
        group by kind"""), {"c": cid})).all())
    replies_by = dict((await conn.execute(text("""select reply_kind, count(*) from app.prospects where campaign_id = cast(:c as uuid)
        and reply_kind is not null group by reply_kind"""), {"c": cid})).all())
    st = dict((await conn.execute(text("select status, count(*) from app.prospects where campaign_id = cast(:c as uuid) group by status"),
                                  {"c": cid})).all())
    emails = (await conn.execute(text("select count(*) from app.email_events where campaign_id = cast(:c as uuid) and kind = 'sent'"),
                                 {"c": cid})).scalar_one()
    booked = (await conn.execute(text("""select count(*) from app.prospects p join app.leads l on l.id = p.lead_id
        where p.campaign_id = cast(:c as uuid) and l.stage in ('booked','showed','won')"""), {"c": cid})).scalar_one()
    boxes = (await conn.execute(text("select address, status, paused_reason from app.sending_mailboxes order by created_at"))).mappings().all()
    return {"people_emailed": ev.get("sent", 0), "emails_sent": emails, "replied": ev.get("reply", 0), "interested": replies_by.get("interested", 0),
            "bounced": ev.get("bounce", 0), "unsubscribed": ev.get("unsubscribe", 0), "booked": booked, "replies": replies_by,
            "in_sequence": st.get("active", 0), "approved_not_started": st.get("waiting", 0),
            "mailboxes": [dict(b) for b in boxes]}


PROSPECT_SQL = """select p.id, p.name, p.role, p.email, p.email_source, p.verify_status, p.snippets, p.first_line, p.line_snippet,
    p.fact_check, p.review, p.edited, p.reviewed_at, p.status, p.next_step, p.next_send_at, p.stop_reason, p.reply_kind,
    p.conversation_id, co.name as company, co.website, co.city, co.rating, co.reviews,
    u.name as reviewed_by_name
    from app.prospects p join app.prospect_companies co on co.id = p.company_id left join auth."user" u on u.id = p.reviewed_by
    where p.campaign_id = cast(:c as uuid)"""


@router.get("/campaigns/{cid}/prospects")
async def list_prospects(cid: str, ctx: Viewer, review: Literal["to_review", "pending", "needs_attention", "approved", "dropped", "all"] = "to_review") -> dict:
    where = {"to_review": " and p.review in ('pending','needs_attention')", "all": ""}.get(review, f" and p.review = '{review}'")
    async with tenant_session(ctx.org_id) as conn:
        await _campaign(conn, cid)
        rows = (await conn.execute(text(PROSPECT_SQL + where + " order by p.review = 'needs_attention' desc, co.name"), {"c": cid})).mappings().all()
    return {"items": [dict(r) for r in rows]}


class Review(BaseModel):
    action: Literal["approve", "drop", "reopen"]
    first_line: Annotated[str | None, Field(min_length=10, max_length=300)] = None


@router.post("/prospects/{pid}")
async def review_prospect(pid: str, body: Review, request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        p = (await conn.execute(text("select id, review, first_line, fact_check from app.prospects where id = cast(:p as uuid) for update"),
                                {"p": pid})).mappings().first()
        if not p:
            raise HTTPException(404, "prospect not found")
        line = (body.first_line or "").strip() or None
        edited = bool(line and line != (p["first_line"] or "").strip())
        if body.action == "approve" and p["review"] == "needs_attention" and not edited:
            raise HTTPException(409, "This line failed the fact check: edit it before approving, or drop it.")
        status = {"approve": "approved", "drop": "dropped", "reopen": "pending"}[body.action]
        if body.action == "reopen" and not (p["fact_check"] or {}).get("ok") and not p["edited"]:
            status = "needs_attention"
        await conn.execute(text("""update app.prospects set review = :s, first_line = coalesce(:l, first_line), edited = edited or :ed,
            fact_check = case when :ed then fact_check || '{"ok": true, "reason": "written by a person"}'::jsonb else fact_check end,
            reviewed_by = :u, reviewed_at = now(), updated_at = now() where id = cast(:p as uuid)"""),
            {"s": status, "l": line if edited else None, "ed": edited, "u": ctx.principal.user_id, "p": pid})
        if status == "dropped":
            await sending.stop_prospect(conn, pid, "dropped in review")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"cold_email.prospect_{status}", target_type="prospect", target_id=pid, ip=client_ip(request),
                           metadata={"edited": edited})
    return {"id": pid, "review": status, "edited": edited}


@router.post("/campaigns/{cid}/approve-ready")
async def approve_ready(cid: str, request: Request, ctx: Editor) -> dict:
    """Approve every line that passed the fact check and is still waiting. Lines that need attention stay for a person."""
    async with tenant_session(ctx.org_id) as conn:
        await _campaign(conn, cid)
        n = (await conn.execute(text("""update app.prospects set review = 'approved', reviewed_by = :u, reviewed_at = now(), updated_at = now()
            where campaign_id = cast(:c as uuid) and review = 'pending'"""), {"u": ctx.principal.user_id, "c": cid})).rowcount
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="cold_email.bulk_approved", target_type="campaign", target_id=cid, ip=client_ip(request),
                           metadata={"approved": n})
    return {"approved": n}


@router.get("/campaigns/{cid}/export.csv")
async def export(cid: str, ctx: Editor, review: Literal["approved", "all"] = "all") -> Response:
    """The review sheet, for Google Sheets or Excel (prospects' business emails: owners and managers only)."""
    async with tenant_session(ctx.org_id) as conn:
        c = await _campaign(conn, cid)
        rows = (await conn.execute(text(PROSPECT_SQL + (" and p.review = 'approved'" if review == "approved" else "") + " order by co.name"),
                                   {"c": cid})).mappings().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Company", "Website", "City", "Rating", "Person", "Role", "Email", "Email check", "Found via", "First line",
                "Based on (from their website)", "Source page", "Review"])
    for r in rows:
        snip = next((s for s in r["snippets"] if s["n"] == r["line_snippet"]), {})
        w.writerow([r["company"], r["website"], r["city"], r["rating"], r["name"], r["role"], r["email"], r["verify_status"],
                    r["email_source"], r["first_line"], snip.get("text", ""), snip.get("url", ""), r["review"]])
    slug = "".join(ch if ch.isalnum() else "-" for ch in c["name"].lower()).strip("-")[:40] or "campaign"
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{slug}-prospects.csv"'})


# ---------- sending (5.4) and replies (5.5) ----------

@router.post("/campaigns/{cid}/start")
async def start(cid: str, request: Request, ctx: Editor) -> dict:
    """Start sending (or add newly approved people to a running campaign)."""
    async with tenant_session(ctx.org_id) as conn:
        try:
            r = await sending.start_campaign(conn, cid)
        except sending.CannotStart as e:
            raise HTTPException(409, str(e)) from e
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="cold_email.campaign_started", target_type="campaign", target_id=cid, ip=client_ip(request), metadata=r)
    return r


@router.post("/campaigns/{cid}/{action}")
async def pause_resume(cid: str, action: Literal["pause", "resume"], request: Request, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _campaign(conn, cid)
        await sending.set_paused(conn, cid, action == "pause")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"cold_email.campaign_{action}d", target_type="campaign", target_id=cid, ip=client_ip(request))
        return {"status": (await _campaign(conn, cid))["status"]}


class FakeReply(BaseModel):
    text: Annotated[str, Field(min_length=2, max_length=4000)]
    complaint: bool = False


@router.post("/prospects/{pid}/simulate-reply")
async def simulate_reply(pid: str, body: FakeReply, ctx: Editor) -> dict:
    """Mock mode only, Agentry staff only: pretend this person replied (or marked us as spam) to see what happens."""
    if settings.cold_email_providers != "mock" or not ctx.principal.is_staff:
        raise HTTPException(404, "not available")
    async with tenant_session(ctx.org_id) as conn:
        email = (await conn.execute(text("select email from app.prospects where id = cast(:p as uuid)"), {"p": pid})).scalar_one_or_none()
    if not email:
        raise HTTPException(404, "prospect not found")
    r = await (replies.complaint(ctx.org_id, email) if body.complaint else replies.ingest_reply(ctx.org_id, email, body.text))
    if not r["matched"]:
        raise HTTPException(409, "nothing has been sent to this person yet")
    return r
