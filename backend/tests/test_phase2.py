"""Phase 2: lead engine identity/consent/ownership, sequence engine, invoices + payments, reactivation, speed-to-lead."""
import asyncio
import hashlib
import hmac
import itertools
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from dbos import DBOS, SetWorkflowID
from helpers import enrollment_for, import_invoices, inv
from sqlalchemy import text

from agentry.automations.invoice_follow_up import act_on_reply
from agentry.automations.lead_reactivation import eligibility, import_old_leads, start_campaign
from agentry.automations.speed_to_lead import create_source
from agentry.connectors.store import save_connection
from agentry.db import tenant_session
from agentry.invoices import (
    apply_payment,
    parse_file,
)
from agentry.leads import can_contact, claim, dedupe, normalize_phone, resolve_contact
from agentry.sequences import next_action, run_enrollment, send_step, workflow_id

with open("../mock-data/boring-machine/old-leads.csv", "rb") as _f:
    OLD_LEADS = _f.read()


# ---------- lead engine ----------

async def test_identity_merges_same_person_across_formats(org):
    assert normalize_phone("90000 20001") == normalize_phone("+91-90000-20001") == "+919000020001"
    async with tenant_session(org) as conn:
        a = await resolve_contact(conn, org, name="Rahul Joshi", phone="+91-90000-20001", email="rahul.j@mail.example", source="t")
        b = await resolve_contact(conn, org, name="Rahul J", phone="+91 9000020001", source="t")
        c = await resolve_contact(conn, org, email="RAHUL.J@mail.example", source="t")
        assert a == b == c
        # two records created independently (e.g. before matching existed) are merged by dedupe
        x = (await conn.execute(text("""insert into app.contacts (org_id, name, email, email_norm, source)
            values (:o, 'Dup', 'dup@x.example', 'dup@x.example', 't') returning id"""), {"o": org})).scalar_one()
        y = (await conn.execute(text("""insert into app.contacts (org_id, name, email, email_norm, source)
            values (:o, 'Dup2', 'Dup@X.example', 'dup@x.example', 't') returning id"""), {"o": org})).scalar_one()
        assert await dedupe(conn) == 1
        merged = (await conn.execute(text("select merged_into from app.contacts where id = :y"), {"y": y})).scalar_one()
        assert str(merged) == str(x)


async def test_consent_and_suppression_gate_every_channel(org):
    async with tenant_session(org) as conn:
        cid = await resolve_contact(conn, org, name="P", phone="+91-90000-30001", email="p@x.example", source="t")
        assert (await can_contact(conn, cid, "whatsapp")) == (False, "no whatsapp consent")
        assert (await can_contact(conn, cid, "email"))[0] is True
        from agentry.leads import opt_out, record_consent
        await record_consent(conn, org, cid, "whatsapp", True, "test")
        assert (await can_contact(conn, cid, "whatsapp"))[0] is True
        await opt_out(conn, org, cid, "whatsapp", "test")
        ok, why = await can_contact(conn, cid, "whatsapp")
        assert not ok and "suppressed" in why


async def test_one_voice_inbound_takes_over_and_stops_outbound(org):
    async with tenant_session(org) as conn:
        cid = await resolve_contact(conn, org, name="Kavya", phone="+91-90000-20006", source="t")
        await conn.execute(text("insert into app.consents (org_id, contact_id, channel, status) values (:o, :c, 'whatsapp', 'granted')"),
                           {"o": org, "c": cid})
        lid = str((await conn.execute(text("""insert into app.leads (org_id, contact_id, source, stage) values (:o, :c, 'old_leads', 'nurture')
            returning id"""), {"o": org, "c": cid})).scalar_one())
        result = await start_campaign(conn, org, "Test", per_hour=60)
        assert result["enrolled"] == 1
        assert await claim(conn, lid, "cold_email") is False  # lower priority can't take over
        assert await claim(conn, lid, "whatsapp_assistant", inbound=True) is True
        status = (await conn.execute(text("select status, stop_reason from app.sequence_enrollments where subject_id = :l"), {"l": lid})).first()
    assert status.status == "stopped" and "whatsapp_assistant" in status.stop_reason


# ---------- invoices + sequences ----------

