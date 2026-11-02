"""SOP & proposal drafter in the portal (ROADMAP-V3 B4). Owners and managers draft; everyone who signs in reads."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import doc_drafter as dd
from agentry.db import tenant_session
from agentry.features import require_page

router = APIRouter(prefix="/org/docs", dependencies=[Depends(require_page("docs"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]


@router.get("")
async def docs(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("select id::text, kind, title, status, created_at from app.doc_drafts order by created_at desc limit 100"))).mappings().all()
    return {"items": [dict(r) for r in rows], "can_edit": ctx.can("automation", "configure")}


class DraftIn(BaseModel):
    kind: Literal["sop", "proposal", "checklist"]
    brief: Annotated[str, Field(min_length=15, max_length=3000)]


@router.post("", status_code=201)
async def create(body: DraftIn, ctx: Editor) -> dict:
    try:
        return await dd.draft(ctx.org_id, body.kind, body.brief, ctx.principal.user_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


async def _doc(conn, did: str) -> dict:
    d = (await conn.execute(text("select * from app.doc_drafts where id = cast(:i as uuid)"), {"i": did})).mappings().first()
    if not d:
        raise HTTPException(404, "document not found")
    return dict(d)


@router.get("/{did}")
async def get(did: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        d = await _doc(conn, did)
    return {k: v for k, v in d.items() if k != "org_id"} | {"id": did}


class Edit(BaseModel):
    title: Annotated[str | None, Field(max_length=160)] = None
    content: Annotated[str | None, Field(max_length=40000)] = None
    diagram: Annotated[str | None, Field(max_length=8000)] = None
    status: Literal["draft", "final"] | None = None


@router.patch("/{did}")
async def edit(did: str, body: Edit, ctx: Editor) -> dict:
    new = body.model_dump(exclude_unset=True)
    async with tenant_session(ctx.org_id) as conn:
        await _doc(conn, did)
        if new:
            await conn.execute(text(f"update app.doc_drafts set {', '.join(f'{k} = :{k}' for k in new)}, updated_at = now() where id = cast(:id as uuid)"),
                               new | {"id": did})
    return {"id": did}


@router.get("/{did}/export")
async def export(did: str, ctx: Reader) -> Response:
    async with tenant_session(ctx.org_id) as conn:
        d = await _doc(conn, did)
    md = f"# {d['title']}\n\n{d['content']}" + (f"\n\n```mermaid\n{d['diagram']}\n```\n" if d["diagram"] else "")
    name = "".join(c if c.isalnum() else "-" for c in d["title"].lower())[:60].strip("-") or "document"
    return Response(md, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
