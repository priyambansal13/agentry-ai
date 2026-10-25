"""API: membership, roles, org switching, Agentry HQ, public demo form, outbox."""
from sqlalchemy import text

from agentry.db import system_session
from agentry.permissions import can


def test_role_matrix():
    assert can("owner", "billing", "manage")
    assert not can("staff", "billing", "read")
    assert can("staff", "conversation", "act")
    assert can("finance", "invoice", "act") and not can("finance", "conversation", "read")
    assert not can("viewer", "automation", "pause")
    assert can("viewer,manager", "automation", "pause")  # multi-role members


async def test_member_reads_own_org(client, login, orgs):
    r = await client.get("/org/contacts", headers=login("riya@sharmadigital.example") | {"X-Org-Id": orgs["sharma-digital"]})
    assert r.status_code == 200
    assert r.json()["total"] >= 10  # 10 seeded; other tests may add leads' contacts
    assert all(c["email"] for c in r.json()["items"])


async def test_member_cannot_open_other_org(client, login, orgs):
    r = await client.get("/org", headers=login("riya@sharmadigital.example") | {"X-Org-Id": orgs["smilecraft"]})
    assert r.status_code == 403


async def test_role_permissions_enforced(client, login, orgs):
    h = login("frontdesk@smilecraft.example") | {"X-Org-Id": orgs["smilecraft"]}
    assert (await client.get("/org/contacts", headers=h)).status_code == 200  # staff: conversation:read
    assert (await client.get("/org/audit", headers=h)).status_code == 403  # staff: no audit:read
    assert (await client.post("/org/automations/website_chat/pause", headers=h)).status_code == 403


async def test_org_switcher_lists_memberships(client, login):
    r = await client.get("/me", headers=login("multi@agentry.dev"))
    names = {o["slug"]: o["role"] for o in r.json()["organizations"]}
    assert names == {"sharma-digital": "viewer", "smilecraft": "manager"}


async def test_overview_tiles_come_from_rollups(client, login, orgs):
    r = await client.get("/org/overview?days=30", headers=login("neha@smilecraft.example") | {"X-Org-Id": orgs["smilecraft"]})
    body = r.json()
    keys = [t["key"] for t in body["tiles"]]
    assert "calls_answered" in keys and "appointments_booked" in keys
    assert "amount_recovered" not in keys  # SmileCraft has no invoice automation
    assert all(len(t["series"]) == 30 for t in body["tiles"])


async def test_pause_resume_is_audited(client, login, orgs):
    h = login("neha@smilecraft.example") | {"X-Org-Id": orgs["smilecraft"]}
    assert (await client.post("/org/automations/lead_reactivation/pause", headers=h)).json()["status"] == "paused"
    assert (await client.post("/org/automations/lead_reactivation/resume", headers=h)).json()["status"] == "live"
    items = (await client.get("/org/audit?limit=2", headers=h)).json()["items"]
    assert [i["action"] for i in items] == ["automation.resume", "automation.pause"]
    assert items[0]["actor_type"] == "user"


async def test_agentry_staff_access_is_audited_as_staff(client, login, orgs):
    h = login("admin@agentry.dev") | {"X-Org-Id": orgs["smilecraft"]}
    assert (await client.post("/org/automations/website_chat/pause", headers=h)).status_code == 200
    await client.post("/org/automations/website_chat/resume", headers=h)
    owner = login("neha@smilecraft.example") | {"X-Org-Id": orgs["smilecraft"]}
    latest = (await client.get("/org/audit?limit=1", headers=owner)).json()["items"][0]
    assert latest["actor_type"] == "agentry_staff"


async def test_hq_is_staff_only(client, login):
    assert (await client.get("/hq/orgs", headers=login("riya@sharmadigital.example"))).status_code == 403
    r = await client.get("/hq/orgs", headers=login("admin@agentry.dev"))
    kaveri = next(o for o in r.json()["items"] if o["slug"] == "kaveri-industrial")
    assert kaveri["status"] == "onboarding" and "Meta approval" in kaveri["blockers"]


async def test_demo_request_writes_row_and_outbox_event(client):
    r = await client.post("/public/demo-requests", json={
        "name": "Test Prospect", "email": "prospect@clinic.example", "company": "Test Clinic",
        "website": "https://clinic.example", "niche": "clinic_or_appointments"})
    assert r.status_code == 201
    async with system_session() as conn:
        ev = (await conn.execute(text("select type, payload from app.events where payload->>'demo_request_id' = :id"),
                                 {"id": r.json()["id"]})).one()
    assert ev.type == "demo_request.created"
    async with system_session() as conn:  # leave nothing for HQ (or a running dev worker) to pick up
        await conn.execute(text("delete from app.events where payload->>'demo_request_id' = :id"), {"id": r.json()["id"]})
        await conn.execute(text("delete from app.demo_requests where id = cast(:id as uuid)"), {"id": r.json()["id"]})


async def test_demo_request_honeypot_stores_nothing(client):
    r = await client.post("/public/demo-requests", json={"name": "Bot", "email": "bot@spam.example",
                                                         "company_url": "http://spam.example"})
    assert r.status_code == 201 and "id" not in r.json()
