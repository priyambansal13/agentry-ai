"""Festival campaigns (ROADMAP-V3 B3): plans weeks ahead, never with an invented offer."""
from datetime import date

from sqlalchemy import text

from agentry.automations import festivals as fv
from agentry.db import tenant_session


def test_calendar_and_date_corrections():
    cfg = fv.FestivalConfig().model_dump()
    soon = fv.upcoming(cfg, date(2026, 10, 20), 21)
    assert [f["key"] for f in soon] == ["dussehra", "diwali"] and soon[1]["date"] == date(2026, 11, 8) and soon[1]["lunar"]
    cfg["festival_dates"] = {"diwali": "2026-11-09"}
    assert fv.upcoming(cfg, date(2026, 10, 20), 21)[1]["date"] == date(2026, 11, 9)  # the business's correction counts
    assert [f["key"] for f in fv.upcoming(cfg, date(2026, 12, 20), 14)] == ["christmas", "new_year"]  # crosses the year


def test_no_invented_offers():
    p = {"theme": "x", "whatsapp": "Happy Diwali! Flat 20% off all services.", "posts": [{"text": "a"}, {"text": "b"}]}
    assert any("isn't part of your offer" in x for x in fv.plan_problems(p, None))
    assert fv.plan_problems(p, "Flat 20% off all services till 10 Nov") == []


async def test_daily_plans_ahead_once(client, team_org):
    oid, h = await team_org(["festival_campaigns"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"offers": {"diwali": "Free AC check-up with every service till 10 Nov"}}'"""))
    assert await fv.daily(oid, date(2026, 10, 20)) == 2  # Dussehra (today) and Diwali
    assert await fv.daily(oid, date(2026, 10, 21)) == 0
    d = (await client.get("/org/festivals", headers=h["owner"])).json()
    diwali = next(p for p in d["plans"] if p["festival"] == "diwali")
    assert "Free AC check-up" in diwali["plan"]["whatsapp"] and diwali["status"] == "draft" and len(diwali["plan"]["posts"]) == 3
    assert (await client.patch(f"/org/festivals/plans/{diwali['id']}", headers=h["owner"], json={"status": "approved"})).json()["status"] == "approved"
    assert (await client.patch(f"/org/festivals/plans/{diwali['id']}", headers=h["staff"], json={"status": "done"})).status_code == 403
