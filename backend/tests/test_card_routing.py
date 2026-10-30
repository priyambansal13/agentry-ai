"""Auto-assign rules: every Needs-you card for a client (contact) or for an agent goes to one chosen person."""
from conftest import expect
from helpers import csv_bytes, enrollment_for, inv
from sqlalchemy import text
from test_invoice_e2e import go_live_invoice_client

from agentry.db import tenant_session
from agentry.invoices import enroll_open
from agentry.sequences import send_step

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def card_for(oid: str, number: str) -> dict:
    """Make the next reminder card for an invoice (approval mode) and return it."""
    eid = await enrollment_for(oid, number)
    assert (await send_step(oid, eid, 0))["results"][0]["status"] == "awaiting_approval"
    async with tenant_session(oid) as conn:
        return dict((await conn.execute(text("""select id::text, assigned_to, assigned_by from app.approvals
            where payload->>'enrollment_id' = :e order by created_at desc limit 1"""), {"e": eid})).mappings().one())


async def contact_of(oid: str, number: str) -> str:
    async with tenant_session(oid) as conn:
        return str((await conn.execute(text("select contact_id from app.invoices where number = :n"), {"n": number})).scalar_one())


async def test_rules_route_new_and_waiting_cards(client, team_org):
    from datetime import date, timedelta
    oid, h = await go_live_invoice_client(client, team_org)
    other = inv("K-1", date.today() - timedelta(days=9), email="accounts@kaveri.example") | {"Company": "Kaveri Steels", "Contact": "P. Senthil",
                                                                                          "Phone": "+91-90000-77777"}
    files = {"file": ("more.csv", csv_bytes([other]), "text/csv")}
    assert (await client.post("/org/invoices/import", headers=h["owner"], files=files, data={"commit": "true"})).json()["created"] == 1
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    people = {p["role"]: p["id"] for p in (await client.get("/org/assignees", headers=h["owner"])).json()["items"]}
    waiting = await card_for(oid, "E-2")  # a card made before any rule exists
    assert waiting["assigned_to"] is None

    # only owners, managers (and Agentry) set rules; the person must be able to handle those cards
    body = {"scope": "automation", "key": "invoice_follow_up", "assign_to": people["finance"]}
    got = {r: (await client.put("/org/card-routing", headers=h[r], json=body)).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    bad = await client.put("/org/card-routing", headers=h["owner"], json=body | {"assign_to": people["staff"]})
    assert bad.status_code == 422  # front desk can't act on invoices
    assert (await client.put("/org/card-routing", headers=h["owner"], json=body | {"key": "website_chat"})).status_code == 404

    async with tenant_session(oid) as conn:  # the waiting card followed the rule
        assert (await conn.execute(text("select assigned_to from app.approvals where id = cast(:i as uuid)"), {"i": waiting["id"]})).scalar_one() == people["finance"]
    new = await card_for(oid, "E-1")
    assert new["assigned_to"] == people["finance"] and new["assigned_by"] == "rule"
    mine = (await client.get("/org/approvals?view=mine", headers=h["finance"])).json()["items"]
    assert {a["id"] for a in mine} >= {waiting["id"], new["id"]} and all(a["assigned_name"] for a in mine if a["id"] == new["id"])

    # a rule for one client beats the agent-wide rule
    e1 = await contact_of(oid, "E-1")
    r = await client.put("/org/card-routing", headers=h["manager"], json={"scope": "contact", "key": e1, "assign_to": people["manager"]})
    assert r.status_code == 200, r.text
    rules = {(x["scope"], x["assign_name"]) for x in r.json()["items"]}
    assert rules == {("automation", "Finance"), ("contact", "Manager")}
    assert next(x for x in r.json()["items"] if x["scope"] == "contact")["contact_name"] == "Northstar Realty"
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.approvals set status = 'resolved' where status = 'pending'"))
    assert (await card_for(oid, "E-1"))["assigned_to"] == people["manager"]
    assert (await card_for(oid, "K-1"))["assigned_to"] == people["finance"]  # another client: the agent-wide rule


async def test_removing_a_rule_releases_its_cards_but_not_hand_assigned_ones(client, team_org):
    oid, h = await go_live_invoice_client(client, team_org)
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    people = {p["role"]: p["id"] for p in (await client.get("/org/assignees", headers=h["owner"])).json()["items"]}
    by_hand = await card_for(oid, "E-1")
    assert (await client.post(f"/org/approvals/{by_hand['id']}/assign", headers=h["owner"], json={"user_id": people["owner"]})).status_code == 200
    by_rule = await card_for(oid, "E-2")
    r = (await client.put("/org/card-routing", headers=h["owner"],
                          json={"scope": "automation", "key": "invoice_follow_up", "assign_to": people["finance"]})).json()
    assert r["cards_assigned"] == 1  # the hand-assigned card stays with the owner
    r = (await client.put("/org/card-routing", headers=h["owner"], json={"scope": "automation", "key": "invoice_follow_up", "assign_to": None})).json()
    assert r["items"] == []
    async with tenant_session(oid) as conn:
        got = dict((await conn.execute(text("select id::text, assigned_to from app.approvals where id = any(cast(:i as uuid[]))"),
                                       {"i": [by_hand["id"], by_rule["id"]]})).all())
        acts = set((await conn.execute(text("select action from app.audit_log where action like 'card_routing.%'"))).scalars())
    assert got == {by_hand["id"]: people["owner"], by_rule["id"]: None}
    assert acts == {"card_routing.set", "card_routing.removed"}


async def test_client_rule_covers_only_cards_the_person_can_handle(client, team_org):
    """A client given to Finance: their invoice cards go to Finance, their emails stay with the people who do conversations."""
    oid, h = await go_live_invoice_client(client, team_org)
    assert (await client.put(f"/hq/orgs/{oid}/automations/inbox_triage", headers=h["agentry"], json={"enabled": True})).status_code == 200
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    people = {p["role"]: p["id"] for p in (await client.get("/org/assignees", headers=h["owner"])).json()["items"]}
    contact = await contact_of(oid, "E-1")
    r = await client.put("/org/card-routing", headers=h["owner"], json={"scope": "contact", "key": contact, "assign_to": people["finance"]})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["resources"] == ["invoice"]
    # an agent-wide rule still needs someone who can work all of that agent's cards
    bad = await client.put("/org/card-routing", headers=h["owner"], json={"scope": "automation", "key": "inbox_triage", "assign_to": people["finance"]})
    assert bad.status_code == 422
    assert (await card_for(oid, "E-1"))["assigned_to"] == people["finance"]
    async with tenant_session(oid) as conn:
        conv = (await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, contact_id, subject, external_ref)
            values (:o, 'email', 'inbox_triage', cast(:c as uuid), 'Quick question', 'test-route-1') returning id"""), {"o": oid, "c": contact})).scalar_one()
        who = (await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, conversation_id, title, body)
            values (:o, 'reply_draft', 'inbox_triage', :c, 'Reply to a question', 'Hi') returning assigned_to"""), {"o": oid, "c": conv})).scalar_one()
    assert who is None


async def test_a_client_rule_takes_cards_from_an_earlier_agent_rule(client, team_org):
    oid, h = await go_live_invoice_client(client, team_org)
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    people = {p["role"]: p["id"] for p in (await client.get("/org/assignees", headers=h["owner"])).json()["items"]}
    card = await card_for(oid, "E-1")
    await client.put("/org/card-routing", headers=h["owner"], json={"scope": "automation", "key": "invoice_follow_up", "assign_to": people["owner"]})
    r = (await client.put("/org/card-routing", headers=h["owner"],
                          json={"scope": "contact", "key": await contact_of(oid, "E-1"), "assign_to": people["finance"]})).json()
    assert r["cards_assigned"] == 1
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select assigned_to from app.approvals where id = cast(:i as uuid)"), {"i": card["id"]})).scalar_one() == people["finance"]
