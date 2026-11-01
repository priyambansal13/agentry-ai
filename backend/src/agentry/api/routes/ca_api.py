"""CA Firm pack in the portal (docs/PACKS.md): clients, the filing board, documents, tax documents and the calendar.

Who: owners, managers, front desk and finance work on it; viewers read. Each part needs its agent switched on
(clients and files: any CA agent).
"""
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, current_org
from agentry.automations.ca import calendar, chaser, core, taxdocs, tracker
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter(prefix="/org/ca")


async def _on(ctx: OrgContext, keys: tuple[str, ...]) -> list[str]:
    if not core.can_read(ctx):
        raise HTTPException(403, "the CA desk is for owners, managers, front desk and finance")
    async with tenant_session(ctx.org_id) as conn:
        on = [k for k in await enabled_automations(conn) if k in core.CA_KEYS]
    if not set(on) & set(keys):
        raise HTTPException(404, "this part of the CA desk isn't switched on")
    return on


def needs(*keys: str):
    async def check(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
        await _on(ctx, keys or core.CA_KEYS)
        return ctx
    return check


Any = Annotated[OrgContext, Depends(needs())]
Board = Annotated[OrgContext, Depends(needs("ca_filing_tracker"))]
Chaser = Annotated[OrgContext, Depends(needs("ca_document_chaser"))]
Reader = Annotated[OrgContext, Depends(needs("ca_tax_docs_reader"))]
Cal = Annotated[OrgContext, Depends(needs("ca_compliance_calendar"))]


def _work(ctx: OrgContext) -> None:
    if not core.can_work(ctx):
        raise HTTPException(403, "viewers can look but not change anything")


def _err(e: core.CaError) -> HTTPException:
    return HTTPException(422, str(e))


@router.get("/meta")
async def meta(ctx: Any) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        on = [k for k in await enabled_automations(conn) if k in core.CA_KEYS]
        team = (await conn.execute(text("""select u.id, u.name, u.email, m.role from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o order by u.name"""), {"o": ctx.org_id})).mappings().all()
    return {"enabled": on, "statuses": [{"key": s, "label": core.STATUS_LABEL[s]} for s in core.STATUSES],
            "kinds": core.KINDS, "client_kinds": core.CLIENT_KINDS, "profile_flags": core.PROFILE_FLAGS,
            "items": {k: v[0] for k, v in chaser.ITEMS.items()}, "team": [dict(t) for t in team], "me": ctx.principal.user_id,
            "can_work": core.can_work(ctx)}


# ---------- clients ----------

class ClientIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=160)]
    kind: Literal["individual", "huf", "firm", "llp", "company", "trust"] = "individual"
    pan: Annotated[str | None, Field(max_length=10)] = None
    gstin: Annotated[str | None, Field(max_length=15)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    email: Annotated[str | None, Field(max_length=200)] = None
    profile: dict[str, bool] = Field(default_factory=dict)
    assignee: str | None = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    whatsapp_ok: bool = True


@router.get("/clients")
async def clients(ctx: Any, q: str | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select c.id::text, c.name, c.kind, c.pan, c.gstin, c.phone, c.email, c.profile, c.assignee,
            (select count(*) from app.ca_filings f where f.client_id = c.id and f.status not in ('filed','verified')) as open_filings,
            (select count(*) from app.ca_files x where x.client_id = c.id) as files
            from app.ca_clients c where (cast(:q as text) is null or c.name ilike :p or c.pan ilike :p or c.phone ilike :p) order by c.name limit 2000"""),
            {"q": q, "p": f"%{q}%"})).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/clients", status_code=201)
async def add_client(body: ClientIn, ctx: Any) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            cid = await core.save_client(conn, ctx.org_id, body.model_dump())
        except core.CaError as e:
            raise _err(e) from e
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="ca.client_added",
                           target_type="ca_client", target_id=cid)
    return {"id": cid}


@router.post("/clients/import")
async def import_clients(ctx: Any, file: Annotated[UploadFile, File()]) -> dict:
    _work(ctx)
    data = await file.read()
    mime = core.mime_of(file.filename, file.content_type)
    rows_text = data.decode("utf-8-sig", errors="ignore") if mime != core.mime_of("x.xlsx", None) else \
        "\n".join(",".join(f'"{c}"' for c in r) for r in core.xlsx_rows(data))
    async with tenant_session(ctx.org_id) as conn:
        try:
            r = await core.import_clients(conn, ctx.org_id, rows_text)
        except core.CaError as e:
            raise _err(e) from e
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="ca.clients_imported",
                           metadata={k: v for k, v in r.items() if k != "errors"})
    return r


@router.get("/clients/{cid}")
async def client(cid: str, ctx: Any) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select * from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
        if not c:
            raise HTTPException(404, "client not found")
        filings = await tracker.board(conn, client_id=cid)
        checklists = {r["id"]: {"checklist": r["checklist"], "chase": r["chase"]} for r in (await conn.execute(text(
            "select id::text, checklist, chase from app.ca_filings where client_id = cast(:i as uuid)"), {"i": cid})).mappings().all()}
        files = (await conn.execute(text("""select id::text, filing_id::text, item_key, doc_type, filename, mime, bytes, source, created_at,
            extracted is not null as read from app.ca_files where client_id = cast(:i as uuid) order by created_at desc"""), {"i": cid})).mappings().all()
    return {"client": {k: v for k, v in dict(c).items() if k not in ("org_id",)} | {"id": cid},
            "filings": [f | checklists.get(f["id"], {}) for f in filings], "files": [dict(f) for f in files]}


@router.patch("/clients/{cid}")
async def edit_client(cid: str, body: ClientIn, ctx: Any) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            await core.save_client(conn, ctx.org_id, body.model_dump(), cid)
        except core.CaError as e:
            raise _err(e) from e
    return {"id": cid}


@router.delete("/clients/{cid}")
async def delete_client(cid: str, ctx: Any) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        paths = [core.path_of(r) for r in (await conn.execute(text("select path from app.ca_files where client_id = cast(:i as uuid)"), {"i": cid})).mappings().all()]
        gone = (await conn.execute(text("delete from app.ca_clients where id = cast(:i as uuid) returning name"), {"i": cid})).scalar_one_or_none()
        if not gone:
            raise HTTPException(404, "client not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="ca.client_deleted",
                           target_type="ca_client", target_id=cid, metadata={"name": gone, "files": len(paths)})
    for p in paths:
        p.unlink(missing_ok=True)
    return {"deleted": True}


# ---------- files ----------

@router.post("/clients/{cid}/files", status_code=201)
async def upload(cid: str, ctx: Any, file: Annotated[UploadFile, File()], filing_id: Annotated[str | None, Form()] = None,
                 doc_type: Annotated[str | None, Form()] = None) -> dict:
    _work(ctx)
    data = await file.read()
    async with tenant_session(ctx.org_id) as conn:
        on = [k for k in await enabled_automations(conn) if k in core.CA_KEYS]
        if not (await conn.execute(text("select 1 from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).first():
            raise HTTPException(404, "client not found")
    try:
        if "ca_document_chaser" in on:  # matched to the checklist it answers
            r = await chaser.receive(ctx.org_id, cid, data, mime=file.content_type, filename=file.filename, source="portal",
                                     filing_id=filing_id, user_id=ctx.principal.user_id)
            fid = r["file_id"]
        else:
            async with tenant_session(ctx.org_id) as conn:
                fid = await core.store_file(conn, ctx.org_id, cid, data, filename=file.filename, mime=file.content_type, filing_id=filing_id,
                                            doc_type=doc_type, user_id=ctx.principal.user_id)
            r = {"file_id": fid}
        if "ca_tax_docs_reader" in on and (doc_type in taxdocs.TAX_DOCS or r.get("doc_type") in taxdocs.TAX_DOCS):
            r["extracted"] = await taxdocs.read_file(ctx.org_id, fid)
    except core.CaError as e:
        raise _err(e) from e
    return r


async def _file(conn, fid: str):
    f = (await conn.execute(text("select * from app.ca_files where id = cast(:i as uuid)"), {"i": fid})).mappings().first()
    if not f:
        raise HTTPException(404, "file not found")
    return f


@router.get("/files/{fid}")
async def download(fid: str, ctx: Any) -> FileResponse:
    async with tenant_session(ctx.org_id) as conn:
        f = await _file(conn, fid)
    return FileResponse(core.path_of(f), media_type=f["mime"], filename=f["filename"])


@router.get("/files/{fid}/extracted")
async def extracted(fid: str, ctx: Any) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        f = await _file(conn, fid)
    return {"id": fid, "filename": f["filename"], "doc_type": f["doc_type"], "extracted": f["extracted"]}


@router.delete("/files/{fid}")
async def delete_file(fid: str, ctx: Any) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        f = await _file(conn, fid)
        await conn.execute(text("delete from app.ca_files where id = cast(:i as uuid)"), {"i": fid})
    core.path_of(f).unlink(missing_ok=True)
    return {"deleted": True}


# ---------- tax documents (reader) ----------

@router.post("/files/{fid}/read")
async def read(fid: str, ctx: Reader) -> dict:
    _work(ctx)
    try:
        return await taxdocs.read_file(ctx.org_id, fid)
    except core.CaError as e:
        raise _err(e) from e


@router.post("/clients/{cid}/samples")
async def samples(cid: str, ctx: Reader) -> dict:
    """Try the reader on a sample Form 16 and AIS (they disagree on TDS, and the AIS has income Form 16 doesn't)."""
    _work(ctx)
    ids = []
    for p in taxdocs.sample_files():
        async with tenant_session(ctx.org_id) as conn:
            ids.append(await core.store_file(conn, ctx.org_id, cid, p.read_bytes(), filename=p.name, mime="text/plain",
                                             doc_type="form16" if "form16" in p.name else "ais", user_id=ctx.principal.user_id))
        await taxdocs.read_file(ctx.org_id, ids[-1])
    return {"files": ids}


async def _tax(ctx: OrgContext, cid: str, ay: str | None) -> tuple[dict, list[dict], list[dict]]:
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select name, pan from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
        if not c:
            raise HTTPException(404, "client not found")
        cfg = await core.enabled(conn, "ca_tax_docs_reader") or {}
        docs = await taxdocs.client_docs(conn, cid, ay)
    return dict(c), docs, taxdocs.compare(docs, c["pan"], float(cfg.get("tds_tolerance", 10)))


@router.get("/clients/{cid}/tax")
async def tax(cid: str, ctx: Reader, ay: str | None = None) -> dict:
    _, docs, points = await _tax(ctx, cid, ay)
    years = sorted({(d["extracted"] or {}).get("assessment_year") for d in docs} - {None}, reverse=True)
    return {"documents": [{"file_id": d["file_id"], "filename": d["filename"], "doc_type": d["extracted"]["doc_type"],
                           "assessment_year": d["extracted"].get("assessment_year"), "items": d["extracted"]["items"]} for d in docs],
            "points": points, "summary": taxdocs.summary(docs) if docs else None, "years": years}


@router.get("/clients/{cid}/tax.xlsx")
async def tax_sheet(cid: str, ctx: Reader, ay: str | None = None) -> Response:
    c, docs, points = await _tax(ctx, cid, ay)
    name = "".join(ch for ch in c["name"] if ch.isalnum() or ch in " -")[:40].strip().replace(" ", "-")
    return Response(taxdocs.sheet(c, docs, points), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}-tax-{ay or "all"}.xlsx"'})


# ---------- filings (board) ----------

class FilingIn(BaseModel):
    client_id: str
    kind: str
    period: Annotated[str, Field(min_length=2, max_length=40)]
    due_on: date | None = None
    assignee: str | None = None
    notes: Annotated[str | None, Field(max_length=2000)] = None


class FilingEdit(BaseModel):
    status: Literal["docs_pending", "in_prep", "review", "filed", "verified"] | None = None
    assignee: str | None = None
    due_on: date | None = None
    ack_no: Annotated[str | None, Field(max_length=60)] = None
    filed_on: date | None = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    position: int | None = None


@router.get("/filings")
async def filings(ctx: Board, status: str | None = None, kind: str | None = None, period: str | None = None,
                  assignee: str | None = None, client_id: str | None = None, q: str | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        items = await tracker.board(conn, status=status, kind=kind, period=period,
                                    assignee=ctx.principal.user_id if assignee == "me" else assignee, client_id=client_id, q=q)
        periods = list((await conn.execute(text("select distinct period from app.ca_filings order by 1 desc limit 50"))).scalars())
    return {"items": items, "periods": periods}


@router.post("/filings", status_code=201)
async def add_filing(body: FilingIn, ctx: Board) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            fid = await tracker.create_filing(conn, ctx.org_id, body.client_id, kind=body.kind, period=body.period, due_on=body.due_on,
                                              assignee=body.assignee, notes=body.notes)
        except core.CaError as e:
            raise _err(e) from e
    if not fid:
        raise HTTPException(409, "this client already has that filing for that period")
    return {"id": fid}


@router.patch("/filings/{fid}")
async def edit_filing(fid: str, body: FilingEdit, ctx: Board) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            row = await tracker.update_filing(conn, ctx.org_id, fid, body.model_dump(exclude_unset=True), user_id=ctx.principal.user_id,
                                              actor_type=ctx.actor_type)
        except core.CaError as e:
            raise _err(e) from e
    return {"id": fid, "status": row["status"]}


@router.delete("/filings/{fid}")
async def delete_filing(fid: str, ctx: Board) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        gone = (await conn.execute(text("delete from app.ca_filings where id = cast(:i as uuid) returning title"), {"i": fid})).scalar_one_or_none()
        if not gone:
            raise HTTPException(404, "filing not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="ca.filing_deleted",
                           target_type="ca_filing", target_id=fid, metadata={"title": gone})
    return {"deleted": True}


class Season(BaseModel):
    kind: str
    period: Annotated[str, Field(min_length=2, max_length=40)]
    due_on: date | None = None
    client_kinds: list[str] | None = None
    flag: str | None = None


@router.post("/filings/season")
async def season(body: Season, ctx: Board) -> dict:
    _work(ctx)
    if body.kind not in core.KINDS:
        raise HTTPException(422, "unknown filing type")
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await tracker.start_season(conn, ctx.org_id, kind=body.kind, period=body.period, due_on=body.due_on,
                                              client_kinds=body.client_kinds, flag=body.flag, user_id=ctx.principal.user_id)
        except core.CaError as e:
            raise _err(e) from e


# ---------- checklists (document chaser) ----------

class ItemIn(BaseModel):
    key: Annotated[str, Field(min_length=1, max_length=60)]
    status: Literal["missing", "received", "not_needed"]
    label: Annotated[str | None, Field(max_length=120)] = None


@router.post("/filings/{fid}/checklist")
async def checklist_item(fid: str, body: ItemIn, ctx: Chaser) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        try:
            return await chaser.set_item(conn, ctx.org_id, fid, body.key, body.status, label=body.label)
        except core.CaError as e:
            raise _err(e) from e


@router.post("/filings/{fid}/checklist/rebuild")
async def rebuild_checklist(fid: str, ctx: Chaser) -> dict:
    """The checklist again from the client's profile (after their profile changed); items already received stay received."""
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        f = (await conn.execute(text("""select f.kind, f.checklist, c.profile, c.kind as client_kind from app.ca_filings f
            join app.ca_clients c on c.id = f.client_id where f.id = cast(:i as uuid)"""), {"i": fid})).mappings().first()
        if not f:
            raise HTTPException(404, "filing not found")
        old = {i["key"]: i for i in f["checklist"] or []}
        new = [old.get(i["key"], i) for i in chaser.checklist_for(f["kind"], f["profile"], f["client_kind"])]
        new += [i for k, i in old.items() if k not in {n["key"] for n in new} and i["status"] == "received"]
        await conn.execute(text("update app.ca_filings set checklist = cast(:c as jsonb) where id = cast(:i as uuid)"),
                           {"c": core.json.dumps(new), "i": fid})
    return {"checklist": new}


class ChaseIn(BaseModel):
    paused: bool


@router.post("/filings/{fid}/chase")
async def chase(fid: str, body: ChaseIn, ctx: Chaser) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("""update app.ca_filings set chase = chase || jsonb_build_object('paused', cast(:p as boolean))
            where id = cast(:i as uuid)"""), {"p": body.paused, "i": fid})
    return {"paused": body.paused}


# ---------- compliance calendar ----------

@router.get("/compliance")
async def compliance(ctx: Cal, days: int = 60) -> dict:
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        return {"items": await calendar.upcoming(conn, today, max(7, min(days, 400)))}


@router.post("/compliance/refresh")
async def refresh(ctx: Cal) -> dict:
    _work(ctx)
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        cfg = await core.enabled(conn, "ca_compliance_calendar") or {}
        return {"created": await calendar.put_on_board(conn, ctx.org_id, today, int(cfg.get("days_ahead", 30)))}


@router.get("/compliance/client/{cid}")
async def client_dates(cid: str, ctx: Cal) -> dict:
    """What applies to this client over the next 12 months, from their profile."""
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select kind, profile from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
    if not c:
        raise HTTPException(404, "client not found")
    return {"items": calendar.deadlines(c["kind"], c["profile"], today, date(today.year + 1, today.month, 1))}
