"""Onboarding wizard endpoints: business profile, knowledge, persona, setup steps, agent test chat, go live."""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.agents.runtime import run_turn
from agentry.auth import OrgContext, client_ip, require
from agentry.db import tenant_session
from agentry.events import emit
from agentry.features import go_live_checks, org_features, require_page
from agentry.knowledge import (
    MAX_FILE_BYTES,
    KnowledgeTooLarge,
    UnreadableFile,
    UnsafeUrl,
    add_document,
    add_faqs,
    crawl,
    extract_text,
)

router = APIRouter(prefix="/org", tags=["setup"])

STEPS = ["profile", "plan", "team", "connect", "import", "knowledge", "settings", "persona", "compliance", "test", "go_live"]


class Profile(BaseModel):
    website: Annotated[str | None, Field(max_length=300)] = None
    phone: Annotated[str | None, Field(max_length=40)] = None
    address: Annotated[str | None, Field(max_length=300)] = None
    city: Annotated[str | None, Field(max_length=80)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    currency: Literal["INR", "USD", "EUR", "GBP", "AED"] | None = None
    customer_value: Annotated[float | None, Field(ge=0, le=10_000_000)] = None
    holidays: list[str] | None = None


@router.get("/profile")
async def get_profile(ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        s = (await conn.execute(text("""select s.website, s.timezone, s.currency, s.profile, s.persona, s.qualification,
            s.industry_pack, s.status, s.widget_key, o.name from app.org_settings s join auth.organization o on o.id = s.org_id"""))).mappings().one()
        steps = dict((await conn.execute(text("select step_key, status from app.onboarding_progress"))).all())
        features = await org_features(conn)
        checks = await go_live_checks(conn, features["go_live"])
    p = s["profile"] or {}
    return {"name": s["name"], "website": s["website"], "timezone": s["timezone"], "currency": s["currency"],
            "phone": p.get("phone"), "address": p.get("address"), "city": p.get("city"),
            "customer_value": p.get("customer_value"), "holidays": p.get("holidays", []), "persona": s["persona"],
            "qualification": s["qualification"], "industry_pack": s["industry_pack"], "status": s["status"],
            "widget_key": s["widget_key"], "steps": [{"key": k, "status": steps.get(k, "todo")} for k in features["steps"]],
            "automations": features["automations"], "connections": features["connections"], "go_live_checks": checks}


@router.patch("/profile")
async def update_profile(body: Profile, request: Request, ctx: Annotated[OrgContext, Depends(require("organization", "update"))]) -> dict:
    changes = body.model_dump(exclude_none=True)
    profile_keys = {k: changes.pop(k) for k in ("phone", "address", "city", "customer_value", "holidays") if k in changes}
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""update app.org_settings set website = coalesce(:w, website), timezone = coalesce(:tz, timezone),
            currency = coalesce(:cur, currency), profile = profile || cast(:p as jsonb)"""),
            {"w": changes.get("website"), "tz": changes.get("timezone"), "cur": changes.get("currency"), "p": json.dumps(profile_keys)})
        await _mark(conn, ctx.org_id, "profile", "done", ctx)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="profile.updated", metadata={"fields": sorted([*changes, *profile_keys])}, ip=client_ip(request))
    return {"ok": True}


class Persona(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    tone: Annotated[str, Field(min_length=2, max_length=200)]
    greeting: Annotated[str, Field(min_length=5, max_length=400)]
    signoff: Annotated[str | None, Field(max_length=80)] = None


@router.put("/persona")
async def set_persona(body: Persona, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.org_settings set persona = persona || cast(:p as jsonb)"),
                           {"p": json.dumps(body.model_dump(exclude_none=True))})
        await _mark(conn, ctx.org_id, "persona", "done", ctx)
    return {"ok": True}


# ---------- knowledge ----------

@router.get("/knowledge", dependencies=[Depends(require_page("knowledge"))])
async def list_knowledge(ctx: Annotated[OrgContext, Depends(require("conversation", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select d.id, d.source_type, d.source_ref, d.title, left(d.content, 300) as preview,
            d.updated_at, (select count(*) from app.kb_chunks c where c.document_id = d.id) as chunks
            from app.kb_documents d order by d.source_type, d.title"""))).mappings().all()
    return {"items": [dict(r) for r in rows]}


class Faq(BaseModel):
    q: Annotated[str, Field(min_length=3, max_length=300)]
    a: Annotated[str, Field(min_length=1, max_length=3000)]


