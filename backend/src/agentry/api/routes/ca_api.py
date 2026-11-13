"""CA Firm pack in the portal (docs/PACKS.md): clients, the filing board, documents, tax documents and the calendar.

Who: owners, managers, front desk and finance work on it; viewers read. Each part needs its agent switched on
(clients and files: any CA agent).
"""
import json
import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit, official_rules
from agentry.auth import OrgContext, current_org
from agentry.automations.ca import (
    anomalies,
    audit3cd,
    bank,
    calendar,
    capgains,
    chaser,
    cleaner,
    core,
    excel,
    gst,
    hub,
    itr,
    notices,
    recurring,
    taxdocs,
    tds,
    tracker,
)
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter(prefix="/org/ca", dependencies=[Depends(official_rules.fresh)])  # the official figures in force


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


# ---------- upload hub: many files or a zip at once ----------

@router.post("/clients/{cid}/hub", status_code=201)
async def hub_upload(cid: str, ctx: Any, files: Annotated[list[UploadFile], File()]) -> dict:
    """Many files or a zip: each recognised, filed, ticked off the checklist and the right agent run (docs/PLAN-CA-DESK-2.md #3)."""
    _work(ctx)
    if len(files) > hub.MAX_FILES:
        raise HTTPException(422, f"up to {hub.MAX_FILES} files at a time")
    try:
        return await hub.process(ctx.org_id, cid, [(await f.read(hub.MAX_TOTAL + 1), f.filename, f.content_type) for f in files],
                                 source="portal", user_id=ctx.principal.user_id, actor_type=ctx.actor_type)
    except hub.HubError as e:
        raise HTTPException(404 if "not found" in str(e) else 422, str(e)) from e


@router.post("/clients/{cid}/hub/sample", status_code=201)
async def hub_sample(cid: str, ctx: Any) -> dict:
    """A zip as a client would send it: bank statement, broker P&L, purchase register + GSTR-2B, TDS register, day book,
    Form 16, AIS and a notice."""
    _work(ctx)
    try:
        return await hub.process(ctx.org_id, cid, [(hub.sample_zip(), "documents-from-client.zip", "application/zip")],
                                 source="portal", user_id=ctx.principal.user_id, actor_type=ctx.actor_type)
    except hub.HubError as e:
        raise HTTPException(404 if "not found" in str(e) else 422, str(e)) from e


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
    """What applies to this client over the next 12 months, from their profile, with where each date comes from."""
    today = datetime.now(UTC).date()
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select kind, profile, gstin from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
        updates = await calendar.active_updates(conn)
    if not c:
        raise HTTPException(404, "client not found")
    return {"items": calendar.deadlines(c["kind"], c["profile"], today, date(today.year + 1, today.month, 1), gstin=c["gstin"], updates=updates)}


@router.get("/compliance/updates")
async def due_date_updates(ctx: Cal) -> dict:
    """Official due-date changes in force, ones being verified, the last check of official sources, and the sources read."""
    from agentry.automations.ca import due_dates
    return await due_dates.for_firm()


@router.get("/rules")
async def rules_in_use(ctx: Cal) -> dict:
    """The official figures the CA agents use (rates, thresholds, limits), with where each comes from and any change in force."""
    from agentry.automations.ca import due_dates
    data = await due_dates.rules_listing()
    return {"figures": [f for f in data["figures"] if not f["key"].startswith("festival.")],
            "pending": sum(1 for u in data["updates"] if u["status"] == "proposed" and not u["key"].startswith("festival."))}


@router.post("/compliance/updates/check")
async def check_due_date_updates(ctx: Cal) -> dict:
    """Check the official sources now (reuses a check from the last hour)."""
    from agentry.automations.ca import due_dates
    _work(ctx)
    return await due_dates.request_sync("firm", ctx.org_id)


# ---------- agents 5-13: work on a client's documents (results kept in ca_work) ----------

