"""SOP & proposal drafter (ROADMAP-V3 B4): SOPs come with a flowchart; proposals never invent prices."""
from agentry.automations import doc_drafter as dd


async def test_sop_proposal_checklist(client, team_org):
    _oid, h = await team_org(["doc_drafter"])
    r = await client.post("/org/docs", headers=h["owner"], json={"kind": "sop", "brief": "How the front desk opens the clinic every morning."})
    assert r.status_code == 201 and r.json()["status"] == "draft"
    d = (await client.get(f"/org/docs/{r.json()['id']}", headers=h["staff"])).json()
    assert d["diagram"].startswith("flowchart TD") and "## Steps" in d["content"]
    p = await client.post("/org/docs", headers=h["owner"], json={"kind": "proposal", "brief": "Monthly social media for a bakery: 12 posts a month."})
    assert (await client.get(f"/org/docs/{p.json()['id']}", headers=h["owner"])).json()["content"].count("[price to confirm]") == 1
    c = await client.post("/org/docs", headers=h["manager"], json={"kind": "checklist", "brief": "Onboarding a new dental assistant in the first week."})
    assert c.status_code == 201
    x = await client.get(f"/org/docs/{r.json()['id']}/export", headers=h["owner"])
    assert "```mermaid" in x.text
    assert (await client.post("/org/docs", headers=h["staff"], json={"kind": "sop", "brief": "Closing the shop every evening safely."})).status_code == 403


def test_prices_must_come_from_the_brief():
    good = {"content": "Price: ₹15,000 a month. " + "Words here. " * 40}
    bad = {"content": "Price: ₹25,000 a month. " + "Words here. " * 40}
    assert dd.problems(good, "12 posts for ₹15,000 a month", "proposal") == []
    assert any("isn't in the brief" in p for p in dd.problems(bad, "12 posts for ₹15,000 a month", "proposal"))
