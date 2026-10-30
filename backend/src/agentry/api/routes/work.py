"""Conversations, "Needs you" approvals, automation settings, email intake and the opportunity report."""
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentry import audit
from agentry.auth import OrgContext, client_ip, current_org, require
from agentry.automations import REGISTRY
from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.db import tenant_session
from agentry.events import emit
from agentry.features import enabled_automations
from agentry.outbound import channel_problem
from agentry.voice import recordings

router = APIRouter(prefix="/org", tags=["work"])
log = logging.getLogger("agentry.work")


# ---------- who may see / act on what ----------
# Invoice follow-up is money: its conversations and Needs-you cards follow the invoice permission (owner, manager,
# finance; viewers read only). Everything else follows the conversation permission (owner, manager, front desk).

def _resource(automation_key: str | None) -> str:
    return "invoice" if automation_key == "invoice_follow_up" else "conversation"


async def _allowed_keys_sql(ctx: OrgContext, action: str) -> str | None:
    """SQL filter on automation_key for what this person may `action`; None = everything; raises if nothing.
    The invoice permission only opens conversations and Needs you when the client has invoice follow-up."""
    if ctx.can("conversation", action):
        return None if ctx.can("invoice", action) else "coalesce(automation_key, '') <> 'invoice_follow_up'"
    if ctx.can("invoice", action):
        async with tenant_session(ctx.org_id) as conn:
            if "invoice_follow_up" in await enabled_automations(conn):
                return "automation_key = 'invoice_follow_up'"
    raise HTTPException(403, f"missing permission conversation:{action}")


def _check(ctx: OrgContext, automation_key: str | None, action: str) -> None:
    resource = _resource(automation_key)
    if not ctx.can(resource, action):
        raise HTTPException(403, f"missing permission {resource}:{action}")


# ---------- conversations ----------

@router.get("/conversations")
async def list_conversations(
    ctx: Annotated[OrgContext, Depends(current_org)],
    channel: str | None = None, category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    scope = await _allowed_keys_sql(ctx, "read")
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            select c.id, c.channel, c.automation_key, c.subject, c.status, c.last_message_at, c.metadata->'labels' as labels,
                   c.metadata #>> '{call,summary}' as call_summary,
                   k.name as contact_name, coalesce(k.email, first.metadata->>'from') as contact_email,
                   first.metadata->'triage' as triage, left(last.body, 160) as preview,
                   (select count(*) from app.messages m where m.conversation_id = c.id) as message_count
            from app.conversations c
            left join app.contacts k on k.id = c.contact_id
            left join lateral (select * from app.messages m where m.conversation_id = c.id order by created_at limit 1) first on true
            left join lateral (select * from app.messages m where m.conversation_id = c.id order by created_at desc limit 1) last on true
            where (cast(:ch as text) is null or c.channel = :ch)
              and (cast(:cat as text) is null or first.metadata #>> '{triage,category}' = :cat)
              and """ + (scope.replace("automation_key", "c.automation_key") if scope else "true") + """
            order by c.last_message_at desc limit :l"""), {"ch": channel, "cat": category, "l": limit})).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        conv = (await conn.execute(text("""select c.*, k.name as contact_name, k.email as contact_email, k.phone as contact_phone
            from app.conversations c left join app.contacts k on k.id = c.contact_id where c.id = :id"""),
            {"id": conversation_id})).mappings().first()
        if not conv:
            raise HTTPException(404, "conversation not found")
        _check(ctx, conv["automation_key"], "read")
        msgs = (await conn.execute(text("""select id, direction, author, body, metadata, created_at from app.messages
            where conversation_id = :id order by created_at"""), {"id": conversation_id})).mappings().all()
        approvals = (await conn.execute(text("""select id, kind, status, title, body, created_at from app.approvals
            where conversation_id = :id order by created_at desc"""), {"id": conversation_id})).mappings().all()
        bookings = (await conn.execute(text("""select b.starts_at, b.ends_at, b.status, s.name as service, st.name as staff
            from app.bookings b join app.services s on s.id = b.service_id join app.staff st on st.id = b.staff_id
            where b.conversation_id = :id"""), {"id": conversation_id})).mappings().all()
    return {"conversation": dict(conv), "messages": [dict(m) for m in msgs], "approvals": [dict(a) for a in approvals],
            "bookings": [dict(b) for b in bookings]}


@router.get("/conversations/{conversation_id}/recording")
async def recording(conversation_id: str, ctx: Annotated[OrgContext, Depends(current_org)]) -> FileResponse:
    """The call recording (stereo Ogg Opus), for the people allowed to read this conversation."""
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select automation_key, metadata->>'recording' as rec from app.conversations where id = cast(:c as uuid)"),
                                {"c": conversation_id})).first()
    if not c:
        raise HTTPException(404, "conversation not found")
    if not await _billing_evidence(ctx, conversation_id):
        _check(ctx, c.automation_key, "read")
    path = recordings.path_for(c.rec)
    if not path:
        raise HTTPException(404, "no recording for this conversation")
    return FileResponse(path, media_type="audio/ogg", filename=f"call-{conversation_id[:8]}.ogg")


async def _billing_evidence(ctx: OrgContext, conversation_id: str) -> bool:
    """People who check statements (finance) may play a call that is the evidence for a charge on one."""
    if not ctx.can("billing", "read"):
        return False
    async with tenant_session(ctx.org_id) as conn:
        return (await conn.execute(text("""select exists(select 1 from app.outcomes where statement_id is not null
            and evidence->>'conversation_id' = :c)"""), {"c": conversation_id})).scalar_one()


@router.delete("/conversations/{conversation_id}/recording")
async def delete_recording(conversation_id: str, request: Request,
                           ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Delete a call recording on request (the caller asked, or it holds something it shouldn't). Owner and manager.
    The transcript and summary stay."""
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select metadata->>'recording' as rec from app.conversations where id = cast(:c as uuid) and channel = 'voice'"),
                                {"c": conversation_id})).first()
        if not c or not c.rec:
            raise HTTPException(404, "no recording for this conversation")
        await recordings.remove(conn, conversation_id, c.rec, "deleted on request")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="recording.deleted", target_type="conversation", target_id=conversation_id, ip=client_ip(request))
    return {"deleted": True}