@router.post("/knowledge/faqs", status_code=201, dependencies=[Depends(require_page("knowledge"))])
async def add_faq(body: Faq, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    await add_faqs(ctx.org_id, [body.model_dump()])
    async with tenant_session(ctx.org_id) as conn:
        await _mark(conn, ctx.org_id, "knowledge", "done", ctx)
    return {"ok": True}


class KnowledgeText(BaseModel):
    title: Annotated[str, Field(min_length=2, max_length=200)]
    content: Annotated[str, Field(min_length=20, max_length=200_000)]


@router.post("/knowledge/text", status_code=201, dependencies=[Depends(require_page("knowledge"))])
async def add_text(body: KnowledgeText, request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Paste anything your agents should know: a price list, policies, product notes. Same title = replaced."""
    try:
        doc_id = await add_document(ctx.org_id, source_type="text", title=body.title.strip(), content=body.content.strip(),
                                    source_ref=f"text:{body.title.strip()[:150]}")
    except KnowledgeTooLarge as e:
        raise HTTPException(413, str(e)) from e
    async with tenant_session(ctx.org_id) as conn:
        await _mark(conn, ctx.org_id, "knowledge", "done", ctx)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="knowledge.text_added", metadata={"title": body.title[:200]}, ip=client_ip(request))
    return {"id": doc_id}


@router.post("/knowledge/file", status_code=201, dependencies=[Depends(require_page("knowledge"))])
async def add_file(request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))],
                   file: Annotated[UploadFile, File()]) -> dict:
    """Upload a PDF, Word, text, Markdown or CSV file. Uploading a file with the same name replaces it."""
    data = await file.read(MAX_FILE_BYTES + 1)
    name = (file.filename or "document").rsplit("/", 1)[-1][:200]
    try:
        content = extract_text(name, data)
        doc_id = await add_document(ctx.org_id, source_type="file", title=name, content=content, source_ref=f"file:{name}")
    except UnreadableFile as e:
        raise HTTPException(422, str(e)) from e
    except KnowledgeTooLarge as e:
        raise HTTPException(413, str(e)) from e
    async with tenant_session(ctx.org_id) as conn:
        await _mark(conn, ctx.org_id, "knowledge", "done", ctx)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="knowledge.file_added", metadata={"file": name, "characters": len(content)}, ip=client_ip(request))
    return {"id": doc_id, "characters": len(content)}


class KnowledgeUrl(BaseModel):
    url: Annotated[str, Field(min_length=4, max_length=500)]
    max_pages: Annotated[int, Field(ge=1, le=20)] = 8


@router.post("/knowledge/website", status_code=201, dependencies=[Depends(require_page("knowledge"))])
async def learn_website(body: KnowledgeUrl, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    try:
        pages = await crawl(body.url, max_pages=body.max_pages)
    except UnsafeUrl as e:
        raise HTTPException(422, str(e)) from e
    learned = 0
    for p in pages:
        if len(p.text) > 80:
            await add_document(ctx.org_id, source_type="url", title=p.title or p.url, content=p.text, source_ref=p.url)
            learned += 1
    async with tenant_session(ctx.org_id) as conn:
        await _mark(conn, ctx.org_id, "knowledge", "done", ctx)
    return {"pages_learned": learned}


@router.delete("/knowledge/{doc_id}", dependencies=[Depends(require_page("knowledge"))])
async def delete_knowledge(doc_id: str, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("delete from app.kb_documents where id = :d"), {"d": doc_id})).rowcount
    if not n:
        raise HTTPException(404, "not found")
    return {"ok": True}


# ---------- setup steps, test chat, go live ----------

async def _mark(conn, org_id: str, step: str, status: str, ctx: OrgContext) -> None:
    await conn.execute(text("""insert into app.onboarding_progress (org_id, step_key, status, done_by, updated_at)
        values (:o, :k, :s, :by, now()) on conflict (org_id, step_key) do update set status = excluded.status,
        done_by = excluded.done_by, blocker = case when excluded.status = 'done' then null else app.onboarding_progress.blocker end,
        updated_at = now()"""), {"o": org_id, "k": step, "s": status, "by": "agentry" if ctx.role is None else "client"})


class StepUpdate(BaseModel):
    status: Literal["todo", "in_progress", "done", "skipped"]


@router.put("/onboarding/{step}")
async def update_step(step: str, body: StepUpdate, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    if step not in STEPS or step == "go_live":
        raise HTTPException(404, "unknown step")
    async with tenant_session(ctx.org_id) as conn:
        await _mark(conn, ctx.org_id, step, body.status, ctx)
    return {"step": step, "status": body.status}


class TestMessage(BaseModel):
    conversation_id: str | None = None
    text: Annotated[str, Field(min_length=1, max_length=2000)]


@router.post("/agent/test")
async def test_agent(body: TestMessage, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Talk to your agent before going live. Test chats are marked so they never count in results."""
    async with tenant_session(ctx.org_id) as conn:
        cid = body.conversation_id
        if cid is None or not (await conn.execute(text("select 1 from app.conversations where id = :c and metadata->>'test' = 'true'"),
                                                  {"c": cid})).first():
            cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, metadata)
                values (:o, 'web_chat', 'website_chat', 'Test chat', '{"test": true}') returning id"""), {"o": ctx.org_id})).scalar_one())
        await _mark(conn, ctx.org_id, "test", "done", ctx)
    r = await run_turn(ctx.org_id, cid, body.text, source="test")
    return {"conversation_id": cid, **r}


@router.post("/go-live")
async def go_live(request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        features = await org_features(conn)
        if not features["automations"]:
            raise HTTPException(409, "no automations are switched on for this client")
        missing = [c["label"] for c in await go_live_checks(conn, features["go_live"]) if not c["done"]]
        if missing:
            raise HTTPException(409, f"finish these first: {', '.join(missing)}")
        switched = (await conn.execute(text("""update app.automation_instances set status = 'approval_mode', updated_at = now()
            where status = 'setup' returning template_key"""))).scalars().all()
        await conn.execute(text("update app.org_settings set status = 'live' where status in ('pending_setup', 'onboarding')"))
        await _mark(conn, ctx.org_id, "go_live", "done", ctx)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="org.went_live", metadata={"automations": switched}, ip=client_ip(request))
        await emit(conn, ctx.org_id, "org.went_live", {"automations": switched})
    return {"live": True, "approval_mode": switched}
