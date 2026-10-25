"""Needs you, conversations, automation settings, email intake, opportunity report."""
import json
import uuid

from agentry.automations.inbox_triage.workflow import triage_email

H = lambda login, email, org: login(email) | {"X-Org-Id": org}


async def test_email_intake_triage_and_approve_edited_draft(client, login, orgs):
    org = orgs["sharma-digital"]
    owner = H(login, "riya@sharmadigital.example", org)
    r = await client.post("/org/inbox/emails", headers=owner, json={
        "sender": "anita@freshbrew.example", "subject": "Quote for social media management",
        "body": "Hi, we are a cafe chain looking for Instagram management. What would it cost per month?",
        "thread_ref": f"test-intake-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201
    await triage_email({"org_id": org, "payload": {"message_id": r.json()["message_id"]}})

    pending = (await client.get("/org/approvals", headers=owner)).json()
    item = next(a for a in pending["items"] if "anita@freshbrew.example" in a["title"])
    assert item["kind"] == "reply_draft" and pending["pending_by_kind"]["reply_draft"] >= 1

    edited = item["body"] + "\n\nP.S. Happy to share case studies."
    d = await client.post(f"/org/approvals/{item['id']}", headers=owner, json={"action": "approve", "body": edited})
    assert d.json()["status"] == "edited"
    again = await client.post(f"/org/approvals/{item['id']}", headers=owner, json={"action": "reject"})
    assert again.status_code == 409

    conv = (await client.get(f"/org/conversations/{item['conversation_id']}", headers=owner)).json()
    assert [m["direction"] for m in conv["messages"]] == ["in", "out"]
    assert conv["messages"][1]["body"].endswith("case studies.")
    assert conv["messages"][0]["metadata"]["triage"]["category"] == "Lead"


async def test_viewer_cannot_act_on_approvals(client, login, orgs):
    org = orgs["sharma-digital"]
    viewer = H(login, "multi@agentry.dev", org)  # viewer at Sharma Digital (has invoice follow-up)
    seen = await client.get("/org/approvals", headers=viewer)
    assert seen.status_code == 200  # invoice items only: viewers may read invoices, never conversations
    assert all(a["automation_key"] == "invoice_follow_up" for a in seen.json()["items"])
    owner = H(login, "riya@sharmadigital.example", org)
    other = next((a for a in (await client.get("/org/approvals", headers=owner)).json()["items"]
                  if a["automation_key"] != "invoice_follow_up"), None)
    if other:  # an email draft: neither viewer nor finance may act on it
        for who in (viewer, H(login, "accounts@sharmadigital.example", org)):
            assert (await client.post(f"/org/approvals/{other['id']}", headers=who, json={"action": "approve"})).status_code == 403


async def test_client_edits_only_client_fields(client, login, orgs):
    org = orgs["sharma-digital"]
    owner = H(login, "riya@sharmadigital.example", org)
    ok = await client.patch("/org/automations/inbox_triage/config", headers=owner,
                            json={"vip_senders": ["northstarrealty.example"], "digest_hour": 9})
    assert ok.status_code == 200 and ok.json()["config"]["digest_hour"] == 9
    locked = await client.patch("/org/automations/inbox_triage/config", headers=owner, json={"categories": ["Only"]})
    assert locked.status_code == 403 and "categories" in locked.text
    bad = await client.patch("/org/automations/inbox_triage/config", headers=owner, json={"digest_hour": 30})
    assert bad.status_code == 422
    staff = H(login, "admin@agentry.dev", org)
    assert (await client.patch("/org/automations/inbox_triage/config", headers=staff,
                               json={"categories": ["Client", "Lead", "Other"]})).status_code == 200
    autos = (await client.get("/org/automations", headers=owner)).json()["items"]
    triage = next(a for a in autos if a["template_key"] == "inbox_triage")
    assert triage["config_schema"]["properties"]["categories"]["editable_by"] == "agentry"
    # restore defaults
    await client.patch("/org/automations/inbox_triage/config", headers=staff, json={
        "categories": ["Client", "Lead", "Invoice/Payment", "Urgent", "Promotion", "Newsletter", "Spam", "Other"],
        "vip_senders": [], "digest_hour": 8})


async def test_opportunity_report_counts_unanswered_enquiries(client, login, orgs):
    org = orgs["sharma-digital"]
    owner = H(login, "riya@sharmadigital.example", org)
    rep = (await client.get("/org/reports/opportunity?days=30", headers=owner)).json()
    assert rep["emails_triaged"] >= 1 and rep["enquiries"] >= 1
    assert rep["enquiries_never_answered"] <= rep["enquiries"]
    assert "close rate" in rep["method"]
    json.dumps(rep)  # serialisable
