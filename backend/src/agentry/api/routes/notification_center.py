"""Notification Center in the portal: rules (business-wide for owners and managers, personal for anyone), each person's
quiet hours and hourly limit, the bell (in-app inbox) and, for Agentry staff, the delivery log."""
import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from agentry import audit
from agentry.auth import OrgContext, Principal, client_ip, current_org, require_staff
from agentry.db import tenant_session
from agentry.features import enabled_automations
from agentry.notify import center

router = APIRouter()
Channel = Literal["telegram", "whatsapp", "email", "in_app"]


def _can_see(ctx: OrgContext, event_type: str) -> bool:
    spec = center.CATALOGUE[event_type]
    return ctx.can(*spec.permission)


async def _my_channels(conn, ctx: OrgContext) -> list[str]:
    from agentry import telegram_team
    from agentry.notify.alerts import whatsapp_alerts
    prefs = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none() or {}
    tg = (await conn.execute(text("select 1 from app.telegram_links where user_id = :u"), {"u": ctx.principal.user_id})).first()
    out = ["in_app", "email"]
    if tg and telegram_team.enabled():
        out.insert(0, "telegram")
    if prefs.get("whatsapp_to") and await whatsapp_alerts(ctx.org_id):
        out.insert(1, "whatsapp")
    return out


@router.get("/org/notification-center")
async def overview(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await center.ensure_defaults(conn, ctx.org_id)
        autos = await enabled_automations(conn)
        rules = [dict(r) for r in (await conn.execute(text("""select * from app.notification_rules where owner_user is null or owner_user = :u
            order by owner_user nulls first, event_type, created_at"""), {"u": ctx.principal.user_id})).mappings()]
        prefs = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none() or {}
        channels = await _my_channels(conn, ctx)
        people = [dict(r) for r in (await conn.execute(text("""select u.id, coalesce(u.name, u.email) as name, m.role from auth.member m
            join auth."user" u on u.id = m."userId" where m."organizationId" = :o order by u.name"""), {"o": ctx.org_id})).mappings()]
    catalogue = [{"type": t, "label": s.label, "area": s.area, "facts": s.facts} for t, s in center.CATALOGUE.items()
                 if center.available(t, autos) and _can_see(ctx, t)]
    seen = {c["type"] for c in catalogue}
    muted = set(prefs.get("muted_rules") or [])
    return {"catalogue": catalogue, "rules": [r | {"id": str(r["id"]), "muted": str(r["id"]) in muted, "mine": r["owner_user"] == ctx.principal.user_id}
                                             for r in rules if r["event_type"] in seen],
            "settings": {"quiet": prefs.get("quiet"), "max_per_hour": prefs.get("max_per_hour") or center.DEFAULT_MAX_PER_HOUR},
            "channels": channels, "people": people, "can_edit_business": ctx.can("automation", "configure")}


class Condition(BaseModel):
    field: Annotated[str, Field(max_length=40)]
    op: Literal["gt", "gte", "lt", "lte", "eq", "ne", "in", "contains"]
    value: str | float | int | bool | list[str]


class RuleIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=80)]
    event_type: str
    conditions: list[Condition] = Field(default_factory=list, max_length=5)
    roles: list[Literal["owner", "manager", "staff", "finance", "viewer"]] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list, max_length=20)
    assignee: bool = False
    channels: list[Channel] = Field(default_factory=lambda: ["in_app"], min_length=1)
    cadence: Literal["now", "digest"] = "now"
    digest_hour: Annotated[int, Field(ge=0, le=23)] = 18
    critical: bool = False
    personal: bool = False  # true: only for me (anyone may make these)


async def _validate(conn, ctx: OrgContext, b: RuleIn) -> None:
    if not b.personal and not ctx.can("automation", "configure"):
        raise HTTPException(403, "only owners and managers set rules for the whole business; make it a personal rule")
    autos = await enabled_automations(conn)
    if b.event_type not in center.CATALOGUE or not center.available(b.event_type, autos) or not _can_see(ctx, b.event_type):
        raise HTTPException(422, "that event isn't available here")
    facts = center.CATALOGUE[b.event_type].facts
    for c in b.conditions:
        if c.field not in facts:
            raise HTTPException(422, f"'{c.field}' can't be checked for this event")
        if c.op in ("gt", "gte", "lt", "lte") and facts[c.field] != "number":
            raise HTTPException(422, f"'{c.field}' isn't a number")
    if not b.personal and not (b.roles or b.user_ids or b.assignee):
        raise HTTPException(422, "choose who gets it")


def _row(b: RuleIn, ctx: OrgContext) -> dict:
    return {"n": b.name, "e": b.event_type, "c": json.dumps([c.model_dump() for c in b.conditions]), "r": [] if b.personal else b.roles,
            "u": [] if b.personal else b.user_ids, "a": False if b.personal else b.assignee, "ch": list(dict.fromkeys(b.channels)),
            "cad": b.cadence, "h": b.digest_hour, "crit": b.critical, "own": ctx.principal.user_id if b.personal else None}