class Reply(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=20000)]


@router.post("/conversations/{conversation_id}/reply", status_code=201)
async def reply(conversation_id: str, r: Reply, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """A person replies in a conversation: the website visitor sees it in the chat window, WhatsApp and Gmail replies are
    sent from the business's own number or mailbox. Replying to a chat takes it over from the agent."""
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("select channel, status, automation_key from app.conversations where id = cast(:c as uuid)"),
                                {"c": conversation_id})).mappings().first()
        if not c:
            raise HTTPException(404, "conversation not found")
        _check(ctx, c["automation_key"], "act")
        mid = str((await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, :c, 'out', 'human', :b, jsonb_build_object('sent_by', jsonb_build_object('user_id', cast(:u as text),
                    'name', cast(:n as text), 'staff', cast(:st as boolean)))) returning id"""),
            {"o": ctx.org_id, "c": conversation_id, "b": r.body, "u": ctx.principal.user_id, "n": ctx.principal.name,
             "st": ctx.principal.is_staff})).scalar_one())
        # a person answered: drafts and hand-off requests for this conversation are done
        await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
            where conversation_id = cast(:c as uuid) and status = 'pending' and kind in ('reply_draft', 'handoff')"""),
            {"u": ctx.principal.user_id, "c": conversation_id})
        await conn.execute(text("""update app.conversations set last_message_at = now(),
            status = case when channel in ('web_chat', 'whatsapp', 'telegram') then 'handed_off' else status end where id = cast(:c as uuid)"""),
            {"c": conversation_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="conversation.replied", target_type="conversation", target_id=conversation_id, ip=client_ip(request))
        await emit(conn, ctx.org_id, "reply.created", {"message_id": mid, "conversation_id": conversation_id})
    return {"message_id": mid}


class ConversationStatus(BaseModel):
    status: Literal["open", "handed_off", "closed"]


@router.post("/conversations/{conversation_id}/status")
async def set_status(conversation_id: str, body: ConversationStatus, request: Request,
                     ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Take a chat over from the agent (handed_off), give it back (open), or close it."""
    async with tenant_session(ctx.org_id) as conn:
        key = (await conn.execute(text("select automation_key from app.conversations where id = cast(:c as uuid)"), {"c": conversation_id})).first()
        if not key:
            raise HTTPException(404, "conversation not found")
        _check(ctx, key[0], "act")
        done = (await conn.execute(text("update app.conversations set status = :s where id = cast(:c as uuid) returning id"),
                                   {"s": body.status, "c": conversation_id})).first()
        if not done:
            raise HTTPException(404, "conversation not found")
        if body.status != "handed_off":
            await conn.execute(text("""update app.approvals set status = 'resolved', decided_by = :u, decided_at = now()
                where conversation_id = cast(:c as uuid) and status = 'pending' and kind = 'handoff'"""),
                {"u": ctx.principal.user_id, "c": conversation_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action=f"conversation.{ {'open': 'returned_to_agent', 'handed_off': 'taken_over', 'closed': 'closed'}[body.status] }",
                           target_type="conversation", target_id=conversation_id, ip=client_ip(request))
    return {"status": body.status}


# ---------- Needs you ----------

@router.get("/approvals")
async def list_approvals(
    ctx: Annotated[OrgContext, Depends(current_org)],
    status: str = "pending", limit: Annotated[int, Query(ge=1, le=200)] = 50,
    view: Literal["now", "snoozed", "mine"] = "now",
) -> dict:
    """Needs you. "now": everything waiting (snoozed cards hidden until their time); "snoozed": only snoozed;
    "mine": assigned to me (plus unassigned)."""
    scope = await _allowed_keys_sql(ctx, "read")
    where = {"now": "(a.snoozed_until is null or a.snoozed_until <= now())",
             "snoozed": "a.snoozed_until > now()",
             "mine": "(a.snoozed_until is null or a.snoozed_until <= now()) and (a.assigned_to is null or a.assigned_to = :me)"}[view]
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            select a.id, a.kind, a.status, a.automation_key, a.conversation_id, a.title, a.body, a.payload, a.created_at,
                   a.snoozed_until, a.assigned_to, u.name as assigned_name,
                   c.channel, c.subject, c.metadata->>'mailbox' as mailbox,
                   (select body from app.messages m where m.conversation_id = a.conversation_id
                                          and m.direction = 'in' order by created_at desc limit 1) as last_inbound
            from app.approvals a left join app.conversations c on c.id = a.conversation_id
            left join auth."user" u on u.id = a.assigned_to
            where a.status = :s and """ + where + " and " + (scope.replace("automation_key", "a.automation_key") if scope else "true") + """
            order by coalesce((a.payload->>'urgent')::boolean, false) desc, a.created_at desc limit :l"""),
            {"s": status, "l": limit, "me": ctx.principal.user_id})).mappings().all()
        counts = dict((await conn.execute(text(
            "select kind, count(*) from app.approvals where status = 'pending' and (snoozed_until is null or snoozed_until <= now()) and "
            + (scope or "true") + " group by kind"))).all())
        snoozed = (await conn.execute(text("select count(*) from app.approvals where status = 'pending' and snoozed_until > now() and "
                                           + (scope or "true")))).scalar_one()
    items = [dict(r) for r in rows]
    problems: dict[tuple, str | None] = {}
    for it in items:  # an outbound card whose channel can't send (e.g. WhatsApp disconnected since it was made)
        if it["kind"] == "outbound_draft":
            key = (it["payload"].get("channel", ""), it["payload"].get("template"))
            if key not in problems:
                problems[key] = await channel_problem(ctx.org_id, *key)
            it["channel_problem"] = problems[key]
    return {"items": items, "pending_by_kind": counts, "snoozed": snoozed}


