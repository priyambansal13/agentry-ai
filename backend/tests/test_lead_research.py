"""Lead Research & Meeting Prep: a note on each new lead from their own website (never invented names or numbers),
nothing from gmail.com addresses, and a one-page brief before the meeting that reaches the team once."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from conftest import expect
from sqlalchemy import text

from agentry.automations import lead_research as lr
from agentry.automations.cold_email.providers import SitePage
from agentry.booking import book, set_catalog
from agentry.db import tenant_session
from agentry.leads import resolve_contact
from agentry.notify import alerts, center

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
IST = ZoneInfo("Asia/Kolkata")
HOURS = {d: [["09:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


async def agency(team_org):
    oid, h = await team_org(["lead_research"])
    await set_catalog(oid, [{"key": "discovery", "name": "Discovery call", "minutes": 30}], [{"name": "Priya", "services": ["discovery"], "hours": HOURS}])
    return oid, h


async def new_lead(oid: str, name: str, email: str, need: str) -> str:
    async with tenant_session(oid) as conn:
        k = await resolve_contact(conn, oid, name=name, email=email, source="form")
        return str((await conn.execute(text("""insert into app.leads (org_id, contact_id, source, qualification) values (:o, :k, 'form', cast(:q as jsonb))
            returning id"""), {"o": oid, "k": k, "q": f'{{"need": "{need}"}}'})).scalar_one())


def test_company_domain_skips_personal_mail():
    assert lr.company_domain("divya@raotoothclinic.example", None) == "raotoothclinic.example"
    assert lr.company_domain("someone@gmail.com", None) is None
    assert lr.company_domain("someone@gmail.com", "www.Acme.example/about") == "acme.example"  # a website they gave wins


def test_ground_drops_what_the_pages_dont_say():
    pages = [SitePage("https://x.example", "X", "Founded in 2010. Dr. Divya Rao, Founder & Lead Dentist.")]
    note = {"company": "X", "what_they_do": "Dentistry since 2010", "size": "45 staff", "likely_need": "More bookings",
            "decision_maker": {"name": "Rahul Mehta", "role": "CEO"}, "talking_points": ["Open since 2010", "Serves 9,000 families"], "questions": ["Why now?"]}
    g = lr.ground(note, pages, "need: more patients")
    assert g["size"] is None and g["decision_maker"] is None  # 45 isn't in the sources; Rahul isn't on the pages
    assert g["what_they_do"] == "Dentistry since 2010" and g["talking_points"] == ["Open since 2010"]
    named = lr.ground({**note, "decision_maker": {"name": "Divya Rao", "role": "Founder & Lead Dentist"}}, pages, "")
    assert named["decision_maker"] == {"name": "Divya Rao", "role": "Founder & Lead Dentist"}
    assert lr.ground({**note, "decision_maker": {"name": "Divya Rao", "role": "Receptionist"}}, pages, "")["decision_maker"] is None


async def test_research_from_their_website(team_org):
    oid, _h = await agency(team_org)
    lid = await new_lead(oid, "Divya Rao", "divya@raotoothclinic.example", "a website that gets more bookings")
    note = await lr.research(oid, lid)
    assert note["status"] == "done" and note["domain"] == "raotoothclinic.example" and len(note["sources"]) == 3
    assert note["company"] == "Rao Tooth Clinic" and note["decision_maker"] == {"name": "Divya Rao", "role": "Founder & Lead Dentist"}
    assert "a website that gets more bookings" in note["likely_need"] and note["talking_points"]
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select research->>'company' from app.leads where id = cast(:i as uuid)"), {"i": lid})).scalar_one() == "Rao Tooth Clinic"
        assert (await conn.execute(text("select company from app.contacts where email = 'divya@raotoothclinic.example'"))).scalar_one() == "Rao Tooth Clinic"
        assert (await conn.execute(text("select payload->>'status' from app.events where type = 'lead.researched'"))).scalar_one() == "done"
        run = (await conn.execute(text("select status, steps from app.agent_runs where agent = 'lead_research'"))).one()
    assert run.status == "ok" and [s["name"] for s in run.steps] == ["read_site", "note"]


async def test_personal_email_gets_a_note_without_a_website(team_org, monkeypatch):
    oid, _h = await agency(team_org)
    fetched = []
    monkeypatch.setattr(lr, "fetch_pages", lambda d: fetched.append(d))
    lid = await new_lead(oid, "Ravi", "ravi.k@gmail.com", "SEO for my bakery")
    note = await lr.research(oid, lid)
    assert fetched == [] and note["status"] == "no_company" and note["company"] is None and note["likely_need"].endswith("SEO for my bakery")


async def test_brief_before_the_meeting_goes_out_once(client, team_org, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda to, s, b: sent.append((to.split("-")[0], s, b)))
    oid, h = await agency(team_org)
    lid = await new_lead(oid, "Divya Rao", "divya@raotoothclinic.example", "more bookings")
    start = datetime.combine(datetime.now(IST).date() + timedelta(days=2), time(11), IST)
    bid = (await book(oid, service_key="discovery", start=start, name="Divya Rao", email="divya@raotoothclinic.example", source="test", lead_id=lid))["booking_id"]
    plan = datetime.fromisoformat(await lr.brief_plan(oid, bid))
    assert plan == start - timedelta(minutes=30)
    assert await lr.send_brief(oid, bid) == "sent"
    assert await lr.send_brief(oid, bid) == "already"
    async with tenant_session(oid) as conn:
        await center.ensure_defaults(conn, oid)
        ev = (await conn.execute(text("select id, payload from app.events where type = 'meeting.brief'"))).one()
    body = ev.payload["body"]
    assert ev.payload["title"] == "Brief: Divya Rao, Discovery call at 11:00 AM"
    assert body.startswith("Discovery call with Priya at 11:00 AM. Contact: divya@raotoothclinic.example.")
    assert "Company: Rao Tooth Clinic\nWhat they do: " in body and "Decision maker: Divya Rao (Founder & Lead Dentist)" in body
    assert "They said: need: more bookings" in body and body.endswith("History: first visit.")
    ids = await center.plan({"id": ev.id, "org_id": oid, "type": "meeting.brief", "payload": ev.payload})
    await center.deliver(oid, ids)
    assert sorted(s[0] for s in sent) == ["manager", "owner"] and sent[0][1] == ev.payload["title"]  # default rule "Meeting briefs"
    got = {r: (await client.get(f"/org/leads/{lid}", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    d = (await client.get(f"/org/leads/{lid}", headers=h["staff"])).json()
    assert d["research"]["company"] == "Rao Tooth Clinic" and d["bookings"][0]["brief"]["title"] == ev.payload["title"] and d["can_research"] is True


async def test_research_again_by_role_and_off_without_the_agent(client, team_org):
    oid, h = await agency(team_org)
    lid = await new_lead(oid, "Divya Rao", "divya@raotoothclinic.example", "more bookings")
    got = {r: (await client.post(f"/org/leads/{lid}/research", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    other, h2 = await team_org(["speed_to_lead"])
    lid2 = await new_lead(other, "X", "x@raotoothclinic.example", "y")
    assert (await client.post(f"/org/leads/{lid2}/research", headers=h2["owner"])).status_code == 404
    assert await lr.research_step(other, lid2) == "off"
    async with tenant_session(other) as conn:
        assert (await conn.execute(text("select research from app.leads where id = cast(:i as uuid)"), {"i": lid2})).scalar_one() is None
