"""Onboarding reminders: a client that stalls while setting up gets a short, specific nudge; Agentry ops get the list.

Daily at 10:00 IST. A client is stalled when it is still onboarding, is at least 2 days old, and no step moved for 3 days.
Each client is nudged at most every 3 days (org_settings.profile.last_nudge_at). Recipients: members who can do the
setup (automation:configure = owners and managers).
"""
import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.features import org_features
from agentry.notify.email import send_email
from agentry.permissions import can

STALL_DAYS = 3
STEP_TITLES = {"profile": "add your business details", "plan": "check your plan", "team": "invite your team",
               "connect": "connect your accounts", "import": "send us your data to import", "knowledge": "add what your agents should know",
               "settings": "review the automation settings", "persona": "set your assistant's name and tone",
               "compliance": "confirm the compliance points", "test": "test your agent", "go_live": "go live"}


async def stalled_clients(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    async with system_session() as conn:
        rows = (await conn.execute(text("""
            select s.org_id, o.name, s.created_at, s.profile->>'last_nudge_at' as last_nudge,
                   (select max(p.updated_at) from app.onboarding_progress p where p.org_id = s.org_id and p.status <> 'todo') as last_progress,
                   (select string_agg(p.blocker, '; ') from app.onboarding_progress p where p.org_id = s.org_id and p.status = 'blocked') as blockers
            from app.org_settings s join auth.organization o on o.id = s.org_id
            where s.status = 'onboarding' and s.created_at < :young"""), {"young": now - timedelta(days=2)})).mappings().all()
    out = []
    for r in rows:
        last = r["last_progress"] or r["created_at"]
        if now - last < timedelta(days=STALL_DAYS):
            continue
        out.append(dict(r) | {"idle_days": (now - last).days})
    return out


async def nudge(org: dict, now: datetime | None = None) -> int:
    """Email this client's setup people about their next step. Returns emails sent (0 if nudged recently)."""
    now = now or datetime.now(UTC)
    if org["last_nudge"] and now - datetime.fromisoformat(org["last_nudge"]) < timedelta(days=STALL_DAYS):
        return 0
    async with tenant_session(org["org_id"]) as conn:
        steps = (await org_features(conn))["steps"]
        done = set((await conn.execute(text("select step_key from app.onboarding_progress where status in ('done', 'skipped')"))).scalars())
    remaining = [s for s in steps if s not in done]
    if not remaining:
        return 0
    async with system_session() as conn:
        people = (await conn.execute(text("""select u.email, u.name, m.role from auth.member m join auth."user" u on u.id = m."userId"
            where m."organizationId" = :o"""), {"o": org["org_id"]})).all()
    to = [p for p in people if can(p.role, "automation", "configure")]
    nxt = remaining[0]
    body = (f"You're {len(remaining)} step{'s' if len(remaining) != 1 else ''} away from having your Agentry agents live for {org['name']}.\n\n"
            f"Next step: {STEP_TITLES.get(nxt, nxt)}.\n{settings.dashboard_url}/onboarding?step={nxt}\n\n"
            "Stuck, or would you rather we did it for you? Just reply to this email: every step can be done by your Agentry team.")
    for p in to:
        greeting = f"Hi {p.name.split(' ')[0]},\n\n" if p.name else ""
        await asyncio.to_thread(send_email, p.email, f"{len(remaining)} steps to go live with Agentry", greeting + body)
    async with tenant_session(org["org_id"]) as conn:
        await conn.execute(text("update app.org_settings set profile = profile || cast(:p as jsonb)"),
                           {"p": json.dumps({"last_nudge_at": now.isoformat()})})
    return len(to)


async def run_daily(now: datetime | None = None) -> dict:
    stalled = await stalled_clients(now)
    sent = 0
    for org in stalled:
        sent += await nudge(org, now)
    if stalled:  # one line per stuck client for Agentry ops
        lines = [f"- {o['name']}: no progress for {o['idle_days']} days" + (f" (blocked: {o['blockers']})" if o["blockers"] else "")
                 for o in stalled]
        await asyncio.to_thread(send_email, settings.ops_email, f"[Agentry] {len(stalled)} client(s) stuck in onboarding",
                                "\n".join(lines) + f"\n\nHQ: {settings.dashboard_url}/hq")
    return {"stalled": len(stalled), "reminders": sent}