@router.post("/org/notification-rules", status_code=201)
async def create_rule(b: RuleIn, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _validate(conn, ctx, b)
        rid = str((await conn.execute(text("""insert into app.notification_rules (org_id, name, event_type, conditions, roles, user_ids, assignee,
            channels, cadence, digest_hour, critical, owner_user, created_by) values (:o, :n, :e, cast(:c as jsonb), :r, :u, :a, :ch, :cad, :h,
            :crit, :own, :by) returning id"""), {"o": ctx.org_id, "by": ctx.principal.user_id, **_row(b, ctx)})).scalar_one())
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="notification_rule.created",
                           target_type="notification_rule", target_id=rid, ip=client_ip(request), metadata={"event": b.event_type, "personal": b.personal})
    return {"id": rid}


async def _editable(conn, ctx: OrgContext, rid: str) -> dict:
    r = (await conn.execute(text("select * from app.notification_rules where id::text = :i"), {"i": rid})).mappings().first()
    if not r or (r["owner_user"] and r["owner_user"] != ctx.principal.user_id):
        raise HTTPException(404, "rule not found")
    if not r["owner_user"] and not ctx.can("automation", "configure"):
        raise HTTPException(403, "only owners and managers change business rules (you can mute it for yourself)")
    return dict(r)


@router.put("/org/notification-rules/{rid}")
async def update_rule(rid: str, b: RuleIn, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        r = await _editable(conn, ctx, rid)
        b.personal = bool(r["owner_user"])
        await _validate(conn, ctx, b)
        await conn.execute(text("""update app.notification_rules set name = :n, event_type = :e, conditions = cast(:c as jsonb), roles = :r,
            user_ids = :u, assignee = :a, channels = :ch, cadence = :cad, digest_hour = :h, critical = :crit, updated_at = now()
            where id::text = :i"""), {"i": rid, **{k: v for k, v in _row(b, ctx).items() if k != "own"}})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="notification_rule.changed",
                           target_type="notification_rule", target_id=rid, ip=client_ip(request))
    return {"id": rid}


class Toggle(BaseModel):
    enabled: bool


