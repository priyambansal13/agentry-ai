"""Packs (docs/PACKS.md): a client gets a pack tailored to them plus standalone add-ons; packs are edited in HQ."""
import uuid

import pytest
from conftest import TABLES
from sqlalchemy import create_engine, text

from agentry.config import settings

BUILT_CA = ["bookkeeping", "inbox_triage", "invoice_follow_up", "whatsapp_assistant"]  # the CA pack's defaults that exist today


@pytest.fixture
def bare_org():
    owner = create_engine(settings.migrate_database_url)
    oid = str(uuid.uuid4())
    with owner.begin() as c:
        c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Mehta & Co CA', :s, now())"""),
                  {"i": oid, "s": f"mehta-ca-{oid[:8]}"})
    yield oid
    with owner.begin() as c:
        for t in [*TABLES, "org_settings"]:
            c.execute(text(f"delete from app.{t} where org_id = :i"), {"i": oid})
        c.execute(text("delete from auth.organization where id = :i"), {"i": oid})
        c.execute(text("delete from app.agent_packs where key like 'test-%'"))
    owner.dispose()


async def test_ca_pack_client_gets_the_built_agents_and_the_pack_price(client, login, bare_org):
    staff = login("admin@agentry.dev")
    packs = (await client.get("/hq/agent-packs", headers=staff)).json()
    ca = next(p for p in packs["items"] if p["key"] == "ca-firm")
    assert {"ca_filing_tracker", "ca_document_chaser", "ca_gst_reconciliation", "bookkeeping"} <= {a["key"] for a in ca["agents"]}
    soon = {c["key"]: c for c in packs["catalog"]}["ca_filing_tracker"]
    assert soon["available"] is False and soon["name"] == "Filing tracker"

    r = await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "pack": "ca-firm"})
    assert r.status_code == 201, r.text
    assert r.json()["automations"] == BUILT_CA
    org = (await client.get(f"/hq/orgs/{bare_org}", headers=staff)).json()
    assert org["plan"]["retainer"] in (14999, "14999.00")  # no plan given: the pack's INR price
    pack = org["pack"]
    assert pack["name"] == "CA Firm" and pack["add_ons"] == []
    agents = {a["key"]: a for a in pack["agents"]}
    assert agents["bookkeeping"]["on"] and not agents["bookkeeping"]["coming_soon"]
    assert agents["ca_filing_tracker"]["coming_soon"] and not agents["ca_filing_tracker"]["on"]  # bought, switched on once built
    assert "ca_itr_prep" not in agents  # optional, not ticked
    assert {a["source"] for a in org["automations"]} == {"pack"}
    # the client sees their pack too
    assert (await client.get("/org", headers=staff | {"X-Org-Id": bare_org})).json()["pack"]["key"] == "ca-firm"


async def test_tailor_the_pack_add_ons_and_remove(client, login, bare_org):
    staff = login("admin@agentry.dev")
    body = {"org_id": bare_org, "pack": "ca-firm", "pack_agents": ["inbox_triage", "bookkeeping", "ca_document_chaser"],
            "automations": ["content_repurposing"], "plan": {"currency": "INR", "retainer": 9999}}
    r = await client.post("/hq/clients", headers=staff, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["automations"] == ["bookkeeping", "content_repurposing", "inbox_triage"]
    org = (await client.get(f"/hq/orgs/{bare_org}", headers=staff)).json()
    assert org["plan"]["retainer"] in (9999, "9999.00")  # an explicit plan wins over the pack price
    assert org["pack"]["add_ons"] == [{"key": "content_repurposing", "name": "Content repurposing"}]

    # retailor: drop bookkeeping, add invoices; the add-on stays
    r = await client.put(f"/hq/orgs/{bare_org}/pack", headers=staff, json={"pack": "ca-firm", "agents": ["inbox_triage", "invoice_follow_up"]})
    assert r.status_code == 200, r.text
    assert r.json()["automations"] == ["content_repurposing", "inbox_triage", "invoice_follow_up"]
    assert "invoices" in r.json()["pages"]
    # agents outside the pack, or only coming-soon ones, are refused
    bad = await client.put(f"/hq/orgs/{bare_org}/pack", headers=staff, json={"pack": "ca-firm", "agents": ["cold_email"]})
    assert bad.status_code == 409 and "not in the CA Firm pack" in bad.json()["detail"]
    soon = await client.put(f"/hq/orgs/{bare_org}/pack", headers=staff, json={"pack": "ca-firm", "agents": ["ca_filing_tracker"]})
    assert soon.status_code == 409 and "built" in soon.json()["detail"]

    # removing the pack keeps its agents as add-ons by default
    r = await client.delete(f"/hq/orgs/{bare_org}/pack", headers=staff)
    assert r.status_code == 200 and r.json()["automations"] == ["content_repurposing", "inbox_triage", "invoice_follow_up"]
    org = (await client.get(f"/hq/orgs/{bare_org}", headers=staff)).json()
    assert org["pack"] is None and {a["source"] for a in org["automations"]} == {"standalone"}
    audit = {a["action"] for a in (await client.get("/org/audit", headers=staff | {"X-Org-Id": bare_org})).json()["items"]}
    assert {"pack.assigned", "pack.removed", "client.created"} <= audit


async def test_remove_pack_and_its_agents(client, login, bare_org):
    staff = login("admin@agentry.dev")
    assert (await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "pack": "ca-firm"})).status_code == 201
    r = await client.delete(f"/hq/orgs/{bare_org}/pack?keep_agents=false", headers=staff)
    assert r.status_code == 409  # nothing would be left
    await client.put(f"/hq/orgs/{bare_org}/automations/reviews", headers=staff, json={"enabled": True})
    r = await client.delete(f"/hq/orgs/{bare_org}/pack?keep_agents=false", headers=staff)
    assert r.status_code == 200 and r.json()["automations"] == ["reviews"]


async def test_hq_builds_its_own_pack(client, login, bare_org):
    staff = login("admin@agentry.dev")
    pack = {"key": "test-clinic", "name": "Clinic", "tagline": "Fewer no-shows",
            "agents": [{"key": "appointment_concierge"}, {"key": "reviews"}, {"key": "ai_receptionist", "default_on": False}],
            "pricing": {"INR": {"currency": "INR", "retainer": 7999}}}
    r = await client.post("/hq/agent-packs", headers=staff, json=pack)
    assert r.status_code == 201, r.text
    assert (await client.post("/hq/agent-packs", headers=staff, json=pack)).status_code == 409
    bad = await client.post("/hq/agent-packs", headers=staff, json=pack | {"key": "test-bad", "agents": [{"key": "nope"}]})
    assert bad.status_code == 422
    wrong = await client.post("/hq/agent-packs", headers=staff, json=pack | {"key": "test-bad", "pricing": {"USD": {"currency": "INR"}}})
    assert wrong.status_code == 422
    assert (await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "pack": "test-clinic"})).json()["automations"] == \
        ["appointment_concierge", "reviews"]
    # archived packs can't be given to anyone new
    r = await client.put("/hq/agent-packs/test-clinic", headers=staff, json={k: v for k, v in pack.items() if k != "key"} | {"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert (await client.put(f"/hq/orgs/{bare_org}/pack", headers=staff, json={"pack": "test-clinic"})).status_code == 409
    # HQ only
    owner = login("riya@sharmadigital.example")
    assert (await client.get("/hq/agent-packs", headers=owner)).status_code == 403
    assert (await client.put(f"/hq/orgs/{bare_org}/pack", headers=owner, json={"pack": "ca-firm"})).status_code == 403