GstOn = Annotated[OrgContext, Depends(needs("ca_gst_reconciliation"))]
ItrOn = Annotated[OrgContext, Depends(needs("ca_itr_prep"))]
CgOn = Annotated[OrgContext, Depends(needs("ca_capital_gains"))]
BankOn = Annotated[OrgContext, Depends(needs("ca_bank_classifier"))]
NoticeOn = Annotated[OrgContext, Depends(needs("ca_notice_handler"))]
TdsOn = Annotated[OrgContext, Depends(needs("ca_tds_returns"))]
AuditOn = Annotated[OrgContext, Depends(needs("ca_tax_audit"))]
ExcelOn = Annotated[OrgContext, Depends(needs("excel_desk"))]
RecurringOn = Annotated[OrgContext, Depends(needs("recurring_books"))]
SAMPLE = taxdocs.SAMPLES
SHEETS = {"ca_gst_reconciliation": gst.sheet, "ca_capital_gains": capgains.sheet, "ca_bank_classifier": bank.sheet, "ca_tds_returns": tds.sheet,
          "ca_tax_audit": audit3cd.sheet}


async def _client(conn, cid: str) -> dict:
    c = (await conn.execute(text("select id::text, name, pan, gstin, kind from app.ca_clients where id = cast(:i as uuid)"), {"i": cid})).mappings().first()
    if not c:
        raise HTTPException(404, "client not found")
    return dict(c)


async def _keep(ctx: OrgContext, cid: str, data: bytes, filename: str | None, mime: str | None, doc_type: str) -> tuple[str, str]:
    """Store an input file on the client's file (so every result can be traced back to it). Returns (file id, mime)."""
    async with tenant_session(ctx.org_id) as conn:
        await _client(conn, cid)
        try:
            fid = await core.store_file(conn, ctx.org_id, cid, data, filename=filename, mime=mime, doc_type=doc_type, user_id=ctx.principal.user_id)
        except core.CaError as e:
            raise _err(e) from e
        return fid, core.mime_of(filename, mime) or ""


async def _save(ctx: OrgContext, cid: str | None, agent: str, title: str, result: dict, file_ids: list[str], params: dict | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        wid = await core.save_work(conn, ctx.org_id, cid, agent, title, result, file_ids=file_ids, params=params, user_id=ctx.principal.user_id)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action=f"{agent}.run",
                           target_type="ca_work", target_id=wid, metadata={"title": title})
    return {"id": wid, "agent": agent, "title": title, "result": result}