class Snooze(BaseModel):
    until: datetime | None  # None = wake now


@router.post("/approvals/{approval_id}/snooze")
async def snooze(approval_id: str, body: Snooze, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Hide a card until later (#11). A snoozed urgent email counts as seen: no escalation."""
    if body.until and body.until <= datetime.now(UTC):
        raise HTTPException(422, "choose a time in the future")
    if body.until and body.until > datetime.now(UTC) + timedelta(days=30):
        raise HTTPException(422, "snooze for at most 30 days")
    async with tenant_session(ctx.org_id) as conn:
        a = (await conn.execute(text("select automation_key, status from app.approvals where id = cast(:i as uuid)"),
                                {"i": approval_id})).mappings().first()
        if not a:
            raise HTTPException(404, "not found")
        _check(ctx, a["automation_key"], "act")
        if a["status"] != "pending":
            raise HTTPException(409, f"already {a['status']}")
        await conn.execute(text("update app.approvals set snoozed_until = :u where id = cast(:i as uuid)"), {"u": body.until, "i": approval_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="approval.snoozed" if body.until else "approval.unsnoozed", target_type="approval",
                           target_id=approval_id, ip=client_ip(request), metadata={"until": body.until.isoformat() if body.until else None})
    return {"id": approval_id, "snoozed_until": body.until}


class Recategorise(BaseModel):
    category: Annotated[str, Field(min_length=2, max_length=30)]


@router.post("/conversations/{conversation_id}/category")
async def recategorise(conversation_id: str, body: Recategorise, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Wrong label? (#8) Move the email to the right category: relabelled in Gmail, and remembered, so the next email
    from this sender (or, after two corrections, this domain) is filed there automatically."""
    from agentry.automations.inbox_triage.config import TriageConfig
    from agentry.connectors.mailbox import mailbox_for
    async with tenant_session(ctx.org_id) as conn:
        c = (await conn.execute(text("""select c.automation_key, m.id as message_id, m.metadata->>'from' as sender, c.subject,
                m.metadata->'triage'->>'category' as category, a.config
            from app.conversations c join app.messages m on m.conversation_id = c.id and m.direction = 'in'
            left join app.automation_instances a on a.template_key = 'inbox_triage'
            where c.id = cast(:c as uuid) and c.channel = 'email' and m.metadata ? 'triage'
            order by m.created_at desc limit 1"""), {"c": conversation_id})).mappings().first()
        if not c:
            raise HTTPException(404, "no sorted email in this conversation")
        _check(ctx, c["automation_key"], "act")
        cfg = TriageConfig(**(c["config"] or {}))
        if body.category not in [*cfg.categories, *cfg.custom_categories]:
            raise HTTPException(422, f"unknown category {body.category}")
        old = c["category"]
        if old == body.category:
            return {"category": old}
        sender = (c["sender"] or "").lower()
        await conn.execute(text("""update app.messages set metadata = jsonb_set(metadata, '{triage}', metadata->'triage' ||
            jsonb_build_object('category', cast(:n as text), 'original_category', coalesce(metadata->'triage'->>'original_category', cast(:o as text)),
                               'corrected_by', cast(:u as text))) where id = :m"""),
            {"n": body.category, "o": old, "u": ctx.principal.user_id, "m": c["message_id"]})
        await conn.execute(text("""insert into app.label_corrections (org_id, conversation_id, sender, sender_domain, subject, from_category,
            to_category, corrected_by) values (:o, cast(:c as uuid), :s, :d, :sub, :f, :t, :u)"""),
            {"o": ctx.org_id, "c": conversation_id, "s": sender, "d": sender.rsplit("@", 1)[-1], "sub": c["subject"],
             "f": old or "", "t": body.category, "u": ctx.principal.user_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="email.recategorised", target_type="conversation", target_id=conversation_id, ip=client_ip(request),
                           metadata={"from": old, "to": body.category})
    try:
        await (await mailbox_for(ctx.org_id, conversation_id)).relabel(ctx.org_id, conversation_id, [f"Agentry/{body.category}"],
                                                                       [f"Agentry/{old}"] if old else [])
    except Exception as e:  # noqa: BLE001 - Gmail unreachable: Agentry is updated, the Gmail label follows on the next change
        log.warning("relabel in mailbox failed for %s: %s", conversation_id, e)
    return {"category": body.category, "previous": old}


# ---------- assigning cards (#9) ----------

class Assign(BaseModel):
    user_id: str | None  # None = unassign


@router.get("/assignees")
async def assignees(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    """Team members who can work Needs-you cards, for the "Assign to" menu."""
    from agentry.permissions import can
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""select u.id, u.name, u.email, m.role from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o order by u.name"""), {"o": ctx.org_id})).mappings().all()
    return {"items": [{"id": r["id"], "name": r["name"] or r["email"], "role": r["role"],
                       "conversations": can(r["role"], "conversation", "act"), "invoices": can(r["role"], "invoice", "act")}
                      for r in rows if can(r["role"], "conversation", "act") or can(r["role"], "invoice", "act")]}


@router.post("/approvals/{approval_id}/assign")
async def assign(approval_id: str, body: Assign, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    from agentry.notify.email import send_email
    from agentry.permissions import can
    async with tenant_session(ctx.org_id) as conn:
        a = (await conn.execute(text("select automation_key, status, title from app.approvals where id = cast(:i as uuid)"),
                                {"i": approval_id})).mappings().first()
        if not a:
            raise HTTPException(404, "not found")
        _check(ctx, a["automation_key"], "act")
        who = None
        if body.user_id:
            who = (await conn.execute(text("""select u.name, u.email, m.role from auth.member m join auth."user" u on u.id = m."userId"
                where m."organizationId" = :o and u.id = :u"""), {"o": ctx.org_id, "u": body.user_id})).mappings().first()
            if not who or not can(who["role"], _resource(a["automation_key"]), "act"):
                raise HTTPException(422, "that person can't handle this card")
        await conn.execute(text("update app.approvals set assigned_to = :u, assigned_by = :by where id = cast(:i as uuid)"),
                           {"u": body.user_id, "by": ctx.principal.user_id, "i": approval_id})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="approval.assigned", target_type="approval", target_id=approval_id, ip=client_ip(request),
                           metadata={"to": body.user_id})
    if who and body.user_id != ctx.principal.user_id:
        from agentry.config import settings as cfg
        await asyncio.to_thread(send_email, who["email"], f"{ctx.principal.name or 'A teammate'} assigned you: {a['title']}",
                                f"It's waiting in your Needs you: {cfg.dashboard_url}/needs-you?view=mine")
    return {"id": approval_id, "assigned_to": body.user_id}


# ---------- auto-assign rules: every card for a client, or for an agent, goes to one person ----------

class Routing(BaseModel):
    scope: Literal["contact", "automation"]
    key: Annotated[str, Field(min_length=1, max_length=64)]  # contact id or automation key
    assign_to: str | None  # None = remove the rule


async def _routing_rules(conn) -> list[dict]:
    rows = (await conn.execute(text("""select r.scope, r.key, r.assign_to, r.resources, u.name as assign_name,
            case when r.scope = 'contact' then coalesce(k.company, k.name) end as contact_name
        from app.card_routing r left join auth."user" u on u.id = r.assign_to
        left join app.contacts k on r.scope = 'contact' and k.id::text = r.key order by r.scope, r.key"""))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/card-routing")
async def card_routing(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        return {"items": await _routing_rules(conn)}


@router.put("/card-routing")
async def set_card_routing(body: Routing, request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Set or remove a rule. Waiting cards that a rule placed, or that nobody has, follow the rules as they now stand;
    hand-assigned cards are never touched."""
    from agentry.permissions import can
    async with tenant_session(ctx.org_id) as conn:
        enabled = set((await conn.execute(text("select template_key from app.automation_instances"))).scalars())
        if body.scope == "automation":
            if body.key not in enabled:
                raise HTTPException(404, "that agent isn't switched on for this business")
            needs = {_resource(body.key)}
        else:
            if not (await conn.execute(text("select 1 from app.contacts where id::text = :k"), {"k": body.key})).first():
                raise HTTPException(404, "contact not found")
            needs = {_resource(k) for k in enabled}  # a client's cards can come from any of the business's agents
        if body.assign_to:
            role = (await conn.execute(text("""select m.role from auth.member m where m."organizationId" = :o and m."userId" = :u"""),
                                       {"o": ctx.org_id, "u": body.assign_to})).scalar_one_or_none()
            covers = sorted(r for r in needs if role and can(role, r, "act"))
            # an agent rule needs someone who can work that agent's cards; a client rule covers the kinds they can work
            if not covers or (body.scope == "automation" and len(covers) < len(needs)):
                raise HTTPException(422, "that person can't handle these cards")
            await conn.execute(text("""insert into app.card_routing (org_id, scope, key, assign_to, resources, set_by)
                values (:o, :s, :k, :u, :res, :by)
                on conflict (org_id, scope, key) do update set assign_to = excluded.assign_to, resources = excluded.resources,
                  set_by = excluded.set_by, created_at = now()"""),
                               {"o": ctx.org_id, "s": body.scope, "k": body.key, "u": body.assign_to, "res": covers, "by": ctx.principal.user_id})
        else:
            await conn.execute(text("delete from app.card_routing where scope = :s and key = :k"), {"s": body.scope, "k": body.key})
        # every waiting card that a rule placed (or nobody has) is decided again, so a new client rule beats an
        # earlier agent-wide one; cards someone assigned by hand stay where they are
        moved = (await conn.execute(text("""
            with decided as (select id, app.card_assignee(payload, conversation_id, automation_key) as who from app.approvals
                             where status = 'pending' and (assigned_by = 'rule' or assigned_to is null))
            update app.approvals a set assigned_to = d.who, assigned_by = case when d.who is null then null else 'rule' end
            from decided d where a.id = d.id and a.assigned_to is distinct from d.who
            returning d.who"""))).scalars().all()
        moved = sum(1 for w in moved if w)
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="card_routing.set" if body.assign_to else "card_routing.removed", target_type=body.scope,
                           target_id=body.key, ip=client_ip(request), metadata={"to": body.assign_to, "cards_assigned": moved})
        return {"items": await _routing_rules(conn), "cards_assigned": moved}


# ---------- saved replies (#12) ----------

class Template(BaseModel):
    title: Annotated[str, Field(min_length=2, max_length=80)]
    body: Annotated[str, Field(min_length=2, max_length=5000)]


@router.get("/reply-templates")
async def list_templates(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    if not (ctx.can("conversation", "act") or ctx.can("invoice", "act")):  # for the people who reply (finance: invoice emails)
        raise HTTPException(403, "missing permission conversation:act")
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("select id, title, body, updated_at from app.reply_templates order by title"))).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/reply-templates", status_code=201)
async def save_template(t: Template, request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Add or update (by title) a saved reply. The AI also uses them when drafting."""
    async with tenant_session(ctx.org_id) as conn:
        tid = str((await conn.execute(text("""insert into app.reply_templates (org_id, title, body, created_by) values (:o, :t, :b, :u)
            on conflict (org_id, title) do update set body = excluded.body, updated_at = now() returning id"""),
            {"o": ctx.org_id, "t": t.title.strip(), "b": t.body, "u": ctx.principal.user_id})).scalar_one())
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="reply_template.saved", target_type="reply_template", target_id=tid, ip=client_ip(request))
    return {"id": tid}


@router.put("/reply-templates/{template_id}")
async def update_template(template_id: str, t: Template, request: Request,
                          ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        try:
            done = (await conn.execute(text("""update app.reply_templates set title = :t, body = :b, updated_at = now()
                where id = cast(:i as uuid) returning id"""), {"t": t.title.strip(), "b": t.body, "i": template_id})).first()
        except IntegrityError as e:
            raise HTTPException(409, "another saved reply already has this title") from e
        if not done:
            raise HTTPException(404, "not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="reply_template.saved", target_type="reply_template", target_id=template_id, ip=client_ip(request))
    return {"id": template_id}


@router.delete("/reply-templates/{template_id}")
async def delete_template(template_id: str, request: Request, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        gone = (await conn.execute(text("delete from app.reply_templates where id = cast(:i as uuid) returning id"), {"i": template_id})).first()
        if not gone:
            raise HTTPException(404, "not found")
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="reply_template.deleted", target_type="reply_template", target_id=template_id, ip=client_ip(request))
    return {"deleted": True}


# ---------- writing style (#1) ----------

@router.post("/inbox/learn-style")
async def relearn_style(ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    """Read the business's recent sent emails again and refresh the style guide drafts follow."""
    from agentry.automations.inbox_triage.style import learn_style
    async with tenant_session(ctx.org_id) as conn:
        if not (await conn.execute(text("select exists(select 1 from app.connections where provider = 'gmail' and status = 'connected')"))).scalar_one():
            raise HTTPException(409, "connect Gmail first: the style is learned from emails you sent")
    r = await learn_style(ctx.org_id)
    async with tenant_session(ctx.org_id) as conn:
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="inbox.style_learned", metadata={"samples": r["samples"], "learned": r["learned"]})
    return r


# ---------- inbox insights (#17, #18) ----------

@router.get("/inbox/insights")
async def inbox_insights(ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    from agentry.automations.inbox_triage.insights import insights
    if not ctx.can("dashboard", "read"):
        raise HTTPException(403, "missing permission dashboard:read")
    async with tenant_session(ctx.org_id) as conn:
        if "inbox_triage" not in await enabled_automations(conn):
            raise HTTPException(404, "inbox triage is not part of this client's plan")
        style = (await conn.execute(text("""select profile->>'writing_style' as guide, profile->>'writing_style_learned_at' as learned_at,
            (profile->>'writing_style_samples')::int as samples from app.org_settings"""))).mappings().first()
        return await insights(conn) | {"writing_style": dict(style) if style and style["guide"] else None}


class Decision(BaseModel):
    action: Literal["approve", "reject", "resolve"]
    body: Annotated[str | None, Field(max_length=20000)] = None  # edited text, if changed


@router.post("/approvals/{approval_id}")
async def decide(approval_id: str, d: Decision, request: Request, ctx: Annotated[OrgContext, Depends(current_org)]) -> dict:
    from agentry.approvals import CardError
    from agentry.approvals import decide as decide_card
    async with tenant_session(ctx.org_id) as conn:
        try:
            status = await decide_card(conn, ctx.org_id, approval_id, d.action, d.body, user_id=ctx.principal.user_id, name=ctx.principal.name,
                                       is_staff=ctx.principal.is_staff, actor_type=ctx.actor_type,
                                       can_act=lambda r: ctx.can(r, "act"), ip=client_ip(request))
        except CardError as e:
            raise HTTPException(e.status, str(e)) from e
    return {"id": approval_id, "status": status}


# ---------- automations: settings from each template's schema ----------

def _schema(key: str) -> dict | None:
    t = REGISTRY.get(key)
    return t.config_model.model_json_schema() if t else None


@router.get("/automations")
async def list_automations(ctx: Annotated[OrgContext, Depends(require("automation", "read"))]) -> dict:
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text(
            "select id, template_key, status, config, created_at, updated_at from app.automation_instances order by template_key"
        ))).mappings().all()
    items = []
    for r in rows:
        t = REGISTRY.get(r["template_key"])
        cfg = t.config_model(**(r["config"] or {})).model_dump(mode="json") if t else r["config"]
        items.append(dict(r) | {"config": cfg, "name": t.name if t else r["template_key"],
                                "description": t.description if t else None, "metrics": list(t.metrics) if t else [],
                                "config_schema": _schema(r["template_key"])})
    return {"items": items}


@router.patch("/automations/{key}/config")
async def update_config(key: str, changes: dict[str, Any], request: Request,
                        ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    t = REGISTRY.get(key)
    if not t:
        raise HTTPException(404, "unknown automation")
    props = t.config_model.model_json_schema().get("properties", {})
    if not ctx.principal.is_staff:
        locked = [k for k in changes if props.get(k, {}).get("editable_by") != "client"]
        if locked:
            raise HTTPException(403, f"managed by Agentry, request a change: {', '.join(locked)}")
    async with tenant_session(ctx.org_id) as conn:
        current = (await conn.execute(text("select config from app.automation_instances where template_key = :k for update"),
                                      {"k": key})).scalar_one_or_none()
        if current is None:
            raise HTTPException(404, "automation not installed")
        try:
            merged = t.config_model(**{**current, **changes}).model_dump(mode="json")
        except ValidationError as e:
            raise HTTPException(422, json.loads(e.json())) from e
        await conn.execute(text("update app.automation_instances set config = cast(:c as jsonb), updated_at = now() where template_key = :k"),
                           {"c": json.dumps(merged), "k": key})
        await audit.record(conn, org_id=ctx.org_id, actor_type=ctx.actor_type, actor_user_id=ctx.principal.user_id,
                           action="automation.configured", target_type="automation", target_id=key,
                           metadata={"changed": sorted(changes)}, ip=client_ip(request))
    return {"template_key": key, "config": merged}


# ---------- email intake (local mailbox; Gmail push will call the same ingest) ----------

class IncomingEmail(BaseModel):
    sender: EmailStr
    subject: Annotated[str, Field(max_length=500)] = ""
    body: Annotated[str, Field(max_length=100_000)]
    thread_ref: Annotated[str | None, Field(max_length=200)] = None


@router.post("/inbox/emails", status_code=201)
async def receive_email(e: IncomingEmail, ctx: Annotated[OrgContext, Depends(require("automation", "configure"))]) -> dict:
    ref = e.thread_ref or f"local-{datetime.now(UTC).timestamp()}"
    return {"message_id": await ingest_email(ctx.org_id, sender=e.sender, subject=e.subject, body=e.body, thread_ref=ref)}


# ---------- opportunity report (the upsell pitch, docs/PRICING.md §4) ----------

@router.get("/reports/opportunity")
async def opportunity_report(
    ctx: Annotated[OrgContext, Depends(require("dashboard", "read"))],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    close_rate: Annotated[float, Query(gt=0, le=1)] = 0.2,
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    async with tenant_session(ctx.org_id) as conn:
        rows = (await conn.execute(text("""
            with inbound as (
              select distinct on (m.conversation_id) m.conversation_id, m.created_at, m.metadata->'triage' as t
              from app.messages m join app.conversations c on c.id = m.conversation_id
              where c.channel = 'email' and m.direction = 'in' and m.created_at >= :since and m.metadata ? 'triage'
              order by m.conversation_id, m.created_at)
            select i.t->>'category' as category, (i.t->>'urgent')::boolean as urgent,
                   (i.t #>> '{entities,amount}') as amount,
                   extract(epoch from (select min(o.created_at) from app.messages o where o.conversation_id = i.conversation_id
                                       and o.direction = 'out' and o.created_at > i.created_at) - i.created_at) / 3600 as reply_hours
            from inbound i"""), {"since": since})).mappings().all()
        profile = (await conn.execute(text("select currency, profile from app.org_settings"))).mappings().first()
    leads = [r for r in rows if r["category"] == "Lead"]
    never = sum(1 for r in leads if r["reply_hours"] is None)
    late = sum(1 for r in leads if r["reply_hours"] is not None and r["reply_hours"] > 24)
    invoice = [r for r in rows if r["category"] == "Invoice/Payment"]
    mentioned = sum(float(r["amount"]) for r in invoice if r["amount"] not in (None, "", "null"))
    value = float(((profile or {}).get("profile") or {}).get("customer_value") or 0)
    replied = [r["reply_hours"] for r in rows if r["reply_hours"] is not None]
    return {
        "days": days, "currency": (profile or {}).get("currency"),
        "emails_triaged": len(rows), "urgent": sum(1 for r in rows if r["urgent"]),
        "enquiries": len(leads), "enquiries_never_answered": never, "enquiries_answered_after_24h": late,
        "invoice_emails": len(invoice), "amount_mentioned_in_invoice_emails": mentioned,
        "median_reply_hours": sorted(replied)[len(replied) // 2] if replied else None,
        "revenue_at_risk": (never * close_rate * value) if value else None,
        "method": f"unanswered enquiries x {close_rate:.0%} close rate x customer value"
                  + ("" if value else " (set the customer value in the business profile to estimate this)"),
    }