async def test_import_enrolls_open_invoices_only(org):
    today = datetime.now(UTC).date()
    r = await import_invoices(org, [inv("T-1", today - timedelta(days=8)), inv("T-2", today - timedelta(days=3), paid=45000),
                                    inv("T-3", today + timedelta(days=10), email="other@x.example")])
    assert r["created"] == 3 and r["enrolled"] == 2  # T-2 is paid
    again = await import_invoices(org, [inv("T-1", today - timedelta(days=8))])
    assert again["created"] == 0 and again["updated"] == 1 and again["enrolled"] == 0  # idempotent


async def test_catch_up_sends_only_the_latest_due_step(org):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-30", today - timedelta(days=30))])
    eid = await enrollment_for(org, "T-30")
    plan = await next_action(org, eid)
    assert plan == {"action": "send", "step": 3}  # day 28 'final' only, not days 7/14/21 in a burst
    out = await send_step(org, eid, 3)
    assert out["results"][0] == {"channel": "email", "status": "recorded", "conversation_id": out["results"][0]["conversation_id"]}
    assert out["results"][1]["status"] == "skipped" and "consent" in out["results"][1]["reason"]
    async with tenant_session(org) as conn:
        body = (await conn.execute(text("""select m.body from app.messages m join app.conversations c on c.id = m.conversation_id
            where c.metadata->>'enrollment_id' = :e"""), {"e": eid})).scalar_one()
    assert "₹45,000" in body and "T-30" in body  # facts from the database, never invented
    assert (await next_action(org, eid))["action"] == "done"  # all steps sent


async def test_step_waits_until_due(org):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-5", today - timedelta(days=5))])
    plan = await next_action(org, await enrollment_for(org, "T-5"))
    assert plan["action"] == "wait" and 0 < plan["seconds"] <= 6 * 3600


async def test_payment_stops_the_running_workflow(org):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-9", today - timedelta(days=9))])
    eid = await enrollment_for(org, "T-9")
    with SetWorkflowID(workflow_id(eid)):
        handle = await DBOS.start_workflow_async(run_enrollment, org, eid)
    for _ in range(50):  # wait until step 0 (day 7) has been sent and the workflow is sleeping
        async with tenant_session(org) as conn:
            if (await conn.execute(text("select last_step from app.sequence_enrollments where id = :e"), {"e": eid})).scalar_one() == 0:
                break
        await asyncio.sleep(0.1)
    async with tenant_session(org) as conn:
        invoice_id = str((await conn.execute(text("select id from app.invoices where number = 'T-9'"))).scalar_one())
        pid = await apply_payment(conn, org, invoice_id=invoice_id, amount=Decimal(45000), currency="INR", gateway="manual",
                                  reference="UTR-TEST-1", match="manual")
        assert pid and await apply_payment(conn, org, invoice_id=invoice_id, amount=Decimal(45000), currency="INR",
                                           gateway="manual", reference="UTR-TEST-1", match="manual") is None  # once
    await DBOS.send_async(workflow_id(eid), {"reason": "payment"}, topic="seq")
    assert await asyncio.wait_for(handle.get_result(), 10) == "invoice paid"


async def test_approval_mode_queues_reminders(org):
    async with tenant_session(org) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode' where template_key = 'invoice_follow_up'"))
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-A", today - timedelta(days=15))])
    eid = await enrollment_for(org, "T-A")
    out = await send_step(org, eid, 1)
    assert out["results"][0]["status"] == "awaiting_approval"
    async with tenant_session(org) as conn:
        a = (await conn.execute(text("select title, body, payload from app.approvals where kind = 'outbound_draft'"))).mappings().one()
    assert "T-A" in a["title"] and a["payload"]["channel"] == "email" and "₹45,000" in a["body"]