@router.get("/clients/{cid}/work")
async def client_work(cid: str, ctx: Any) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, agent, title, created_at from app.ca_work where client_id = cast(:c as uuid)
            order by created_at desc limit 200"""), {"c": cid})).mappings().all()
    return {"items": [dict(r) for r in rows]}


async def _work_row(conn, wid: str) -> dict:
    w = (await conn.execute(text("select * from app.ca_work where id = cast(:i as uuid)"), {"i": wid})).mappings().first()
    if not w:
        raise HTTPException(404, "not found")
    return dict(w)


@router.get("/work/{wid}")
async def work(wid: str, ctx: Any) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        w = await _work_row(conn, wid)
    return {k: (str(v) if k in ("id", "client_id") and v else v) for k, v in w.items() if k != "org_id"} | {"file_ids": [str(x) for x in w["file_ids"]]}


@router.delete("/work/{wid}")
async def delete_work(wid: str, ctx: Any) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("delete from app.ca_work where id = cast(:i as uuid)"), {"i": wid})
    return {"deleted": True}


@router.get("/work/{wid}/sheet.xlsx")
async def work_sheet(wid: str, ctx: Any) -> Response:
    async with tenant_session(ctx.org_id) as conn:
        w = await _work_row(conn, wid)
        client_name = (await conn.execute(text("select name from app.ca_clients where id = :c"), {"c": w["client_id"]})).scalar_one_or_none() if w["client_id"] else ""
    r = w["result"]
    if w["agent"] == "ca_itr_prep":
        body = itr.sheet(client_name or "", r)
    elif w["agent"] == "excel_desk":
        body = excel.sheet_reco(r) if "counts" in r else excel.sheet_table(r) if "columns" in r else core.xlsx_bytes({"Answer": [["Question", w["title"]], ["Answer", json.dumps(r.get("answer"))]]})
    elif w["agent"] == "ca_gst_reconciliation":
        body = gst.sheet(r)
    elif w["agent"] == "excel_cleaner":
        body = cleaner.sheet(r)
    elif w["agent"] == "ca_anomaly_finder":
        body = anomalies.sheet(r)
    elif w["agent"] == "ca_upload_hub":
        body = hub.sheet(r)
    elif w["agent"] in SHEETS:
        body = SHEETS[w["agent"]](r)
    else:
        raise HTTPException(404, "no sheet for this")
    name = re.sub(r"[^A-Za-z0-9-]+", "-", f"{client_name or 'agentry'}-{w['title']}")[:80].strip("-")
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


def _read_error(e: Exception) -> HTTPException:
    return _err(e) if isinstance(e, core.CaError) else HTTPException(422, "this file couldn't be read")


# GST reconciliation

async def _gst(ctx: OrgContext, cid: str, two_b: tuple[bytes, str | None, str | None], books: tuple[bytes, str | None, str | None], period: str) -> dict:
    f1, m1 = await _keep(ctx, cid, *two_b, "gstr2b")
    f2, m2 = await _keep(ctx, cid, *books, "purchase_register")
    async with tenant_session(ctx.org_id) as conn:
        client = await _client(conn, cid)
        cfg = await core.enabled(conn, "ca_gst_reconciliation") or {}
    try:
        r = gst.reconcile(gst.records(two_b[0], m1), gst.records(books[0], m2), float(cfg.get("tolerance", 10)))
    except (core.CaError, ValueError) as e:
        raise _read_error(e) from e
    r["messages"] = gst.supplier_messages(r, client["name"], client["gstin"], period)
    return await _save(ctx, cid, "ca_gst_reconciliation", f"GST reconciliation {period}", r, [f1, f2], {"period": period})


@router.post("/clients/{cid}/gst", status_code=201)
async def gst_run(cid: str, ctx: GstOn, gstr2b: Annotated[UploadFile, File()], books: Annotated[UploadFile, File()],
                  period: Annotated[str, Form(min_length=2, max_length=30)]) -> dict:
    _work(ctx)
    return await _gst(ctx, cid, (await gstr2b.read(), gstr2b.filename, gstr2b.content_type), (await books.read(), books.filename, books.content_type), period)


@router.post("/clients/{cid}/gst/sample", status_code=201)
async def gst_sample(cid: str, ctx: GstOn) -> dict:
    _work(ctx)
    return await _gst(ctx, cid, ((SAMPLE / "gstr2b_sample.json").read_bytes(), "gstr2b_sample.json", "application/json"),
                      ((SAMPLE / "purchase_register_sample.csv").read_bytes(), "purchase_register_sample.csv", "text/csv"), "Oct 2026 (sample)")


# ITR preparation

@router.get("/clients/{cid}/itr/prefill")
async def itr_prefill(cid: str, ctx: ItrOn, ay: str | None = None) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _client(conn, cid)
        docs = await taxdocs.client_docs(conn, cid, ay)
        cg = (await conn.execute(text("""select result->'summary' from app.ca_work where client_id = cast(:c as uuid) and agent = 'ca_capital_gains'
            order by created_at desc limit 1"""), {"c": cid})).scalar_one_or_none()
    return {"inputs": itr.prefill(docs, cg), "fields": itr.FIELDS, "from": {"documents": len(docs), "capital_gains": bool(cg)}}


class ItrIn(BaseModel):
    inputs: dict[str, float | int | str | None]
    age: Literal["below60", "60to80", "above80"] = "below60"
    assessment_year: Annotated[str, Field(max_length=10)] = "2026-27"


@router.post("/clients/{cid}/itr", status_code=201)
async def itr_run(cid: str, body: ItrIn, ctx: ItrOn) -> dict:
    _work(ctx)
    p = {k: v for k, v in body.inputs.items() if k in itr.FIELDS} | {"age": body.age}
    r = itr.prepare(p)
    return await _save(ctx, cid, "ca_itr_prep", f"ITR computation AY {body.assessment_year}", r, [], {"age": body.age})


# capital gains, bank statements, TDS, tax audit: one file in, a result out

async def _one(ctx: OrgContext, cid: str, agent: str, upload: tuple[bytes, str | None, str | None], doc_type: str, title: str, run) -> dict:
    fid, mime = await _keep(ctx, cid, *upload, doc_type)
    try:
        r = await run(upload[0], mime)
    except (core.CaError, ValueError, KeyError, IndexError) as e:
        raise _read_error(e) from e
    return await _save(ctx, cid, agent, title, r, [fid])


async def _cg(data: bytes, mime: str) -> dict:
    return capgains.compute(data, mime)


@router.post("/clients/{cid}/capital-gains", status_code=201)
async def cg_run(cid: str, ctx: CgOn, file: Annotated[UploadFile, File()]) -> dict:
    _work(ctx)
    return await _one(ctx, cid, "ca_capital_gains", (await file.read(), file.filename, file.content_type), "broker_pnl", f"Capital gains: {file.filename}", _cg)


@router.post("/clients/{cid}/capital-gains/sample", status_code=201)
async def cg_sample(cid: str, ctx: CgOn) -> dict:
    _work(ctx)
    p = SAMPLE / "broker_pnl_sample.csv"
    return await _one(ctx, cid, "ca_capital_gains", (p.read_bytes(), p.name, "text/csv"), "broker_pnl", "Capital gains: sample broker P&L", _cg)


async def _bank(ctx: OrgContext, cid: str, upload: tuple[bytes, str | None, str | None]) -> dict:
    async def run(data: bytes, mime: str) -> dict:
        async with tenant_session(ctx.org_id) as conn:
            cfg = await core.enabled(conn, "ca_bank_classifier") or {}
            return await bank.run(ctx.org_id, conn, data, mime, bool(cfg.get("use_model", True)))
    return await _one(ctx, cid, "ca_bank_classifier", upload, "bank_statement", f"Bank statement: {upload[1]}", run)


@router.post("/clients/{cid}/bank", status_code=201)
async def bank_run(cid: str, ctx: BankOn, file: Annotated[UploadFile, File()]) -> dict:
    _work(ctx)
    return await _bank(ctx, cid, (await file.read(), file.filename, file.content_type))


@router.post("/clients/{cid}/bank/sample", status_code=201)
async def bank_sample(cid: str, ctx: BankOn) -> dict:
    _work(ctx)
    p = SAMPLE / "bank_statement_sample.csv"
    return await _bank(ctx, cid, (p.read_bytes(), p.name, "text/csv"))


class BankLine(BaseModel):
    row: int
    category: str
    learn: bool = True


@router.post("/work/{wid}/bank-line")
async def bank_line(wid: str, body: BankLine, ctx: BankOn) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        w = await _work_row(conn, wid)
        if w["agent"] != "ca_bank_classifier":
            raise HTTPException(404, "not a bank statement")
        try:
            r = await bank.correct(conn, ctx.org_id, w["result"], body.row, body.category, body.learn, ctx.principal.user_id)
        except core.CaError as e:
            raise _err(e) from e
        learned = r.pop("pattern")
        await conn.execute(text("update app.ca_work set result = cast(:r as jsonb), updated_at = now() where id = cast(:i as uuid)"),
                           {"r": json.dumps(r, default=str), "i": wid})
    return {"learned": learned, "totals": r["totals"]}


async def _tds(data: bytes, mime: str) -> dict:
    return tds.compute(data, mime)


@router.post("/clients/{cid}/tds", status_code=201)
async def tds_run(cid: str, ctx: TdsOn, file: Annotated[UploadFile, File()]) -> dict:
    _work(ctx)
    return await _one(ctx, cid, "ca_tds_returns", (await file.read(), file.filename, file.content_type), "tds_register", f"TDS: {file.filename}", _tds)


@router.post("/clients/{cid}/tds/sample", status_code=201)
async def tds_sample(cid: str, ctx: TdsOn) -> dict:
    _work(ctx)
    p = SAMPLE / "tds_register_sample.csv"
    return await _one(ctx, cid, "ca_tds_returns", (p.read_bytes(), p.name, "text/csv"), "tds_register", "TDS: sample payments register", _tds)


def _audit_runner(fy: int, days: int):
    async def run(data: bytes, mime: str) -> dict:
        return audit3cd.compute(data, mime, fy, days)
    return run


async def _audit(ctx: OrgContext, cid: str, upload: tuple[bytes, str | None, str | None], fy: int) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        cfg = await core.enabled(conn, "ca_tax_audit") or {}
    return await _one(ctx, cid, "ca_tax_audit", upload, "ledger", f"3CD checks FY {fy}-{str(fy + 1)[2:]}",
                      _audit_runner(fy, int(cfg.get("msme_default_days", 15))))


@router.post("/clients/{cid}/audit", status_code=201)
async def audit_run(cid: str, ctx: AuditOn, file: Annotated[UploadFile, File()], fy: Annotated[int, Form(ge=2020, le=2035)]) -> dict:
    _work(ctx)
    return await _audit(ctx, cid, (await file.read(), file.filename, file.content_type), fy)


@router.post("/clients/{cid}/audit/sample", status_code=201)
async def audit_sample(cid: str, ctx: AuditOn) -> dict:
    _work(ctx)
    p = SAMPLE / "ledger_sample.csv"
    return await _audit(ctx, cid, (p.read_bytes(), p.name, "text/csv"), 2025)


# notices

@router.post("/clients/{cid}/notices", status_code=201)
async def notice_run(cid: str, ctx: NoticeOn, file: Annotated[UploadFile, File()]) -> dict:
    _work(ctx)
    fid, _ = await _keep(ctx, cid, await file.read(), file.filename, file.content_type, "notice")
    try:
        return await notices.handle(ctx.org_id, cid, fid, ctx.principal.user_id)
    except core.CaError as e:
        raise _err(e) from e


@router.post("/clients/{cid}/notices/sample", status_code=201)
async def notice_sample(cid: str, ctx: NoticeOn) -> dict:
    _work(ctx)
    p = SAMPLE / "notice_143_1_sample.txt"
    fid, _ = await _keep(ctx, cid, p.read_bytes(), p.name, "text/plain", "notice")
    return await notices.handle(ctx.org_id, cid, fid, ctx.principal.user_id)


# ---------- Excel desk (the firm's own; no client needed) ----------

@router.get("/excel")
async def excel_list(ctx: ExcelOn) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id::text, title, created_at, params from app.ca_work where agent in ('excel_desk', 'excel_cleaner', 'ca_anomaly_finder') and client_id is null
            order by created_at desc limit 50"""))).mappings().all()
    return {"items": [dict(r) for r in rows]}


