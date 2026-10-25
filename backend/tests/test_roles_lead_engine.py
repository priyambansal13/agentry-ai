"""Lead reactivation and speed-to-lead, end to end, for every role.

                                          owner manager front-desk finance viewer agentry
leads list                                  ✓     ✓        ✓          –       –      ✓
campaigns: see                              ✓     ✓        ✓          ✓       ✓      ✓
campaigns: import old leads, start          ✓     ✓        –          –       –      ✓
lead forms (speed-to-lead): create, see     ✓     ✓        –          –       –      ✓
outreach drafts in Needs you: approve       ✓     ✓        ✓          –       –      ✓
"""
from datetime import UTC, datetime, timedelta

from conftest import expect
from sqlalchemy import text

from agentry.config import ROOT
from agentry.db import tenant_session
from agentry.sequences import send_step

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
ADMINS = {"owner": 200, "manager": 200, "staff": 403, "finance": 403, "viewer": 403, "agentry": 200}
READERS = {"owner": 200, "manager": 200, "staff": 200, "finance": 403, "viewer": 403, "agentry": 200}
OLD_LEADS = (ROOT / "mock-data" / "boring-machine" / "old-leads.csv").read_bytes()


def created(m: dict) -> dict:
    return {r: (201 if c == 200 else c) for r, c in m.items()}


async def test_lead_reactivation_every_role(client, team_org):
    oid, h = await team_org(["lead_reactivation"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    from agentry.connectors.store import save_connection
    await save_connection(oid, provider="whatsapp", account_ref=f"pn-{oid[:8]}", secret={"access_token": "t"})  # WhatsApp-first steps need it
    expect({r: (await client.get("/org/campaigns", headers=h[r])).status_code for r in ALL}, **{r: 200 for r in ALL})
    expect({r: (await client.get("/org/leads", headers=h[r])).status_code for r in ALL}, **READERS)
    files = {"file": ("old-leads.csv", OLD_LEADS, "text/csv")}
    got = {r: (await client.post("/org/campaigns/reactivation/import", headers=h[r], files=files)).status_code for r in ALL}
    expect(got, **ADMINS)
    got = {r: (await client.post("/org/campaigns/reactivation", headers=h[r], json={"name": f"Win-back {r}", "per_hour": 60})).status_code
           for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    started = (await client.post("/org/campaigns/reactivation", headers=h["manager"], json={"name": "Win-back", "per_hour": 60})).json()
    assert started["enrolled"] >= 5
    # the first message of each lead waits for approval (approval mode); people who handle conversations approve
    async with tenant_session(oid) as conn:
        eids = list((await conn.execute(text("select id from app.sequence_enrollments order by next_run_at limit 6"))).scalars())
        await conn.execute(text("update app.sequence_enrollments set next_run_at = now() - interval '1 minute'"))
    for e in eids:
        await send_step(oid, str(e), 0)
    drafts = [a for a in (await client.get("/org/approvals", headers=h["owner"])).json()["items"] if a["kind"] == "outbound_draft"]
    assert len(drafts) >= len(ALL) and all(a["automation_key"] == "lead_reactivation" for a in drafts)
    got = {r: (await client.post(f"/org/approvals/{drafts[i]['id']}", headers=h[r], json={"action": "reject"})).status_code
           for i, r in enumerate(ALL)}
    expect(got, **READERS)
    # speed-to-lead isn't switched on: no lead forms here
    expect({r: (await client.get("/org/lead-sources", headers=h[r])).status_code for r in ("owner", "agentry")}, owner=404, agentry=404)


async def test_speed_to_lead_every_role(client, team_org):
    oid, h = await team_org(["speed_to_lead"])
    f = (await client.get("/org/features", headers=h["owner"])).json()
    assert "lead_forms" in f["pages"] and "campaigns" not in f["pages"]  # lead forms live on the Leads page
    expect({r: (await client.post("/org/lead-sources", headers=h[r], json={"name": f"Form {r}"})).status_code for r in ALL},
           **created(ADMINS))
    expect({r: (await client.get("/org/lead-sources", headers=h[r])).status_code for r in ALL}, **ADMINS)
    src = (await client.get("/org/lead-sources", headers=h["owner"])).json()["items"][0]
    key = src["url"].rsplit("/", 1)[-1]
    # a website form posts a lead (public, keyed link); the team sees it on Leads
    r = await client.post(f"/hooks/leads/{key}", json={"name": "Ishaan Bhatt", "phone": "+91-90000-30011",
                                                       "message": "Tooth pain, can I come today?", "whatsapp_optin": True})
    assert r.status_code == 201
    leads = {r_: await client.get("/org/leads", headers=h[r_]) for r_ in ALL}
    expect({r_: x.status_code for r_, x in leads.items()}, **READERS)
    assert any(lead["name"] == "Ishaan Bhatt" for lead in leads["staff"].json()["items"])
    assert (await client.get("/org/campaigns", headers=h["owner"])).status_code == 404  # reactivation not bought
    from agentry.automations.speed_to_lead import start_first_touch
    await start_first_touch(oid, r.json()["lead_id"])  # what the worker does on lead.created
    async with tenant_session(oid) as conn:
        e = (await conn.execute(text("select count(*) from app.sequence_enrollments where next_run_at < :t"),
                                {"t": datetime.now(UTC) + timedelta(minutes=5)})).scalar_one()
    assert e == 1  # first touch scheduled within about a minute
