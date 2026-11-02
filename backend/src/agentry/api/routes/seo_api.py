"""Local SEO in the portal (ROADMAP-V3 B1). Owners and managers run it (automation:configure); others read."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import local_seo as seo
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/seo", dependencies=[Depends(require_page("seo"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]


@router.get("")
async def overview(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        audits = (await conn.execute(text("select id::text, url, score, result, created_at from app.seo_audits order by created_at desc limit 6"))).mappings().all()
        arts = (await conn.execute(text("""select id::text, topic, title, status, created_at, checks from app.seo_articles order by created_at desc limit 50"""))).mappings().all()
        _s, cfg = await seo.settings_of(conn)
    latest = dict(audits[0]) if audits else None
    return {"latest": latest, "history": [{"score": a["score"], "at": a["created_at"]} for a in audits], "articles": [dict(a) for a in arts],
            "config": cfg, "can_edit": ctx.can("automation", "configure")}


class AuditIn(BaseModel):
    url: Annotated[str | None, Field(max_length=300)] = None


@router.post("/audit", status_code=201)
async def audit(body: AuditIn, ctx: Editor) -> dict:
    try:
        return await seo.run_audit(ctx.org_id, body.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ArticleIn(BaseModel):
    topic: Annotated[str, Field(min_length=3, max_length=160)]


@router.post("/articles", status_code=201)
async def article(body: ArticleIn, ctx: Editor) -> dict:
    try:
        return await seo.write_article(ctx.org_id, body.topic)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


async def _article(conn, aid: str) -> dict:
    a = (await conn.execute(text("select * from app.seo_articles where id = cast(:i as uuid)"), {"i": aid})).mappings().first()
    if not a:
        raise HTTPException(404, "article not found")
    return dict(a)


@router.get("/articles/{aid}")
async def get_article(aid: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        a = await _article(conn, aid)
    return {k: v for k, v in a.items() if k != "org_id"} | {"id": aid}


class ArticleEdit(BaseModel):
    title: Annotated[str | None, Field(max_length=120)] = None
    meta: Annotated[str | None, Field(max_length=200)] = None
    body: Annotated[str | None, Field(max_length=20000)] = None
    status: Literal["draft", "approved", "published"] | None = None


@router.patch("/articles/{aid}")
async def edit_article(aid: str, body: ArticleEdit, ctx: Editor) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        a = await _article(conn, aid)
        new = body.model_dump(exclude_unset=True)
        if new.get("status") in ("approved", "published"):
            probs = seo.article_problems({**a, **new, "faqs": a["faqs"]}, a["body"] if "body" not in new else "")
            probs = [p for p in probs if "isn't in the business's facts" not in p]  # a person edited it: numbers are theirs
            if probs:
                raise HTTPException(409, "fix first: " + "; ".join(probs))
        if new:
            sets = ", ".join(f"{k} = :{k}" for k in new)
            await conn.execute(text(f"update app.seo_articles set {sets}, updated_at = now() where id = cast(:id as uuid)"), new | {"id": aid})
    return {"id": aid}


@router.get("/articles/{aid}/export")
async def export(aid: str, ctx: Reader, format: Literal["html", "md"] = "html") -> Response:
    async with tenant_session(ctx.org_id) as conn:
        a = await _article(conn, aid)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": ctx.org_id})).scalar_one_or_none() or ""
    if format == "md":
        md = f"# {a['title']}\n\n{a['body']}\n\n## Frequently asked questions\n\n" + "\n\n".join(f"### {f['q']}\n\n{f['a']}" for f in a["faqs"])
        return Response(md, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{a["slug"]}.md"'})
    return Response(seo.article_html(a, business), media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{a["slug"]}.html"'})
