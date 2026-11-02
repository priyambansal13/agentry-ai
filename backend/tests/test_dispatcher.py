"""Ops dispatcher (ROADMAP-V3 C2): jobs from chat or the team, assigned by skill / area / load, updates, invoices."""
import io
from datetime import date, timedelta

import pytest
from PIL import Image
from sqlalchemy import text

from agentry import governance
from agentry.agents.tools import run_tool, tool_defs
from agentry.automations import dispatcher as dp
from agentry.db import tenant_session

DAY = date.today() + timedelta(days=1)


@pytest.fixture(autouse=True)
def daytime(monkeypatch):
    monkeypatch.setattr(governance, "is_quiet", lambda now, tz: False)


async def _techs(client, h):
    for t in ({"name": "Imran", "phone": "+919810000101", "skills": ["AC service", "AC repair"], "areas": ["Kothrud", "Baner"], "max_per_day": 2},
              {"name": "Suresh", "phone": "+919810000102", "skills": ["AC service"], "areas": ["Kothrud"], "max_per_day": 3},
              {"name": "Vikas", "phone": "+919810000103", "skills": ["Plumbing"], "areas": [], "max_per_day": 4}):
        assert (await client.post("/org/dispatch/technicians", headers=h["manager"], json=t)).status_code == 201


async def test_assignment_by_skill_area_and_load(client, team_org):
    _oid, h = await team_org(["ops_dispatcher"])
    await _techs(client, h)
    made = []
    for i in range(4):
        r = await client.post("/org/dispatch/jobs", headers=h["staff"], json={"customer": f"Customer {i}", "phone": f"+9198100002{i:02d}", "service": "AC service",
                                                                               "area": "Kothrud", "day": DAY.isoformat()})
        made.append(r.json()["technician"])
    assert sorted(made[:2]) == ["Imran", "Suresh"] and made.count("Imran") == 2 and made.count("Suresh") == 2  # least busy first
    r = await client.post("/org/dispatch/jobs", headers=h["staff"], json={"customer": "Baner lady", "service": "AC repair", "area": "Baner", "day": DAY.isoformat()})
    assert r.json()["technician"] is None  # only Imran does Baner and he's full: waits with a card
    r = await client.post("/org/dispatch/jobs", headers=h["staff"], json={"customer": "Leak", "service": "Plumbing", "area": "Anywhere", "day": DAY.isoformat()})
    assert r.json()["technician"] == "Vikas"  # no areas = everywhere
    b = (await client.get(f"/org/dispatch?day={DAY.isoformat()}", headers=h["staff"])).json()
    assert len(b["jobs"]) == 6 and "Job #" in b["jobs"][0]["tech_message"]
    past = await client.post("/org/dispatch/jobs", headers=h["staff"], json={"customer": "X Y", "service": "AC service", "day": "2020-01-01"})
    assert past.status_code == 422


async def test_on_the_way_done_photo_and_invoice(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(["ops_dispatcher", "invoice_follow_up"])
    await _techs(client, h)
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    j = (await client.post("/org/dispatch/jobs", headers=h["staff"], json={"customer": "Asha Rao", "phone": "+919810000111", "service": "AC service",
                                                                           "area": "Kothrud", "day": DAY.isoformat()})).json()
    r = await client.patch(f"/org/dispatch/jobs/{j['id']}", headers=h["staff"], json={"status": "on_the_way"})
    assert r.json()["told"] == "sent" and "is on the way" in sent[-1]
    b = io.BytesIO()
    Image.new("RGB", (20, 20)).save(b, "JPEG")
    assert (await client.post(f"/org/dispatch/jobs/{j['id']}/photos", headers=h["staff"], files={"file": ("done.jpg", b.getvalue(), "image/jpeg")})).status_code == 201
    r = await client.patch(f"/org/dispatch/jobs/{j['id']}", headers=h["staff"], json={"status": "done", "amount": 1499})
    assert "is done" in sent[-1] and "₹1,499" in sent[-1]
    async with tenant_session(oid) as conn:
        inv = (await conn.execute(text("select number, amount, status from app.invoices where source = 'dispatcher'"))).one()
        photos = (await conn.execute(text("select jsonb_array_length(photos) from app.service_jobs"))).scalar_one()
    assert inv.number == f"JOB-{j['number']}" and float(inv.amount) == 1499 and photos == 1
    assert (await client.patch(f"/org/dispatch/jobs/{j['id']}", headers=h["viewer"], json={"status": "cancelled"})).status_code == 403


async def test_booked_from_the_chat(team_org):
    oid, _h = await team_org(["ops_dispatcher", "whatsapp_assistant"])
    assert "book_job" in {t["function"]["name"] for t in tool_defs(("dispatch",))}
    async with tenant_session(oid) as conn:
        conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, external_ref) values (:o, 'whatsapp', 'wa:1') returning id"""),
                                       {"o": oid})).scalar_one())
    r = await run_tool("book_job", {"name": "Neha", "phone": "+919810000121", "service": "AC repair", "day": DAY.isoformat()}, org_id=oid,
                       conversation_id=conv, source="whatsapp")
    assert "address or area" in r["error"]  # asks before booking
    r = await run_tool("book_job", {"name": "Neha", "phone": "+919810000121", "service": "AC repair", "area": "Kothrud", "day": DAY.isoformat(),
                                    "problem": "Not cooling"}, org_id=oid, conversation_id=conv, source="whatsapp")
    assert r["job"] > 100 and "job #" in r["tell_customer"]
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select source, status from app.service_jobs"))).one() == ("agent", "new")  # no technicians yet: waits
    assert dp.tech_message({"number": 1, "service": "X", "day": DAY, "slot": "any", "customer": "C"}).startswith("Job #1")
