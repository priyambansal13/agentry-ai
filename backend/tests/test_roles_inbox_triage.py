"""Inbox triage, end to end, for every role. The matrix (docs/CLIENT-ONBOARDING.md §1):

                         owner manager front-desk finance viewer agentry
see / approve drafts       ✓     ✓        ✓          –       –      ✓
conversations, leads       ✓     ✓        ✓          –       –      ✓
knowledge: read            ✓     ✓        ✓          –       –      ✓
knowledge, settings, pause ✓     ✓        –          –       –      ✓
connections (see, connect) ✓     ✓        –          –       –      ✓
audit log                  ✓     ✓        –          –       –      ✓
billing                    ✓     –        –          ✓       –      ✓
export data                ✓     –        –          –       –      ✓
team: invite/change/remove ✓     –        –          –       –      ✓
urgent alerts + digest     on    on       opt-in     –       –
statements by email        on    –        –          on      –
"""
from conftest import expect
from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.db import tenant_session
from agentry.notify.alerts import recipient_emails

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def statuses(client, h, method, path, **kw):
    return {r: (await client.request(method, path, headers=h[r], **kw)).status_code for r in ALL}


async def test_inbox_triage_every_role(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    readers = {"owner": 200, "manager": 200, "staff": 200, "finance": 403, "viewer": 403, "agentry": 200}
    admins = {"owner": 200, "manager": 200, "staff": 403, "finance": 403, "viewer": 403, "agentry": 200}

    # an email arrives and is triaged into a draft (the workflow's steps, run inline)
    from agentry.automations.inbox_triage import workflow as wf
    for i in range(len(ALL)):
        mid = await ingest_email(oid, sender=f"client{i}@acme.example", subject=f"Quote for audit {i}?",
                                 body="Hi, could you send me a quote for our annual audit? Thanks", thread_ref=f"local:t{i}")
        email = await wf.load_email(oid, mid)
        triage = await wf.classify(oid, email) | {"needs_reply": True}
        await wf.save_triage(oid, email, triage)
        await wf.draft_reply(oid, email, triage)

    expect(await statuses(client, h, "GET", "/org/approvals"), **readers)
    expect(await statuses(client, h, "GET", "/org/conversations"), **readers)
    expect(await statuses(client, h, "GET", "/org/leads"), **readers)
    expect(await statuses(client, h, "GET", "/org/contacts"), **readers)
    expect(await statuses(client, h, "GET", "/org/knowledge"), **readers)
    expect(await statuses(client, h, "GET", "/org/automations"), **{r: 200 for r in ALL})

    # each role tries to approve its own draft: only the people who handle email may
    async with tenant_session(oid) as conn:
        drafts = list((await conn.execute(text("select id from app.approvals where status = 'pending' order by created_at"))).scalars())
    got = {r: (await client.post(f"/org/approvals/{drafts[i]}", headers=h[r], json={"action": "approve"})).status_code for i, r in enumerate(ALL)}
    expect(got, **readers)
    async with tenant_session(oid) as conn:  # every reply records who sent it (shown in the conversation)
        senders = sorted((await conn.execute(text("select metadata #>> '{sent_by,name}' from app.messages where author = 'human'"))).scalars())
    assert [x.split("-")[0].split("@")[0] for x in senders] == ["admin", "manager", "owner", "staff"]

    expect(await statuses(client, h, "POST", "/org/knowledge/faqs", json={"q": "Do you do GST filing?", "a": "Yes, monthly and quarterly."}),
           owner=201, manager=201, staff=403, finance=403, viewer=403, agentry=201)
    expect(await statuses(client, h, "PATCH", "/org/automations/inbox_triage/config", json={"digest_hour": 9}), **admins)
    expect(await statuses(client, h, "PATCH", "/org/automations/inbox_triage/config", json={"categories": ["Lead"]}),
           owner=403, manager=403, staff=403, finance=403, viewer=403, agentry=200)  # Agentry-managed field
    for r in ALL:  # pause, then resume, as each role
        p = (await client.post("/org/automations/inbox_triage/pause", headers=h[r])).status_code
        await client.post("/org/automations/inbox_triage/resume", headers=h["agentry"])
        assert p == admins[r], (r, p)
    expect(await statuses(client, h, "PUT", "/org/persona", json={"name": "Ava", "tone": "warm", "greeting": "Hello there!"}), **admins)
    expect(await statuses(client, h, "PATCH", "/org/profile", json={"city": "Pune"}),
           owner=200, manager=403, staff=403, finance=403, viewer=403, agentry=200)
    expect(await statuses(client, h, "GET", "/org/audit"), **admins)
    expect(await statuses(client, h, "GET", "/org/billing"), owner=200, manager=403, staff=403, finance=200, viewer=403, agentry=200)
    expect(await statuses(client, h, "GET", "/org/export/contacts.csv"), owner=200, manager=403, staff=403, finance=403, viewer=403, agentry=200)
    expect(await statuses(client, h, "POST", "/org/team/events", json={"action": "member.role_changed", "email": "x@y.z", "role": "viewer"}),
           owner=201, manager=403, staff=403, finance=403, viewer=403, agentry=201)
    # not part of an inbox-triage plan: hidden from everyone
    expect(await statuses(client, h, "GET", "/org/invoices"), **{r: 404 for r in ALL})
    expect(await statuses(client, h, "POST", "/org/connections/whatsapp", json={"phone_number_id": "1", "waba_id": "2", "access_token": "x"}),
           **{r: 404 for r in ALL})


async def test_inbox_triage_alerts_follow_role_and_choice(client, team_org):
    oid, h = await team_org(["inbox_triage"])
    kinds = {r: (await client.get("/org/notifications", headers=h[r])).json()["prefs"] for r in ("owner", "manager", "staff", "finance", "viewer")}
    assert kinds == {"owner": {"urgent": ["email"], "escalation": ["email"], "digest": ["email"], "weekly": ["email"], "billing": ["email"], "reports": ["email"]},
                     "manager": {"urgent": ["email"], "escalation": [], "digest": ["email"], "weekly": [], "reports": ["email"]},
                     "staff": {"urgent": [], "escalation": [], "digest": [], "weekly": [], "reports": []},  # front desk: allowed, off until they opt in
                     "finance": {"weekly": [], "billing": ["email"], "reports": []}, "viewer": {"weekly": [], "reports": []}}
    who = lambda emails: sorted(e.split("-")[0] for e in emails)
    assert who(await recipient_emails(oid, "urgent")) == ["manager", "owner"]
    assert who(await recipient_emails(oid, "billing")) == ["finance", "owner"]
    # the front desk opts in to urgent alerts; the owner switches the digest off; finance can't add alerts it may not get
    await client.put("/org/notifications", headers=h["staff"], json={"urgent": ["email"]})
    await client.put("/org/notifications", headers=h["owner"], json={"digest": []})
    r = await client.put("/org/notifications", headers=h["finance"], json={"urgent": ["email"], "billing": []})
    assert r.json()["prefs"] == {"weekly": [], "billing": [], "reports": []}
    assert who(await recipient_emails(oid, "urgent")) == ["manager", "owner", "staff"]
    assert who(await recipient_emails(oid, "digest")) == ["manager"]
    assert who(await recipient_emails(oid, "billing")) == ["owner"]
