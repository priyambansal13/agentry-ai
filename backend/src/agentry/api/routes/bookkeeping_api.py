"""Bookkeeping in the portal (9.5): receipts and bills, checking them, budgets, export to Tally / CSV.

Money permission: owners, managers and finance read and act (invoice:act); viewers read (invoice:read); front desk none.
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import text

from agentry import audit, documents
from agentry.auth import OrgContext, client_ip, current_org
from agentry.automations import bookkeeping as bk
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter(prefix="/org/bookkeeping")


async def _ctx(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
    if not ctx.can("invoice", "read"):
        raise HTTPException(403, "bookkeeping is for owners, managers and finance")
    async with tenant_session(ctx.org_id) as conn:
        if "bookkeeping" not in await enabled_automations(conn):
            raise HTTPException(404, "the bookkeeping assistant isn't switched on")
    return ctx


Reader = Annotated[OrgContext, Depends(_ctx)]


def _act(ctx: OrgContext) -> None:
    if not ctx.can("invoice", "act"):
        raise HTTPException(403, "viewers can't change the books")


@router.get("/documents")
async def list_documents(ctx: Reader, status: str | None = None, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
                         limit: Annotated[int, Query(ge=1, le=500)] = 200) -> dict:
    month = month or datetime.now(UTC).date().isoformat()[:7]
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, kind, source, filename, status, fields, confidence, checks, error, created_at, reviewed_at,
                exported_at, duplicate_of::text from app.documents where (cast(:s as text) is null or status = :s)
                and (status in ('needs_review','processing','failed') or left(fields->'date'->>'value', 7) = :m or left(created_at::text, 7) = :m)
            order by created_at desc limit :l"""), {"s": status, "m": month, "l": limit})).mappings().all()
        counts = dict((await conn.execute(text("select status, count(*) from app.documents group by status"))).all())
        _st, cfg = await bk.settings_of(conn)
        spent = await bk.spend(conn, month)
        to_export = (await conn.execute(text("select count(*) from app.documents where status = 'ready' and exported_at is null"))).scalar_one()
    budgets = cfg.get("budgets") or {}
    cats = sorted(set(spent) | set(budgets), key=lambda c: -spent.get(c, 0))
    return {"month": month, "items": [dict(r) for r in rows], "counts": counts, "to_export": to_export, "can_act": ctx.can("invoice", "act"),
            "by_category": [{"category": c, "spent": round(spent.get(c, 0), 2), "budget": budgets.get(c)} for c in cats],
            "total": round(sum(spent.values()), 2), "categories": cfg["categories"], "review_below": cfg["review_below"]}


@router.post("/documents", status_code=201)
async def upload(request: Request, ctx: Reader, file: Annotated[UploadFile, File()]) -> dict:
    _act(ctx)
    mime = documents.mime_of(file.filename, file.content_type)
    if not mime:
        raise HTTPException(422, "upload a photo (JPG, PNG, WEBP) or a PDF")
    data = await file.read(documents.MAX_BYTES + 1)
    try:
        doc = await bk.ingest(ctx.org_id, data, mime=mime, filename=file.filename, source="upload", user_id=ctx.principal.user_id)
    except documents.DocumentError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": doc["id"], "status": doc["status"], "error": doc.get("error")}


@router.post("/samples", status_code=201)
async def samples(ctx: Reader) -> dict:
    """Try it: three sample receipts (a clean grocery bill, a supplier's GST invoice, a smudged café receipt)."""
    _act(ctx)
    out = []
    for p in documents.sample_files():
        doc = await bk.ingest(ctx.org_id, p.read_bytes(), mime=documents.mime_of(p.name, None), filename=p.name, source="sample",
                              user_id=ctx.principal.user_id)
        out.append({"id": doc["id"], "status": doc["status"], "file": p.name})
    return {"items": out}


@router.get("/documents/{did}")
async def get_document(did: str, ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        row = (await conn.execute(text("""select d.*, d.id::text as id, d.duplicate_of::text as duplicate_of, k.name as sender
            from app.documents d left join app.contacts k on k.id = d.contact_id where d.id = cast(:i as uuid)"""), {"i": did})).mappings().first()
        if not row:
            raise HTTPException(404, "document not found")
        _st, cfg = await bk.settings_of(conn)
    d = {k: v for k, v in dict(row).items() if k not in ("file_path", "sha256", "org_id", "contact_id")}
    return {**d, "categories": cfg["categories"], "review_below": cfg["review_below"], "can_act": ctx.can("invoice", "act"),
            "field_order": [{"name": n, "type": t, "required": r} for n, (t, r) in documents.RECEIPT_FIELDS.items()]}


@router.get("/documents/{did}/file")
async def get_file(did: str, ctx: Reader) -> FileResponse:
    async with tenant_session(ctx.org_id) as conn:
        row = (await conn.execute(text("select file_path, mime, filename from app.documents where id = cast(:i as uuid)"), {"i": did})).mappings().first()
    if not row or not documents.path_of(dict(row)).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(documents.path_of(dict(row)), media_type=row["mime"], headers={"Cache-Control": "private, max-age=60"})


class Review(BaseModel):
    action: Literal["accept", "reject"]
    fields: dict[str, object] | None = None


@router.put("/documents/{did}")
async def review(did: str, b: Review, request: Request, ctx: Reader) -> dict:
    _act(ctx)
    try:
        out = await bk.review(ctx.org_id, did, action=b.action, edits=b.fields, user_id=ctx.principal.user_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action=f"document.{b.action}ed",
                           target_type="document", target_id=did, ip=client_ip(request), metadata={"edited": sorted((b.fields or {}).keys())})
    return out


@router.get("/export")
async def export(ctx: Reader, request: Request, format: Literal["tally", "csv"] = "csv",
                 month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None, include_exported: bool = False) -> Response:
    """Ready documents only (checked or confident). Marks them exported so the next export has only new ones."""
    _act(ctx)
    async with tenant_session(ctx.org_id) as conn:
        docs = await bk.exportable(conn, month, include_exported)
        company = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": ctx.org_id})).scalar_one_or_none() or "Company"
        if docs:
            await conn.execute(text("update app.documents set exported_at = now() where id = any(cast(:ids as uuid[]))"), {"ids": [d["id"] for d in docs]})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="bookkeeping.exported",
                           target_type="documents", ip=client_ip(request), metadata={"format": format, "count": len(docs), "month": month})
    name = f"agentry-expenses{'-' + month if month else ''}"
    if format == "tally":
        return Response(bk.to_tally(docs, company), media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{name}-tally.xml"', "X-Count": str(len(docs))})
    return Response(bk.to_csv(docs), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"', "X-Count": str(len(docs))})
