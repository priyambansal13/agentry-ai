"""Competitor & price watch in the portal (10.1): the watched pages, their latest changes, add / check now / pause / remove.

Everyone with dashboard access sees it; owners and managers (automation:configure) change the list.
"""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import text

from agentry import audit, watchers
from agentry.auth import OrgContext, client_ip, current_org
from agentry.automations.competitor_watch import CompetitorWatchConfig
from agentry.db import tenant_session
from agentry.features import enabled_automations

router = APIRouter(prefix="/org/watchers")


async def _ctx(ctx: Annotated[OrgContext, Depends(current_org)]) -> OrgContext:
    if not ctx.can("dashboard", "read"):
        raise HTTPException(403, "no access")
    async with tenant_session(ctx.org_id) as conn:
        if "competitor_watch" not in await enabled_automations(conn):
            raise HTTPException(404, "competitor & price watch isn't switched on")
    return ctx


Reader = Annotated[OrgContext, Depends(_ctx)]


def _edit(ctx: OrgContext) -> None:
    if not ctx.can("automation", "configure"):
        raise HTTPException(403, "only owners and managers change what's watched")


async def _config(conn) -> dict:
    row = (await conn.execute(text("select config from app.automation_instances where template_key = 'competitor_watch'"))).scalar_one_or_none()
    return CompetitorWatchConfig(**(row or {})).model_dump()


@router.get("")
async def list_watchers(ctx: Reader) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select w.id::text, w.kind, w.name, w.url, w.every_minutes, w.rule, w.status, w.error,
                w.last_checked_at, w.last_changed_at, w.next_check_at, w.last_value - 'text' - '_failures' as value
            from app.watchers w where w.kind in ('page','price') order by w.created_at"""))).mappings().all()
        changes = (await conn.execute(text("""select s.watcher_id::text, s.at, s.summary from app.watch_snapshots s
            where s.notified order by s.at desc limit 30"""))).mappings().all()
        cfg = await _config(conn)
    return {"items": [dict(r) for r in rows], "changes": [dict(c) for c in changes], "max_pages": cfg["max_pages"],
            "can_edit": ctx.can("automation", "configure")}


class NewWatcher(BaseModel):
    kind: Literal["page", "price"]
    name: Annotated[str, Field(min_length=2, max_length=120)]
    url: HttpUrl


@router.post("", status_code=201)
async def add(b: NewWatcher, request: Request, ctx: Reader) -> dict:
    _edit(ctx)
    url = str(b.url)
    if not url.startswith("https://") and not url.startswith("http://"):
        raise HTTPException(422, "enter a web address starting with https://")
    async with tenant_session(ctx.org_id) as conn:
        cfg = await _config(conn)
        n = (await conn.execute(text("select count(*) from app.watchers where kind in ('page','price') and status <> 'paused'"))).scalar_one()
        if n >= cfg["max_pages"]:
            raise HTTPException(409, f"your plan includes {cfg['max_pages']} pages: remove one first")
        wid = (await conn.execute(text("""insert into app.watchers (org_id, kind, name, url, every_minutes, rule, created_by)
            values (:o, :k, :n, :u, :m, cast(:r as jsonb), :by) returning id::text"""),
            {"o": ctx.org_id, "k": b.kind, "n": b.name, "u": url, "m": cfg["check_every_hours"] * 60,
             "r": json.dumps({"min_change_pct": cfg["min_change_pct"]} if b.kind == "price" else {}), "by": ctx.principal.user_id})).scalar_one()
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="watcher.added",
                           target_type="watcher", target_id=wid, ip=client_ip(request), metadata={"url": url, "kind": b.kind})
    first = await watchers.check(ctx.org_id, wid)  # the starting point (and a check that the page can be read)
    return {"id": wid, "error": first.get("error")}


@router.post("/{wid}/check")
async def check_now(wid: str, ctx: Reader) -> dict:
    _edit(ctx)
    async with tenant_session(ctx.org_id) as conn:
        if not (await conn.execute(text("select 1 from app.watchers where id = cast(:i as uuid) and kind in ('page','price')"), {"i": wid})).first():
            raise HTTPException(404, "not found")
        await conn.execute(text("update app.watchers set status = 'active', last_value = last_value - '_failures' where id = cast(:i as uuid)"), {"i": wid})
    return await watchers.check(ctx.org_id, wid)


class Status(BaseModel):
    status: Literal["active", "paused"]


@router.put("/{wid}")
async def set_status(wid: str, b: Status, ctx: Reader) -> dict:
    _edit(ctx)
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.watchers set status = :s, next_check_at = now() where id = cast(:i as uuid)
            and kind in ('page','price')"""), {"s": b.status, "i": wid})).rowcount
    if not n:
        raise HTTPException(404, "not found")
    return {"status": b.status}


@router.delete("/{wid}")
async def remove(wid: str, request: Request, ctx: Reader) -> dict:
    _edit(ctx)
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("delete from app.watchers where id = cast(:i as uuid) and kind in ('page','price')"), {"i": wid})).rowcount
        if n:
            await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="watcher.removed",
                               target_type="watcher", target_id=wid, ip=client_ip(request))
    if not n:
        raise HTTPException(404, "not found")
    return {"removed": True}
