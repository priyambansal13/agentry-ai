"""Onboarding reminders: stalled clients get a specific nudge (to the people who can do the setup), at most every 3
days; ops get the list; clients making progress are left alone."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry import onboarding_nudges as nudges
from agentry.db import tenant_session


async def test_stalled_client_is_nudged_once(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"], live=False)
    sent = []
    monkeypatch.setattr(nudges, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    now = datetime.now(UTC)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.org_settings set created_at = :t"), {"t": now - timedelta(days=6)})
        await conn.execute(text("update app.onboarding_progress set status = 'done', updated_at = :t where step_key = 'profile'"),
                           {"t": now - timedelta(days=4)})
    r = await nudges.run_daily(now)
    mine = [s for s in sent if "@team.example" in s[0]]
    assert sorted(to.split("-")[0] for to, _, _ in mine) == ["manager", "owner"]  # only people who can do the setup
    subject, body = mine[0][1], mine[0][2]
    assert subject == "7 steps to go live with Agentry" and "Next step: check your plan" in body and "/onboarding?step=plan" in body
    assert any("stuck in onboarding" in s[1] for s in sent)  # ops list
    assert r["stalled"] >= 1
    sent.clear()
    await nudges.run_daily(now + timedelta(days=1))  # not again within 3 days
    assert not [s for s in sent if "@team.example" in s[0]]
    async with tenant_session(oid) as conn:  # progress today: no longer stalled
        await conn.execute(text("update app.onboarding_progress set status = 'done', updated_at = :t where step_key = 'plan'"),
                           {"t": now + timedelta(days=4)})
    sent.clear()
    await nudges.run_daily(now + timedelta(days=5))
    assert not [s for s in sent if "@team.example" in s[0]]