@router.post("/org/notification-rules/{rid}/enabled")
async def toggle_rule(rid: str, b: Toggle, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _editable(conn, ctx, rid)
        await conn.execute(text("update app.notification_rules set enabled = :e, updated_at = now() where id::text = :i"), {"e": b.enabled, "i": rid})
    return {"id": rid, "enabled": b.enabled}


@router.delete("/org/notification-rules/{rid}")
async def delete_rule(rid: str, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        await _editable(conn, ctx, rid)
        await conn.execute(text("delete from app.notification_rules where id::text = :i"), {"i": rid})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="notification_rule.deleted",
                           target_type="notification_rule", target_id=rid, ip=client_ip(request))
    return {"deleted": True}


class Mute(BaseModel):
    muted: bool


@router.post("/org/notification-rules/{rid}/mute")
async def mute_rule(rid: str, b: Mute, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Anyone can mute a business rule for themselves."""
    async with tenant_session(ctx.org_id) as conn:
        prefs = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none() or {}
        muted = set(prefs.get("muted_rules") or [])
        muted = muted | {rid} if b.muted else muted - {rid}
        await _save_prefs(conn, ctx, {**prefs, "muted_rules": sorted(muted)})
    return {"id": rid, "muted": b.muted}


async def _save_prefs(conn, ctx: OrgContext, prefs: dict) -> None:
    await conn.execute(text("""insert into app.notification_preferences (user_id, org_id, prefs) values (:u, :o, cast(:p as jsonb))
        on conflict (user_id, org_id) do update set prefs = excluded.prefs"""), {"u": ctx.principal.user_id, "o": ctx.org_id, "p": json.dumps(prefs)})


class Settings(BaseModel):
    quiet_from: Annotated[str | None, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = None
    quiet_to: Annotated[str | None, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = None
    max_per_hour: Annotated[int, Field(ge=1, le=100)] = center.DEFAULT_MAX_PER_HOUR


@router.put("/org/notification-settings")
async def my_settings(b: Settings, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if bool(b.quiet_from) != bool(b.quiet_to):
        raise HTTPException(422, "set both the start and the end of quiet hours, or neither")
    async with tenant_session(ctx.org_id) as conn:
        prefs = (await conn.execute(text("select prefs from app.notification_preferences where user_id = :u"), {"u": ctx.principal.user_id})).scalar_one_or_none() or {}
        prefs = {**prefs, "max_per_hour": b.max_per_hour, "quiet": {"from": b.quiet_from, "to": b.quiet_to} if b.quiet_from else None}
        await _save_prefs(conn, ctx, prefs)
    return {"quiet": prefs["quiet"], "max_per_hour": b.max_per_hour}


@router.post("/org/notification-rules/{rid}/test")
async def test_rule(rid: str, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Send me a sample through this rule's channels, so I can see how it arrives."""
    async with tenant_session(ctx.org_id) as conn:
        r = (await conn.execute(text("select * from app.notification_rules where id::text = :i and (owner_user is null or owner_user = :u)"),
                                {"i": rid, "u": ctx.principal.user_id})).mappings().first()
        if not r:
            raise HTTPException(404, "rule not found")
        me = next((p for p in await center._people(conn, ctx.org_id) if p["user_id"] == ctx.principal.user_id), None)
    if not me:
        raise HTTPException(409, "only members of this business can receive its notifications")
    label = center.CATALOGUE[r["event_type"]].label
    out = {}
    for ch in [c for c in r["channels"] if c != "in_app"]:
        why = await center._send(ch, me, ctx.org_id, f"Test: {r['name']}", f"This is how “{label}” will reach you.")
        out[ch] = "sent" if why is None else why
    return {"results": out}


# ---------- the bell ----------

@router.get("/org/notifications/inbox")
async def inbox(ctx: Annotated[OrgContext, Depends(current_org)], limit: Annotated[int, Query(ge=1, le=100)] = 30) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select id, event_type, title, body, link, status, critical, created_at, read_at from app.notifications
            where user_id = :u order by created_at desc limit :l"""), {"u": ctx.principal.user_id, "l": limit})).mappings().all()
        unread = (await conn.execute(text("select count(*) from app.notifications where user_id = :u and read_at is null"),
                                     {"u": ctx.principal.user_id})).scalar_one()
    return {"items": [dict(r) for r in rows], "unread": unread}


class ReadIn(BaseModel):
    ids: list[int] | None = None  # None: everything


@router.post("/org/notifications/inbox/read")
async def mark_read(b: ReadIn, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        n = (await conn.execute(text("""update app.notifications set read_at = now() where user_id = :u and read_at is null
            and (cast(:ids as bigint[]) is null or id = any(cast(:ids as bigint[])))"""), {"u": ctx.principal.user_id, "ids": b.ids})).rowcount
    return {"read": n}


# ---------- Agentry HQ: what went where ----------

@router.get("/hq/orgs/{org_id}/notifications-log")
async def delivery_log(org_id: str, _: Annotated[Principal, Depends(require_staff)], status: str | None = None,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    if status and not re.fullmatch(r"[a-z_]+", status):
        raise HTTPException(422, "bad status")
    async with tenant_session(org_id) as conn:
        rows = (await conn.execute(text("""select n.id, n.event_type, n.title, n.status, n.deliveries, n.created_at, n.sent_at, coalesce(u.name, u.email) as person
            from app.notifications n left join auth."user" u on u.id = n.user_id where (cast(:s as text) is null or n.status = :s)
            order by n.created_at desc limit :l"""), {"s": status, "l": limit})).mappings().all()
        counts = dict((await conn.execute(text("select status, count(*) from app.notifications where created_at > now() - interval '7 days' group by status"))).all())
    return {"items": [dict(r) for r in rows], "last_7_days": counts}


# ---------- Business Pulse (ROADMAP-V2 9.1) ----------

@router.get("/org/pulse")
async def get_pulse(ctx: Annotated[OrgContext, Depends(current_org)], period: Literal["daily", "weekly"] = "daily") -> dict:
    """Today's brief, worked out now (the plain opener: the model writes one only for the version that's sent)."""
    from agentry import pulse
    if not ctx.can("dashboard", "read"):
        raise HTTPException(403, "missing permission dashboard:read")
    b = await pulse.build(ctx.org_id, period, with_opener=False)
    async with tenant_session(ctx.org_id) as conn:
        profile = (await conn.execute(text("select profile from app.org_settings"))).scalar_one_or_none() or {}
    return {k: b[k] for k in ("period", "title", "opener", "items", "from", "to")} | {"settings": pulse.settings_of(profile),
                                                                                    "can_edit": ctx.can("automation", "configure")}


class PulseSettings(BaseModel):
    enabled: bool = True
    hour: Annotated[int, Field(ge=5, le=12)] = 8
    weekly: bool = True


@router.put("/org/pulse/settings")
async def pulse_settings(b: PulseSettings, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not ctx.can("automation", "configure"):
        raise HTTPException(403, "only owners and managers change the brief")
    async with tenant_session(ctx.org_id) as conn:
        await conn.execute(text("update app.org_settings set profile = profile || jsonb_build_object('pulse', cast(:p as jsonb))"),
                           {"p": json.dumps(b.model_dump())})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id, action="pulse.settings_changed",
                           target_type="org", target_id=ctx.org_id, ip=client_ip(request), metadata=b.model_dump())
    return b.model_dump()


@router.post("/org/pulse/send-now")
async def pulse_send_now(ctx: Annotated[OrgContext, Depends(current_org)], period: Literal["daily", "weekly"] = "daily") -> dict:
    """Send the brief now (to see how it arrives); it goes to whoever the Morning brief / Week in review rules say."""
    from agentry import pulse
    if not ctx.can("automation", "configure"):
        raise HTTPException(403, "only owners and managers send the brief")
    async with tenant_session(ctx.org_id) as conn:
        from agentry.notify.center import ensure_defaults
        await ensure_defaults(conn, ctx.org_id)
    return {"event_id": await pulse.send(ctx.org_id, period)}