async def test_reply_actions(org):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-P", today - timedelta(days=10)), inv("T-D", today - timedelta(days=10), email="d@x.example")])
    async with tenant_session(org) as conn:
        rows = {r.number: {"id": str(r.id), "number": r.number, "contact_id": str(r.contact_id)}
                for r in (await conn.execute(text("select id, number, contact_id from app.invoices"))).all()}
    promise = (today + timedelta(days=6)).isoformat()
    assert await act_on_reply(org, rows["T-P"], None, "will pay", {"label": "promise_to_pay", "date": promise}, 1) == "promise_to_pay"
    assert await act_on_reply(org, rows["T-D"], None, "wrong amount", {"label": "dispute", "reason": "billed 16h not 10h"}, 1) == "dispute"
    async with tenant_session(org) as conn:
        p = (await conn.execute(text("""select e.status, e.paused_until from app.sequence_enrollments e
            where e.subject_id = cast(:i as uuid)"""), {"i": rows["T-P"]["id"]})).first()
        d = (await conn.execute(text("select status from app.invoices where number = 'T-D'"))).scalar_one()
        kinds = (await conn.execute(text("select kind from app.approvals"))).scalars().all()
    assert p.status == "paused" and p.paused_until.date() == today + timedelta(days=7)
    assert d == "disputed" and "dispute" in kinds


# ---------- payment webhooks ----------

async def test_razorpay_webhook_signed_and_matched(org, client):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-R", today - timedelta(days=8), amount=18500)])
    async with tenant_session(org) as conn:
        invoice_id = str((await conn.execute(text("select id from app.invoices where number = 'T-R'"))).scalar_one())
    cid = await save_connection(org, provider="razorpay", account_ref="rzp_test_abc", secret={
        "key_id": "rzp_test_abc", "key_secret": "s", "webhook_secret": "whsec-test"})
    body = json.dumps({"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"notes": {"invoice_id": invoice_id}}},
        "payment": {"entity": {"id": "pay_ABC123", "amount": 1850000, "currency": "INR", "status": "captured", "notes": {}}}}}).encode()
    sig = hmac.new(b"whsec-test", body, hashlib.sha256).hexdigest()
    assert (await client.post(f"/webhooks/razorpay/{cid}", content=body, headers={"x-razorpay-signature": "bad"})).status_code == 401
    r = (await client.post(f"/webhooks/razorpay/{cid}", content=body, headers={"x-razorpay-signature": sig})).json()
    again = (await client.post(f"/webhooks/razorpay/{cid}", content=body, headers={"x-razorpay-signature": sig})).json()
    assert r["match"] == "strong" and r["duplicate"] is False and again["duplicate"] is True
    async with tenant_session(org) as conn:
        assert (await conn.execute(text("select status from app.invoices where number = 'T-R'"))).scalar_one() == "paid"


