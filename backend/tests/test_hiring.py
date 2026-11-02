"""Hiring assistant (ROADMAP-V3 A5): CVs scored with quoted reasons, nothing personal used, stages, the apply link."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.automations import hiring as hr
from agentry.db import tenant_session

JOB = {"title": "AC service technician", "description": "Install and service split and window ACs at customers' homes across Pune. Two-wheeler needed.",
       "must_have": ["2 years AC servicing", "split AC installation", "two-wheeler licence"], "location": "Pune"}
STRONG = b"""Ramesh Patil
ramesh.patil@example.com  +91 98100 00061
Male, Married, Date of birth 12/03/1995
Experience: 4 years AC servicing with CoolCare Services, Pune
Did split AC installation and gas charging for 300+ homes
Holds a two-wheeler licence and own bike
"""
WEAK = b"""Sunita Kale
sunita.k@example.com
Retail sales associate, 3 years
Customer service and billing
"""


async def test_scored_with_quotes_shortlisted_and_moved(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h = await team_org(["hiring"])
    r = await client.post("/org/hiring/jobs", headers=h["manager"], json=JOB)
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    assert (await client.post("/org/hiring/jobs", headers=h["staff"], json=JOB)).status_code == 403  # front desk doesn't hire
    up = await client.post(f"/org/hiring/jobs/{jid}/candidates", headers=h["owner"],
                           files=[("files", ("ramesh.txt", STRONG, "text/plain")), ("files", ("sunita.txt", WEAK, "text/plain")),
                                  ("files", ("empty.txt", b"hi", "text/plain"))])
    added = {a["name"]: a for a in up.json()["added"]}
    assert added["Ramesh Patil"]["verdict"] == "strong" and added["Ramesh Patil"]["score"] == 100
    assert added["Sunita Kale"]["verdict"] == "no" and len(up.json()["errors"]) == 1
    j = (await client.get(f"/org/hiring/jobs/{jid}", headers=h["owner"])).json()
    assert j["candidates"][0]["name"] == "Ramesh Patil" and "/public/jobs/" in j["apply_link"] and "AC service technician" in j["post"]
    c = (await client.get(f"/org/hiring/candidates/{added['Ramesh Patil']['id']}", headers=h["owner"])).json()
    quotes = [s["quote"] for s in c["assessment"]["strengths"]]
    assert all(q in STRONG.decode() for q in quotes) and len(quotes) == 3
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.approvals where automation_key = 'hiring'"))).scalar_one() == 1  # strong -> card
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "email"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    when = (datetime.now(UTC) + timedelta(days=2)).replace(hour=5, minute=30, second=0, microsecond=0)
    r = await client.post(f"/org/hiring/candidates/{added['Ramesh Patil']['id']}/stage", headers=h["owner"],
                          json={"status": "interview", "interview_at": when.isoformat()})
    assert r.json()["message"] == "sent" and "11:00 AM" in sent[-1] and "our office" in sent[-1]
    r = await client.post(f"/org/hiring/candidates/{added['Sunita Kale']['id']}/stage", headers=h["owner"], json={"status": "rejected"})
    assert "go ahead with other candidates" in sent[-1]
    assert (await client.post(f"/org/hiring/candidates/{added['Sunita Kale']['id']}/stage", headers=h["owner"], json={"status": "interview"})).status_code == 422


def test_personal_details_never_reach_the_model_or_the_reasons():
    job = {"title": "x", "description": "y", "must_have": ["AC servicing"]}
    a = hr.checked({"score": 90, "verdict": "strong", "strengths": [{"point": "Married, stable", "quote": "Married"},
                                                                   {"point": "AC work", "quote": "made up line"}], "gaps": []}, STRONG.decode(), job)
    assert a["strengths"] == []  # a personal detail and an invented quote are both dropped
    assert "[removed]" in hr.SKIP.sub("[removed]", STRONG.decode())


async def test_the_apply_link(client, team_org):
    oid, h = await team_org(["hiring"])
    jid = (await client.post("/org/hiring/jobs", headers=h["owner"], json=JOB)).json()["id"]
    link = (await client.get(f"/org/hiring/jobs/{jid}", headers=h["owner"])).json()["apply_link"]
    path = "/public/jobs/" + link.rsplit("/", 1)[-1]
    page = await client.get(path)
    assert page.status_code == 200 and "AC service technician" in page.text and "two-wheeler licence" in page.text
    r = await client.post(f"{path}/apply", data={"name": "Ramesh Patil", "email": "ramesh.patil@example.com", "phone": "+919810000061"},
                          files={"cv": ("ramesh.txt", STRONG, "text/plain")})
    assert r.status_code == 200 and "Thank you" in r.text
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select source from app.candidates"))).scalar_one() == "apply_link"
    await client.patch(f"/org/hiring/jobs/{jid}", headers=h["owner"], json={"status": "closed"})
    assert (await client.get(path)).status_code == 404