def _mime(f: UploadFile, data: bytes) -> str:
    m = core.mime_of(f.filename, f.content_type)
    if not m:
        raise HTTPException(422, "upload a PDF, photo, CSV or Excel file")
    if len(data) > core.MAX_FILE:
        raise HTTPException(422, "files can be up to 20 MB")
    return m


@router.post("/excel/table", status_code=201)
async def excel_table(ctx: ExcelOn, file: Annotated[UploadFile, File()], columns: Annotated[str | None, Form(max_length=500)] = None) -> dict:
    _work(ctx)
    data = await file.read()
    try:
        t = await excel.to_excel(ctx.org_id, data, _mime(file, data), [c.strip() for c in (columns or "").split(",") if c.strip()] or None)
    except core.CaError as e:
        raise _err(e) from e
    return await _save(ctx, None, "excel_desk", f"To Excel: {file.filename}", t, [], {"kind": "table"})


@router.post("/excel/reconcile", status_code=201)
async def excel_reconcile(ctx: ExcelOn, first: Annotated[UploadFile, File()], second: Annotated[UploadFile, File()],
                          tolerance: Annotated[float, Form(ge=0, le=100000)] = 1) -> dict:
    _work(ctx)
    a, b = await first.read(), await second.read()
    try:
        r = excel.reconcile(core.table_rows(a, _mime(first, a)), core.table_rows(b, _mime(second, b)), tolerance)
    except (core.CaError, ValueError, IndexError) as e:
        raise _read_error(e) from e
    return await _save(ctx, None, "excel_desk", f"Reconcile: {first.filename} vs {second.filename}", r, [], {"kind": "reconcile"})


