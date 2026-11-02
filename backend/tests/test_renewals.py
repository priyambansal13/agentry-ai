"""Renewals & repeat business (ROADMAP-V3 A4): reminders before, win-back after, birthdays, the next cycle."""
from datetime import date

from sqlalchemy import text

from agentry.automations import renewals as rn
from agentry.db import tenant_session

SHEET = (b"Customer,Mobile,Email,Plan,Renewal date,Amount,Frequency,Date of birth\n"
         b"Anita Desai,+91 98100 00051,anita@example.com,AC AMC (2 units),15/11/2026,3500,yearly,05/11/1988\n"
         b"Rohit Jain,+91 98100 00052,,Gym membership,01/10/2026,6000,quarterly,\n"
         b"Bad row,,,,,,,\n")


async def _org(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(["renewals"])
    r = await client.post("/org/renewals/import", headers=h["manager"], files={"file": ("renewals.csv", SHEET, "text/csv")})
    assert r.json() == {"added": 2, "skipped_rows": [4]}
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append((who["contact_name"], body))
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    return oid, h, sent


async def test_reminders_once_per_offset_then_renewed(client, team_org, monkeypatch):
    oid, h, sent = await _org(client, team_org, monkeypatch)
    out = await rn.daily(oid, date(2026, 10, 16))  # 30 days before Anita's AMC; Rohit lapsed 15 days ago
    assert out["reminders"] == 1 and out["lapsed"] == 1 and out["winbacks"] == 1
    anita = next(b for n, b in sent if n == "Anita Desai")
    assert "AC AMC (2 units) (₹3,500) is due for renewal on 15 Nov" in anita
    assert "lapsed on 01 Oct" in next(b for n, b in sent if n == "Rohit Jain")
    assert (await rn.daily(oid, date(2026, 10, 20)))["reminders"] == 0       # not again until 7 days before
    assert (await rn.daily(oid, date(2026, 11, 8)))["reminders"] == 1        # 7 days
    assert (await rn.daily(oid, date(2026, 11, 14)))["reminders"] == 1       # 1 day: "tomorrow"
    assert "due for renewal tomorrow" in sent[-1][1]
    items = (await client.get("/org/renewals", headers=h["staff"])).json()["items"]
    aid = next(i["id"] for i in items if i["customer"] == "Anita Desai")
    assert (await client.post(f"/org/renewals/{aid}/mark", headers=h["staff"], json={"action": "renewed"})).status_code == 200
    a = next(i for i in (await client.get("/org/renewals", headers=h["owner"])).json()["items"] if i["id"] == aid)
    assert a["due_on"] == "2027-11-15" and a["reminded"] == [] and a["status"] == "upcoming" and a["renewals"] == 1
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.events where type = 'renewal.won'"))).scalar_one() == 1


async def test_birthday_once_a_year(client, team_org, monkeypatch):
    oid, _h, sent = await _org(client, team_org, monkeypatch)
    assert (await rn.daily(oid, date(2026, 11, 5)))["birthdays"] == 1
    assert sent[-1][1].startswith("Happy birthday, Anita!")
    assert (await rn.daily(oid, date(2026, 11, 5)))["birthdays"] == 0


async def test_approval_mode_sends_nothing(client, team_org, monkeypatch):
    oid, _h, sent = await _org(client, team_org, monkeypatch)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    out = await rn.daily(oid, date(2026, 10, 16))
    assert out["reminders"] == 0 and out["lapsed"] == 1 and sent == []


def test_cycles():
    assert rn.next_due(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
    assert rn.next_due(date(2026, 11, 15), "half_yearly") == date(2027, 5, 15)
    assert rn.next_due(date(2026, 11, 15), "once") is None
