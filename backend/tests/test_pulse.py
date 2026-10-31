"""Business Pulse: the morning brief's numbers and order come from code, the opener can't invent numbers, it's due
once a day at each business's hour (Mondays add the week), and it reaches the owner through the Notification Center."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from conftest import expect
from sqlalchemy import text
from test_invoice_e2e import go_live_invoice_client

from agentry import pulse
from agentry.db import tenant_session
from agentry.notify import alerts, center

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
IST = ZoneInfo("Asia/Kolkata")


def test_indian_money_format():
    assert [pulse._money(v) for v in (950, 41250, 250000, 12345678)] == ["₹950", "₹41,250", "₹2,50,000", "₹1,23,45,678"]
    assert pulse._money(1200, "USD") == "USD 1,200"


async def busy_invoice_client(client, team_org):
    """Two overdue invoices, a payment yesterday and a card nobody has touched for 5 hours."""
    oid, h = await go_live_invoice_client(client, team_org)
    async with tenant_session(oid) as conn:
        from agentry.invoices import apply_payment
        inv = (await conn.execute(text("select id::text from app.invoices where number = 'E-1'"))).scalar_one()
        await apply_payment(conn, oid, invoice_id=inv, amount=12000, currency="INR", gateway="razorpay", reference="pay_y1", match="strong")
        await conn.execute(text("update app.payments set received_at = now() - interval '20 hours' where reference = 'pay_y1'"))
        await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, created_at)
            values (:o, 'escalation', 'invoice_follow_up', 'Call Rohan about E-2', 'x', now() - interval '5 hours')"""), {"o": oid})
    return oid, h


async def test_brief_ranks_what_needs_doing_then_good_news(client, team_org):
    oid, _h = await busy_invoice_client(client, team_org)
    b = await pulse.build(oid, "daily", with_opener=False)
    kinds = [i["kind"] for i in b["items"]]
    assert kinds == ["do", "do", "good"]
    assert b["items"][0]["text"] == "1 card waiting over 4 hours" and b["items"][0]["link"] == "/needs-you"
    assert b["items"][1]["text"].startswith("₹78,000 overdue across 2 invoices; biggest: E-")  # 45,000 + 45,000 - 12,000 paid
    assert b["items"][2]["text"] == "₹12,000 received (1 payment)"
    assert b["title"] == "Morning brief: 2 to do" and "Needs you:" in b["body"] and "Yesterday: ₹12,000 received" in b["body"]
    assert "leads" not in b["facts"] and "calls" not in b["facts"]  # only what this business has


async def test_opener_never_invents_numbers(client, team_org, monkeypatch):
    oid, _h = await busy_invoice_client(client, team_org)

    def says(line):
        async def fake(tier, messages, **kw):
            return SimpleNamespace(text=line, data=None, mock=False)
        monkeypatch.setattr(pulse, "complete", fake)
    says("Good morning Owner, ₹78,000 is overdue and 1 card is waiting.")
    assert (await pulse.build(oid, "daily"))["opener"] == "Good morning Owner, ₹78,000 is overdue and 1 card is waiting."
    says("Good morning, you made ₹5,00,000 yesterday.")
    assert (await pulse.build(oid, "daily"))["opener"] == "Good morning, Owner: 2 things need you today."


async def test_due_once_a_day_at_their_hour_and_weekly_on_monday(team_org):
    oid, _h = await team_org(["inbox_triage"])
    monday = datetime.now(IST).date()
    monday -= timedelta(days=monday.weekday())
    at8 = datetime(monday.year, monday.month, monday.day, 8, 10, tzinfo=IST).astimezone(UTC)
    mine = lambda rows: sorted(p for o, p in rows if o == oid)
    assert mine(await pulse.due(at8)) == ["daily", "weekly"]
    assert mine(await pulse.due(at8 + timedelta(hours=1))) == []  # not their hour
    assert mine(await pulse.due(at8 + timedelta(days=1))) == ["daily"]  # Tuesday: no week
    await pulse.mark_sent(oid, "daily", monday)
    assert mine(await pulse.due(at8)) == ["weekly"]
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.org_settings set profile = profile || '{"pulse": {"enabled": true, "hour": 7, "weekly": false}}'"""))
    assert mine(await pulse.due(at8 - timedelta(hours=1) + timedelta(days=1))) == ["daily"]


async def test_brief_reaches_the_owner_and_settings_are_for_owners(client, team_org, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda to, s, b: sent.append((to.split("-")[0], s, b)))
    oid, h = await busy_invoice_client(client, team_org)
    got = {r: (await client.get("/org/pulse", headers=h[r])).status_code for r in ALL}
    expect(got, **{r: 200 for r in ALL})
    view = (await client.get("/org/pulse", headers=h["viewer"])).json()
    assert view["title"] == "Morning brief: 2 to do" and view["can_edit"] is False and view["settings"] == {"enabled": True, "hour": 8, "weekly": True}
    got = {r: (await client.put("/org/pulse/settings", headers=h[r], json={"hour": 9})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    assert (await client.put("/org/pulse/settings", headers=h["owner"], json={"hour": 3})).status_code == 422
    eid = (await client.post("/org/pulse/send-now", headers=h["owner"])).json()["event_id"]
    async with tenant_session(oid) as conn:
        payload = (await conn.execute(text("select payload from app.events where id = :i"), {"i": eid})).scalar_one()
    ids = await center.plan({"id": eid, "org_id": oid, "type": "pulse.daily", "payload": payload})
    await center.deliver(oid, ids)
    assert [s[:2] for s in sent] == [("owner", "Morning brief: 2 to do")]  # "Morning brief" rule: the owner (Telegram not linked: email)
    assert "1 card waiting over 4 hours. Clear them in Needs you." in sent[0][2]