@router.post("/excel/ask", status_code=201)
async def excel_ask(ctx: ExcelOn, file: Annotated[UploadFile, File()], question: Annotated[str, Form(min_length=3, max_length=300)]) -> dict:
    _work(ctx)
    data = await file.read()
    try:
        r = await excel.ask(ctx.org_id, core.table_rows(data, _mime(file, data)), question)
    except (core.CaError, ValueError, IndexError) as e:
        raise _read_error(e) from e
    return await _save(ctx, None, "excel_desk", question, r, [], {"kind": "ask", "file": file.filename})


@router.post("/excel/clean", status_code=201)
async def excel_clean(ctx: ExcelOn, file: Annotated[UploadFile, File()], standardise_names: Annotated[bool, Form()] = False) -> dict:
    """The Excel cleaner (docs/PLAN-CA-DESK-2.md #1): a messy sheet in, a clean one out with a log of every change. No AI."""
    _work(ctx)
    data = await file.read()
    try:
        r = cleaner.compute(data, _mime(file, data), standardise_names)
    except (core.CaError, ValueError, IndexError) as e:
        raise _read_error(e) from e
    return await _save(ctx, None, "excel_cleaner", f"Cleaned: {file.filename}", r, [], {"kind": "clean", "file": file.filename})


@router.post("/excel/clean/sample", status_code=201)
async def excel_clean_sample(ctx: ExcelOn) -> dict:
    _work(ctx)
    r = cleaner.compute((SAMPLE / "messy_sales_register_sample.csv").read_bytes(), "text/csv")
    return await _save(ctx, None, "excel_cleaner", "Cleaned: messy sales register (sample)", r, [], {"kind": "clean", "file": "sample"})