async def test_stripe_webhook_weak_match_by_customer_and_amount(org, client):
    today = datetime.now(UTC).date()
    await import_invoices(org, [inv("T-S", today - timedelta(days=8), amount=1250, email="owner@maple.example")])
    cid = await save_connection(org, provider="stripe", account_ref="Stripe", secret={"webhook_secret": "whsec_test123"})
    body = json.dumps({"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "payment_intent": "pi_1", "amount_total": 125000, "currency": "inr",
        "customer_details": {"email": "OWNER@maple.example"}, "metadata": {}}}}).encode()
    t = str(int(time.time()))
    sig = hmac.new(b"whsec_test123", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    old = str(int(time.time()) - 3600)
    stale = hmac.new(b"whsec_test123", f"{old}.".encode() + body, hashlib.sha256).hexdigest()
    assert (await client.post(f"/webhooks/stripe/{cid}", content=body, headers={"stripe-signature": f"t={old},v1={stale}"})).status_code == 401
    r = (await client.post(f"/webhooks/stripe/{cid}", content=body, headers={"stripe-signature": f"t={t},v1={sig}"})).json()
    assert r["match"] == "weak"


# ---------- reactivation (mock-data/boring-machine/old-leads.csv) ----------

async def test_reactivation_import_respects_consent_and_merges_duplicates(org):
    rows = parse_file(OLD_LEADS, "old-leads.csv")
    async with tenant_session(org) as conn:
        stats = await import_old_leads(conn, org, rows)
        elig = await eligibility(conn)
        names = {e["name"] for e in elig["eligible"]}
        rahuls = (await conn.execute(text("select count(*) from app.contacts where name like 'Rahul%' and merged_into is null"))).scalar_one()
    assert stats["rows"] == 9 and stats["opted_out"] == 1
    assert rahuls == 1  # the duplicate Rahul (different phone format and email) is one person
    assert "Elena Fernandes" not in names  # opted out
    assert "Aditya Rane" not in names  # no WhatsApp consent and no email
    assert {"Rahul Joshi", "Kavya Shetty", "Sunita Pawar"} <= names


async def test_campaign_paces_messages_one_by_one(org):
    rows = parse_file(OLD_LEADS, "old-leads.csv")
    async with tenant_session(org) as conn:
        await import_old_leads(conn, org, rows)
        r = await start_campaign(conn, org, "Diwali check-in", per_hour=6)
        slots = (await conn.execute(text("select next_run_at from app.sequence_enrollments order by next_run_at"))).scalars().all()
    assert r["enrolled"] == len(slots) >= 5
    gaps = {round((b - a).total_seconds()) for a, b in itertools.pairwise(slots)}
    assert gaps == {600}  # 6 per hour = one every 10 minutes


# ---------- speed-to-lead ----------

async def test_form_lead_gets_consent_and_first_touch(org, client):
    async with tenant_session(org) as conn:
        src = await create_source(conn, org, "Website form")
    r = await client.post(f"/hooks/leads/{src['key']}", json={"name": "Ishaan Bhatt", "phone": "+91-90000-30011",
                                                               "message": "Tooth pain, can I come today?", "whatsapp_optin": True})
    assert r.status_code == 201
    assert (await client.post("/hooks/leads/ls_nope", json={"phone": "1"})).status_code == 404
    assert (await client.post(f"/hooks/leads/{src['key']}", json={"name": "x"})).status_code == 422
    from agentry.automations.speed_to_lead import start_first_touch
    eid = await start_first_touch(org, r.json()["lead_id"])
    async with tenant_session(org) as conn:
        e = (await conn.execute(text("select next_run_at from app.sequence_enrollments where id = :e"), {"e": eid})).scalar_one()
        consent = (await conn.execute(text("select status from app.consents where channel = 'whatsapp'"))).scalar_one()
        lead = (await conn.execute(text("select owner_automation, qualification from app.leads where id = :l"),
                                   {"l": r.json()["lead_id"]})).first()
    assert consent == "granted" and lead.owner_automation == "speed_to_lead" and "Tooth pain" in lead.qualification["need"]
    assert abs((e - datetime.now(UTC)).total_seconds()) < 5  # first step offset 1 min from a start 1 min early = now


async def test_booking_completes_outbound_sequences(org):
    async with tenant_session(org) as conn:
        cid = await resolve_contact(conn, org, name="Sunita", phone="+91-90000-20002", source="t")
        await conn.execute(text("insert into app.consents (org_id, contact_id, channel, status) values (:o, :c, 'whatsapp', 'granted')"),
                           {"o": org, "c": cid})
        await conn.execute(text("insert into app.leads (org_id, contact_id, source, stage) values (:o, :c, 'old_leads', 'nurture')"),
                           {"o": org, "c": cid})
        await start_campaign(conn, org, "t", 60)
        await conn.execute(text("""insert into app.services (org_id, key, name, minutes) values (:o, 'consult', 'Consultation', 30)"""), {"o": org})
        await conn.execute(text("""insert into app.staff (org_id, name, service_keys, working_hours)
            values (:o, 'Dr X', '{consult}', '{"mon":[["10:00","18:00"]],"tue":[["10:00","18:00"]],"wed":[["10:00","18:00"]],"thu":[["10:00","18:00"]],"fri":[["10:00","18:00"]],"sat":[["10:00","18:00"]]}')"""),
            {"o": org})
    from agentry.booking import availability, book
    slots, _, _ = await availability(org, "consult", limit=1)
    await book(org, service_key="consult", start=slots[0].start, name="Sunita", phone="+91-90000-20002", source="lead_reactivation")
    async with tenant_session(org) as conn:
        e = (await conn.execute(text("select status, stop_reason from app.sequence_enrollments"))).first()
    assert e.status == "completed" and e.stop_reason == "booked"


def test_money_and_missing_link_cleanup():
    from agentry.sequences import _drop_sentences_with, _money
    assert _money(110000, "INR") == "₹1,10,000" and _money(9500, "INR") == "₹9,500" and _money(486500.4, "INR") == "₹4,86,500"
    assert _money(1250, "USD") == "USD 1,250.00"
    body = "Invoice is due. You can pay online here: [PAY_LINK]. Thanks!\nBest,\nTeam"
    assert _drop_sentences_with(body, "[PAY_LINK]") == "Invoice is due. Thanks!\nBest,\nTeam"
