"""Onboarding a client from Agentry HQ: only the automations they bought are visible, everywhere, and enforced by the API."""
import uuid

import pytest
from conftest import TABLES
from sqlalchemy import create_engine, text

from agentry.config import settings
from agentry.db import tenant_session


@pytest.fixture
def bare_org():
    """An organisation as the dashboard creates it (auth row only), removed afterwards."""
    owner = create_engine(settings.migrate_database_url)
    oid = str(uuid.uuid4())
    with owner.begin() as c:
        c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Mehta & Co', :s, now())"""),
                  {"i": oid, "s": f"mehta-{oid[:8]}"})
    yield oid
    with owner.begin() as c:
        for t in [*TABLES, "org_settings"]:
            c.execute(text(f"delete from app.{t} where org_id = :i"), {"i": oid})
        c.execute(text("delete from auth.organization where id = :i"), {"i": oid})


async def test_inbox_triage_only_client(client, login, bare_org):
    staff = login("admin@agentry.dev")
    as_client = staff | {"X-Org-Id": bare_org}
    plan = {"currency": "INR", "setup_fee": 5000, "retainer": 4999, "tax_rate": 0.18}
    r = await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "automations": ["inbox_triage"], "plan": plan})
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["automations"] == ["inbox_triage"] and f["connections"] == ["gmail", "outlook"]
    assert "invoices" not in f["pages"] and "campaigns" not in f["pages"] and "knowledge" in f["pages"]
    assert f["steps"] == ["profile", "plan", "team", "connect", "knowledge", "settings", "persona", "go_live"]
    assert f["go_live"] == ["profile", "mailbox"]
    # provisioning twice is refused; unknown or not-yet-built automations are refused
    assert (await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "automations": ["inbox_triage"]})).status_code == 409
    # hidden sections are hidden from the API too (even for Agentry staff: what staff see is what the client sees)
    assert (await client.get("/org/invoices", headers=as_client)).status_code == 404
    assert (await client.get("/org/campaigns", headers=as_client)).status_code == 404
    assert (await client.post("/org/connections/whatsapp", headers=as_client,
                              json={"phone_number_id": "1", "waba_id": "2", "access_token": "x"})).status_code == 404
    assert (await client.get("/org/leads", headers=as_client)).status_code == 200
    # the plan was saved with the client
    assert (await client.get(f"/hq/orgs/{bare_org}", headers=staff)).json()["plan"]["retainer"] in (4999, "4999.00")
    # go-live waits for the profile and a connected Gmail; the chat test isn't required for an inbox-only client
    prof = (await client.get("/org/profile", headers=as_client)).json()
    assert {c["key"]: c["done"] for c in prof["go_live_checks"]} == {"mailbox": False, "profile": False}
    r = await client.post("/org/go-live", headers=as_client)
    assert r.status_code == 409 and "Gmail or Outlook connected" in r.json()["detail"]
    assert (await client.patch("/org/profile", headers=as_client, json={"city": "Pune"})).status_code == 200
    async with tenant_session(bare_org) as conn:
        await conn.execute(text("""insert into app.connections (org_id, provider, account_ref, status, secret_enc) values (:o, 'gmail', 'mehta@x.example', 'connected', 'x')"""),
                           {"o": bare_org})
    r = await client.post("/org/go-live", headers=as_client)
    assert r.status_code == 200 and r.json()["approval_mode"] == ["inbox_triage"]


async def test_upsell_and_switch_off(client, login, bare_org):
    staff = login("admin@agentry.dev")
    as_client = staff | {"X-Org-Id": bare_org}
    assert (await client.post("/hq/clients", headers=staff, json={"org_id": bare_org, "automations": ["inbox_triage"]})).status_code == 201
    bad = await client.put(f"/hq/orgs/{bare_org}/automations/cold_email", headers=staff, json={"enabled": True})
    assert bad.status_code == 409  # not built yet
    f = (await client.put(f"/hq/orgs/{bare_org}/automations/invoice_follow_up", headers=staff, json={"enabled": True})).json()
    assert "invoices" in f["pages"] and "gateways" in f["connections"] and "import" in f["steps"]
    assert (await client.get("/org/invoices", headers=as_client)).status_code == 200
    assert (await client.get("/org/features", headers=as_client)).json()["automations"] == ["inbox_triage", "invoice_follow_up"]
    off = await client.put(f"/hq/orgs/{bare_org}/automations/invoice_follow_up", headers=staff, json={"enabled": False})
    assert off.status_code == 200 and (await client.get("/org/invoices", headers=as_client)).status_code == 404
    last = await client.put(f"/hq/orgs/{bare_org}/automations/inbox_triage", headers=staff, json={"enabled": False})
    assert last.status_code == 409  # never zero automations
    # HQ-only endpoints
    owner = login("riya@sharmadigital.example")
    assert (await client.put(f"/hq/orgs/{bare_org}/automations/invoice_follow_up", headers=owner, json={"enabled": True})).status_code == 403
    assert (await client.post("/hq/clients", headers=owner, json={"org_id": bare_org, "automations": ["inbox_triage"]})).status_code == 403
    audit = (await client.get("/org/audit", headers=as_client)).json()["items"]
    assert {"client.created", "automation.enabled", "automation.disabled"} <= {a["action"] for a in audit}


async def test_seeded_clients_keep_their_sections(client, login, orgs):
    sharma = (await client.get("/org/features", headers=login("riya@sharmadigital.example") | {"X-Org-Id": orgs["sharma-digital"]})).json()
    assert "invoices" in sharma["pages"] and "gmail" in sharma["connections"]