@router.post("/excel/anomalies", status_code=201)
async def excel_anomalies(ctx: ExcelOn, file: Annotated[UploadFile, File()]) -> dict:
    """The anomaly finder (docs/PLAN-CA-DESK-2.md #2) on the firm's own sheet. No AI."""
    _work(ctx)
    data = await file.read()
    try:
        r = anomalies.compute(data, _mime(file, data))
    except (core.CaError, ValueError, IndexError) as e:
        raise _read_error(e) from e
    return await _save(ctx, None, "ca_anomaly_finder", f"Anomalies: {file.filename}", r, [], {"kind": "anomalies", "file": file.filename})


@router.post("/excel/anomalies/sample", status_code=201)
async def excel_anomalies_sample(ctx: ExcelOn) -> dict:
    _work(ctx)
    r = anomalies.compute((SAMPLE / "purchase_daybook_sample.csv").read_bytes(), "text/csv")
    return await _save(ctx, None, "ca_anomaly_finder", "Anomalies: purchase day book (sample)", r, [], {"kind": "anomalies", "file": "sample"})


async def _anomalies_for(ctx: OrgContext, cid: str, upload: tuple[bytes, str | None, str | None], title: str) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        gstin = (await _client(conn, cid))["gstin"]

    async def run(data: bytes, mime: str) -> dict:
        return anomalies.compute(data, mime, firm_gstin=gstin)
    return await _one(ctx, cid, "ca_anomaly_finder", upload, "ledger", title, run)


@router.post("/clients/{cid}/anomalies", status_code=201)
async def client_anomalies(cid: str, ctx: ExcelOn, file: Annotated[UploadFile, File()]) -> dict:
    """On a client: the client's own GSTIN decides same-state vs other-state, and the file is kept on the client."""
    _work(ctx)
    return await _anomalies_for(ctx, cid, (await file.read(), file.filename, file.content_type), f"Anomalies: {file.filename}")


@router.post("/clients/{cid}/anomalies/sample", status_code=201)
async def client_anomalies_sample(cid: str, ctx: ExcelOn) -> dict:
    _work(ctx)
    p = SAMPLE / "purchase_daybook_sample.csv"
    return await _anomalies_for(ctx, cid, (p.read_bytes(), p.name, "text/csv"), "Anomalies: sample purchase day book")


# ---------- recurring entries (the firm's own books) ----------

class RecurringIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    vendor: Annotated[str, Field(min_length=2, max_length=120)]
    category: Annotated[str, Field(min_length=2, max_length=60)]
    amount: Annotated[float, Field(gt=0, le=1e9)]
    gst_rate: Annotated[float, Field(ge=0, le=28)] = 0
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"] = "monthly"
    next_on: date
    ends_on: date | None = None
    active: bool = True


@router.get("/recurring")
async def recurring_list(ctx: RecurringOn) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = await recurring.entries(conn)
    return {"items": rows, "monthly_cost": recurring.monthly_cost(rows)}


@router.post("/recurring", status_code=201)
async def recurring_add(body: RecurringIn, ctx: RecurringOn) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        rid = (await conn.execute(text("""insert into app.recurring_entries (org_id, name, vendor, category, amount, gst_rate, frequency, next_on,
            ends_on, active, created_by) values (:o, :n, :v, :c, :a, :g, :f, :nx, :e, :ac, :u) returning id::text"""),
            {"o": ctx.org_id, "n": body.name, "v": body.vendor, "c": body.category, "a": body.amount, "g": body.gst_rate, "f": body.frequency,
             "nx": body.next_on, "e": body.ends_on, "ac": body.active, "u": ctx.principal.user_id})).scalar_one()
    return {"id": rid}


@router.patch("/recurring/{rid}")
async def recurring_edit(rid: str, body: RecurringIn, ctx: RecurringOn) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        done = (await conn.execute(text("""update app.recurring_entries set name = :n, vendor = :v, category = :c, amount = :a, gst_rate = :g,
            frequency = :f, next_on = :nx, ends_on = :e, active = :ac where id = cast(:i as uuid) returning id"""),
            {"n": body.name, "v": body.vendor, "c": body.category, "a": body.amount, "g": body.gst_rate, "f": body.frequency, "nx": body.next_on,
             "e": body.ends_on, "ac": body.active, "i": rid})).first()
    if not done:
        raise HTTPException(404, "not found")
    return {"id": rid}


