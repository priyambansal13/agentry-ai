"""Client health (ROADMAP-V3 A7): a falling, absent or stuck client scores low with the reasons."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.client_health import assess
from agentry.db import tenant_session


async def test_a_quiet_client_with_stuck_cards_is_at_risk(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    old = datetime.now(UTC) - timedelta(days=20)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.org_settings set created_at = :d"), {"d": datetime.now(UTC) - timedelta(days=90)})
        for _ in range(30):  # busy two-to-four weeks ago, silent now
            await conn.execute(text("insert into app.events (org_id, type, payload, occurred_at) values (:o, 'email.triaged', '{}', :d)"), {"o": oid, "d": old})
        for _ in range(6):
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, created_at)
                values (:o, 'reply_draft', 'inbox_triage', 'x', :d)"""), {"o": oid, "d": datetime.now(UTC) - timedelta(days=5)})
    me = next(r for r in await assess() if r["org_id"] == oid)
    assert me["level"] == "at_risk" and me["score"] < 50
    assert any("activity fell" in x for x in me["reasons"]) and any("6 cards waiting" in x for x in me["reasons"])
    assert any("signed in" in x or "portal" in x for x in me["reasons"])
    r = await client.get("/hq/health", headers={"Authorization": h["agentry"]["Authorization"]})
    assert r.status_code == 200 and any(i["org_id"] == oid for i in r.json()["items"])
    assert (await client.get("/hq/health", headers=h["owner"])).status_code == 403
