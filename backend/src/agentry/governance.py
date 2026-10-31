"""Governance (ROADMAP-V2 §2.2): how much each action may do on its own, within which limits, and what the record says.

Levels, per business and action:
    shadow        the agent works it out and records what it would have done; nothing is sent, nobody is asked
    recommend     a Needs-you card (a person decides)                               <- the default for new actions
    auto_limited  it acts on its own within the limits (per day, not in quiet hours); beyond them it falls back to a card
    auto          it acts on its own (limits still apply)

Until an owner chooses, the level follows what the business already had (an agent in approval mode = recommend, live
= auto_limited), so nothing changes on day one. The track record (cards approved as written) suggests when to give an
action more freedom; only an owner can.
"""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

LEVELS = ("shadow", "recommend", "auto_limited", "auto")
QUIET = (time(21, 0), time(8, 0))  # customer-facing messages the business starts never go out at night


@dataclass(frozen=True)
class Action:
    label: str
    agent: str
    card_kind: str  # the Needs-you cards whose record counts for this action
    customer_facing: bool
    default_limits: dict
    levels: tuple[str, ...] = LEVELS
    fixed_default: str | None = None  # a default that doesn't follow the agent's approval/live switch


ACTIONS: dict[str, Action] = {
    "invoice_follow_up.send": Action("Send payment reminders", "invoice_follow_up", "outbound_draft", True, {"max_per_day": 50, "quiet_hours": True}),
    "lead_reactivation.send": Action("Send win-back messages to old leads", "lead_reactivation", "outbound_draft", True,
                                     {"max_per_day": 100, "quiet_hours": True}),
    "speed_to_lead.send": Action("Message new leads within a minute", "speed_to_lead", "outbound_draft", True, {"max_per_day": 100, "quiet_hours": False}),
    "inbox_triage.send_reply": Action("Send email replies without review (trusted categories)", "inbox_triage", "reply_draft", True,
                                      {"max_per_day": 20, "quiet_hours": False}),
    # each first line is approved by a person and the campaign is started by one: sending itself has no card
    "cold_email.send": Action("Send cold emails (after you approve the lines)", "cold_email", "", True, {"max_per_day": 150, "quiet_hours": False},
                              levels=("shadow", "auto_limited", "auto"), fixed_default="auto_limited"),
}


@dataclass
class Decision:
    mode: str  # send | card | shadow
    level: str
    reason: str = ""


async def _setting(conn: AsyncConnection, action: str) -> tuple[str, dict, bool]:
    """(level, limits, chosen by an owner?)"""
    a = ACTIONS[action]
    row = (await conn.execute(text("select level, limits from app.autonomy where action = :a"), {"a": action})).first()
    if row:
        return row.level, {**a.default_limits, **(row.limits or {})}, True
    if a.fixed_default:
        return a.fixed_default, dict(a.default_limits), False
    status = (await conn.execute(text("select status from app.automation_instances where template_key = :k"), {"k": a.agent})).scalar_one_or_none()
    return ("auto_limited" if status == "live" else "recommend"), dict(a.default_limits), False


def is_quiet(now: datetime, tz: str) -> bool:
    t = now.astimezone(ZoneInfo(tz or "Asia/Kolkata")).time()
    return t >= QUIET[0] or t < QUIET[1]


_quiet = is_quiet  # what decide() calls (tests pin it to daytime)


async def decide(conn: AsyncConnection, org_id: str, action: str, now: datetime | None = None, *, count: bool = True) -> Decision:
    """Should this action go out on its own now? Counts it toward today's limit when the answer is send (count=True)."""
    now = now or datetime.now(UTC)
    level, limits, _ = await _setting(conn, action)
    if level == "shadow":
        return Decision("shadow", level, "watching only: recorded, not sent")
    if level == "recommend":
        return Decision("card", level)
    tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
    if limits.get("quiet_hours") and ACTIONS[action].customer_facing and _quiet(now, tz):
        return Decision("card", level, "quiet hours (9 pm to 8 am): waiting for a person instead of sending at night")
    day = now.astimezone(ZoneInfo(tz)).date()
    used = (await conn.execute(text("select n from app.action_counts where action = :a and day = :d"), {"a": action, "d": day})).scalar_one_or_none() or 0
    cap = limits.get("max_per_day")
    if cap is not None and used >= int(cap):
        return Decision("card", level, f"today's limit of {cap} reached: the rest wait for a person")
    if count:
        await conn.execute(text("""insert into app.action_counts (org_id, action, day, n) values (:o, :a, :d, 1)
            on conflict (org_id, action, day) do update set n = app.action_counts.n + 1"""), {"o": org_id, "a": action, "d": day})
    return Decision("send", level)


async def record(conn: AsyncConnection, action: str, days: int = 30) -> dict:
    """The track record behind a suggestion: cards for this action decided in the last `days`."""
    a = ACTIONS[action]
    if not a.card_kind:
        return {"decided": 0, "as_written": 0, "edited": 0, "rejected": 0, "rate": None}
    r = (await conn.execute(text("""select count(*) filter (where status in ('approved','edited','rejected')) as decided,
            count(*) filter (where status = 'approved') as as_written, count(*) filter (where status = 'edited') as edited,
            count(*) filter (where status = 'rejected') as rejected
        from app.approvals where kind = :k and automation_key = :ag and decided_at > now() - make_interval(days => :d)
          and decided_by is not null"""), {"k": a.card_kind, "ag": a.agent, "d": days})).mappings().one()
    out = dict(r)
    out["rate"] = round(out["as_written"] / out["decided"], 2) if out["decided"] else None
    return out


def suggestion(level: str, rec: dict) -> str | None:
    """More freedom only on a solid record; less when people keep changing or discarding drafts."""
    if level == "recommend" and rec["decided"] >= 20 and (rec["rate"] or 0) >= 0.9:
        return f"{rec['as_written']} of the last {rec['decided']} were approved as written: you could let it act on its own within limits."
    if level in ("auto_limited", "auto") and rec["decided"] >= 10 and (rec["rate"] or 1) < 0.6:
        return "People changed or discarded many of these recently: consider asking for approval again."
    return None


async def overview(conn: AsyncConnection, automations: list[str]) -> list[dict]:
    out = []
    for key, a in ACTIONS.items():
        if a.agent not in automations:
            continue
        level, limits, chosen = await _setting(conn, key)
        rec = await record(conn, key)
        out.append({"action": key, "label": a.label, "agent": a.agent, "level": level, "levels": list(a.levels), "limits": limits, "chosen": chosen,
                    "record": rec, "suggestion": suggestion(level, rec), "customer_facing": a.customer_facing})
    return out


async def set_level(conn: AsyncConnection, org_id: str, action: str, level: str, limits: dict, user_id: str | None) -> None:
    if action not in ACTIONS or level not in ACTIONS[action].levels:
        raise ValueError("that level isn't available for this action")
    await conn.execute(text("""insert into app.autonomy (org_id, action, level, limits, updated_by) values (:o, :a, :l, cast(:lim as jsonb), :u)
        on conflict (org_id, action) do update set level = excluded.level, limits = excluded.limits, updated_by = excluded.updated_by, updated_at = now()"""),
        {"o": org_id, "a": action, "l": level, "lim": json.dumps(limits), "u": user_id})