@router.delete("/recurring/{rid}")
async def recurring_delete(rid: str, ctx: RecurringOn) -> dict:
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("delete from app.recurring_entries where id = cast(:i as uuid)"), {"i": rid})
    return {"deleted": True}


@router.post("/recurring/run")
async def recurring_run(ctx: RecurringOn) -> dict:
    _work(ctx)
    return {"booked": await recurring.book_due(ctx.org_id)}


# ---------- client portal (automations/ca/portal.py) ----------

def _portal_admin(ctx: OrgContext) -> None:
    if ctx.role not in ("owner", "manager", None):
        raise HTTPException(403, "only the owner or a manager can change the client portal")


@router.get("/portal")
async def portal_settings(ctx: Board) -> dict:
    from agentry.automations.ca import portal
    async with tenant_session(ctx.org_id) as conn:
        return await portal.get_settings(conn)


class PortalSettings(BaseModel):
    enabled: bool
    title: Annotated[str | None, Field(max_length=80)] = None
    color: Annotated[str | None, Field(max_length=9)] = None
    logo_url: Annotated[str | None, Field(max_length=400)] = None
    welcome: Annotated[str | None, Field(max_length=300)] = None


@router.put("/portal")
async def save_portal(body: PortalSettings, ctx: Board) -> dict:
    from agentry.automations.ca import portal
    _portal_admin(ctx)
    try:
        async with tenant_session(ctx.org_id) as conn:
            out = await portal.save_settings(conn, body.model_dump())
            await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="ca.portal_settings",
                               metadata={"enabled": body.enabled})
        return out
    except portal.PortalError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/clients/{cid}/portal")
async def client_portal_link(cid: str, ctx: Board) -> dict:
    from agentry.automations.ca import portal
    async with tenant_session(ctx.org_id) as conn:
        return {"link": await portal.link_status(conn, cid), "settings": await portal.get_settings(conn)}


@router.post("/clients/{cid}/portal")
async def make_portal_link(cid: str, ctx: Board, send: bool = False) -> dict:
    """A new private link for this client (the old one stops working): sent to them, or returned to copy."""
    from agentry.automations.ca import portal
    _work(ctx)
    try:
        if send:
            return await portal.send_link(ctx.org_id, cid, ctx.principal.user_id)
        async with tenant_session(ctx.org_id) as conn:
            return await portal.create_link(conn, ctx.org_id, cid, ctx.principal.user_id)
    except portal.PortalError as e:
        raise HTTPException(e.status, str(e)) from e


@router.delete("/clients/{cid}/portal")
async def revoke_portal_link(cid: str, ctx: Board) -> dict:
    from agentry.automations.ca import portal
    _work(ctx)
    async with tenant_session(ctx.org_id) as conn:
        return {"revoked": await portal.revoke(conn, cid)}


public_portal = APIRouter(prefix="/public/portal", tags=["public"])


@public_portal.get("/{token}")
async def portal_view(token: str) -> dict:
    from agentry.automations.ca import portal
    try:
        return await portal.view(token)
    except portal.PortalError as e:
        raise HTTPException(e.status, str(e)) from e


@public_portal.post("/{token}/files/many", status_code=201)
async def portal_upload_many(token: str, files: Annotated[list[UploadFile], File()]) -> dict:
    from agentry.automations.ca import portal
    if len(files) > hub.MAX_FILES:
        raise HTTPException(422, f"up to {hub.MAX_FILES} files at a time")
    try:
        return await portal.upload_many(token, [(await f.read(hub.MAX_TOTAL + 1), f.filename, f.content_type) for f in files])
    except portal.PortalError as e:
        raise HTTPException(e.status, str(e)) from e


@public_portal.post("/{token}/files", status_code=201)
async def portal_upload(token: str, file: Annotated[UploadFile, File()], filing_id: Annotated[str | None, Form()] = None) -> dict:
    from agentry.automations.ca import portal
    data = await file.read(core.MAX_FILE + 1)
    try:
        return await portal.upload(token, data, filename=file.filename, mime=file.content_type, filing_id=filing_id or None)
    except portal.PortalError as e:
        raise HTTPException(e.status, str(e)) from e
