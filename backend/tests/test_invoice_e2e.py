"""Invoice follow-up, end to end, for a client that has ONLY invoice follow-up (no inbox triage, no WhatsApp assistant).
Each test is a real-world path: import -> go live -> reminders -> customer replies -> payment -> statement."""
import json
from datetime import UTC, datetime, timedelta

import httpx
from helpers import csv_bytes, enrollment_for, inv
from sqlalchemy import text

from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.connectors import http
from agentry.connectors.store import save_connection
from agentry.db import tenant_session
from agentry.sequences import next_action, send_step

TODAY = datetime.now(UTC).date()


async def go_live_invoice_client(client, team_org):
    """An invoice-only client set up the normal way: imported during onboarding, then live."""
    oid, h = await team_org(["invoice_follow_up"], live=False)
    files = {"file": ("ledger.csv", csv_bytes([inv("E-1", TODAY - timedelta(days=9)), inv("E-2", TODAY - timedelta(days=16), email="b@x.example")]), "text/csv")}
    r = (await client.post("/org/invoices/import", headers=h["owner"], files=files, data={"commit": "true"})).json()
    assert r["created"] == 2
    await save_connection(oid, provider="gmail", account_ref="accounts@client.example", secret={"refresh_token": "x"})
    assert (await client.patch("/org/profile", headers=h["owner"], json={"city": "Pune"})).status_code == 200
    r = await client.post("/org/go-live", headers=h["owner"])
    assert r.status_code == 200, r.text
    return oid, h


async def test_invoices_imported_during_setup_get_reminders_at_go_live(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)
    from agentry.automations.invoice_follow_up import enroll_on_go_live
    await enroll_on_go_live({"org_id": oid, "payload": {"automations": ["invoice_follow_up"]}})
    async with tenant_session(oid) as conn:
        n = (await conn.execute(text("select count(*) from app.sequence_enrollments where status = 'active'"))).scalar_one()
    assert n == 2


async def reminder_conversation(oid: str, number: str) -> tuple[str, str]:
    """Send the first reminder (recorded locally) and return (enrollment id, conversation external_ref)."""
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'live' where template_key = 'invoice_follow_up'"))
        await conn.execute(text("delete from app.connections where provider = 'gmail'"))  # the test mailbox can't really send
    from agentry.invoices import enroll_open
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    eid = await enrollment_for(oid, number)
    out = await send_step(oid, eid, 0)
    conv = out["results"][0]["conversation_id"]
    async with tenant_session(oid) as conn:
        ref = (await conn.execute(text("select external_ref from app.conversations where id = cast(:c as uuid)"), {"c": conv})).scalar_one()
    return eid, ref


async def test_email_reply_is_understood_without_inbox_triage(client, team_org, monkeypatch):
    oid, _h = await go_live_invoice_client(client, team_org)
    eid, ref = await reminder_conversation(oid, "E-1")
    mid = await ingest_email(oid, sender="rohan@northstar.example", subject="Re: Reminder", body="Sorry for the delay, we will pay by Friday.",
                             thread_ref=ref)
    from agentry.automations.invoice_follow_up import reminder_reply
    await reminder_reply({"org_id": oid, "payload": {"message_id": mid}})
    async with tenant_session(oid) as conn:
        status = (await conn.execute(text("select status from app.sequence_enrollments where id = cast(:e as uuid)"), {"e": eid})).scalar_one()
    assert status == "paused"  # promise to pay: reminders wait


async def test_whatsapp_reply_reaches_the_invoice_agent(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)
    _eid, _ref = await reminder_conversation(oid, "E-1")
    async with tenant_session(oid) as conn:  # the reminder also went out on WhatsApp, in the customer's WhatsApp thread
        cid = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, external_ref, metadata)
            values (:o, 'whatsapp', 'invoice_follow_up', 'WhatsApp', 'wa:919000000001', cast(:m as jsonb)) returning id"""),
            {"o": oid, "m": json.dumps({"subject_type": "invoice", "subject_id": (await conn.execute(text("select id::text from app.invoices where number = 'E-1'"))).scalar_one()})})).scalar_one())
        inv_id = (await conn.execute(text("select id::text from app.invoices where number = 'E-1'"))).scalar_one()
        await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body, metadata)
            values (:o, cast(:c as uuid), 'out', 'agent', '[template invoice_reminder]', cast(:m as jsonb))"""),
            {"o": oid, "c": cid, "m": json.dumps({"subject_type": "invoice", "subject_id": inv_id})})
    from agentry.automations.invoice_follow_up import whatsapp_reminder_reply
    await whatsapp_reminder_reply({"org_id": oid, "payload": {"conversation_id": cid, "text": "Already paid yesterday, UTR 4471", "message_id": "m"}})
    async with tenant_session(oid) as conn:
        kinds = (await conn.execute(text("select kind from app.approvals where automation_key = 'invoice_follow_up'"))).scalars().all()
    assert "payment_review" in kinds


async def test_reminders_carry_a_payment_link(client, team_org, monkeypatch):
    oid, _h = await go_live_invoice_client(client, team_org)
    made = []

    def razorpay(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        made.append(body)
        return httpx.Response(200, json={"id": "plink_1", "short_url": f"https://rzp.io/i/{body['reference_id']}"})
    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(razorpay))
    await save_connection(oid, provider="razorpay", account_ref="rzp_test_1", secret={"key_id": "rzp_test_1", "key_secret": "s", "webhook_secret": "w"})
    eid, _ref = await reminder_conversation(oid, "E-1")
    async with tenant_session(oid) as conn:
        body = (await conn.execute(text("""select m.body from app.messages m join app.conversations c on c.id = m.conversation_id
            where c.metadata->>'enrollment_id' = :e and m.direction = 'out'"""), {"e": eid})).scalar_one()
    assert made and made[0]["amount"] == 4500000 and "https://rzp.io/i/E-1" in body


async def test_approving_a_stale_reminder_after_payment_sends_nothing(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)  # approval mode after go-live
    from agentry.invoices import apply_payment, enroll_open
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    eid = await enrollment_for(oid, "E-1")
    assert (await send_step(oid, eid, 0))["results"][0]["status"] == "awaiting_approval"
    async with tenant_session(oid) as conn:
        inv_id = (await conn.execute(text("select id::text from app.invoices where number = 'E-1'"))).scalar_one()
        await apply_payment(conn, oid, invoice_id=inv_id, amount=45000, currency="INR", gateway="manual", reference="NEFT-1", match="manual")
        card = (await conn.execute(text("select id::text, status from app.approvals where kind = 'outbound_draft'"))).one()
    assert card.status != "pending"  # the reminder card is withdrawn when the invoice is paid
    from agentry.worker.delivery import deliver_outbound_draft
    async with tenant_session(oid) as conn:  # even if someone had approved it in time, nothing is sent for a paid invoice
        await conn.execute(text("update app.approvals set status = 'approved' where id = cast(:a as uuid)"), {"a": card.id})
    assert (await deliver_outbound_draft(oid, card.id))["status"] == "skipped"


async def test_pause_really_pauses(client, team_org):
    oid, h = await go_live_invoice_client(client, team_org)
    from agentry.invoices import enroll_open
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
        inv_id = (await conn.execute(text("select id::text from app.invoices where number = 'E-2'"))).scalar_one()
    assert (await client.post(f"/org/invoices/{inv_id}/reminders/pause", headers=h["owner"])).json()["updated"] == 1
    plan = await next_action(oid, await enrollment_for(oid, "E-2"))
    assert plan["action"] == "wait" and plan["reason"] == "paused"


def test_opt_out_is_not_any_stop():
    from agentry.automations.invoice_follow_up import _heuristic
    assert _heuristic("Please don't stop the service, we will pay by Friday")["label"] == "promise_to_pay"
    assert _heuristic("STOP")["label"] == "opt_out"
    assert _heuristic("Please remove me from these emails")["label"] == "opt_out"


async def test_questions_reach_a_person(client, team_org):
    oid, _h = await go_live_invoice_client(client, team_org)
    from agentry.automations.invoice_follow_up import act_on_reply
    async with tenant_session(oid) as conn:
        row = (await conn.execute(text("select id::text as id, number, contact_id::text as contact_id from app.invoices where number = 'E-1'"))).mappings().one()
    for label, reply in (("resend_invoice", "Can you resend the invoice? I can't find it."), ("other", "Can we pay in two parts?"),
                         ("partial_payment", "Paying half now, rest next month")):
        await act_on_reply(oid, dict(row), None, reply, {"label": label}, 1)
    async with tenant_session(oid) as conn:
        cards = (await conn.execute(text("select title from app.approvals where automation_key = 'invoice_follow_up'"))).scalars().all()
    assert len(cards) == 3, cards


async def live_client(team_org):
    oid, h = await team_org(["invoice_follow_up"])
    return oid, h


async def import_rows(client, h, rows):
    files = {"file": ("ledger.csv", csv_bytes(rows), "text/csv")}
    return (await client.post("/org/invoices/import", headers=h["owner"], files=files, data={"commit": "true"})).json()


async def test_dispute_then_reopen_or_write_off(client, team_org):
    from agentry.automations.invoice_follow_up import act_on_reply
    oid, h = await live_client(team_org)
    await import_rows(client, h, [inv("D-1", TODAY - timedelta(days=9)), inv("D-2", TODAY - timedelta(days=9), email="z@x.example")])
    async with tenant_session(oid) as conn:
        rows = {r["number"]: dict(r) for r in (await conn.execute(text("select id::text as id, number, contact_id::text as contact_id from app.invoices"))).mappings()}
    for n in ("D-1", "D-2"):
        await act_on_reply(oid, rows[n], None, "the amount is wrong", {"label": "dispute", "reason": "wrong amount"}, 1)
    assert (await client.post(f"/org/invoices/{rows['D-1']['id']}/status", headers=h["viewer"], json={"action": "reopen"})).status_code == 403
    assert (await client.post(f"/org/invoices/{rows['D-1']['id']}/status", headers=h["finance"], json={"action": "reopen", "note": "credit note sent"})).json()["status"] == "open"
    assert (await client.post(f"/org/invoices/{rows['D-2']['id']}/status", headers=h["owner"], json={"action": "write_off"})).json()["status"] == "written_off"
    async with tenant_session(oid) as conn:
        open_disputes = (await conn.execute(text("select count(*) from app.approvals where kind = 'dispute' and status = 'pending'"))).scalar_one()
        active = (await conn.execute(text("""select count(*) from app.sequence_enrollments e join app.invoices i on i.id = e.subject_id
            where i.number = 'D-1' and e.status = 'active'"""))).scalar_one()
    assert open_disputes == 0 and active == 1  # reopened: reminders run again


async def test_customer_says_paid_and_unmatched_payment(client, team_org):
    from agentry.automations.invoice_follow_up import act_on_reply
    from agentry.invoices import apply_payment
    oid, h = await live_client(team_org)
    await import_rows(client, h, [inv("P-1", TODAY - timedelta(days=9)), inv("P-2", TODAY - timedelta(days=9), amount=12000, email="u@x.example")])
    async with tenant_session(oid) as conn:
        rows = {r["number"]: dict(r) for r in (await conn.execute(text("select id::text as id, number, contact_id::text as contact_id from app.invoices"))).mappings()}
    await act_on_reply(oid, rows["P-1"], None, "Paid yesterday, UTR 99812", {"label": "already_paid", "utr": "99812"}, 1)
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select id::text from app.approvals where kind = 'payment_review'"))).scalar_one()
        await apply_payment(conn, oid, invoice_id=None, amount=12000, currency="INR", gateway="razorpay", reference="pay_X", match="unmatched")
        unmatched = (await conn.execute(text("select id::text from app.approvals where kind = 'payment_review' and payload ? 'payment_id'"))).scalar_one()
    assert (await client.post("/org/payments/confirm", headers=h["finance"], json={"approval_id": card})).json() == {"confirmed": True}
    assert (await client.post("/org/payments/confirm", headers=h["finance"], json={"approval_id": unmatched})).status_code == 422
    assert (await client.post("/org/payments/confirm", headers=h["finance"], json={"approval_id": unmatched, "invoice_id": rows["P-2"]["id"]})).status_code == 200
    async with tenant_session(oid) as conn:
        st = dict((await conn.execute(text("select number, status from app.invoices"))).all())
    assert st == {"P-1": "paid", "P-2": "paid"}


async def test_payment_for_a_closed_invoice_goes_to_review(team_org):
    from agentry.invoices import apply_payment
    oid, _h = await live_client(team_org)
    async with tenant_session(oid) as conn:
        await conn.execute(text("""insert into app.invoices (org_id, number, currency, amount, amount_paid, due_on, status, source)
            values (:o, 'C-1', 'INR', 5000, 5000, current_date, 'paid', 'test')"""), {"o": oid})
        iid = (await conn.execute(text("select id::text from app.invoices where number = 'C-1'"))).scalar_one()
        await apply_payment(conn, oid, invoice_id=iid, amount=5000, currency="INR", gateway="razorpay", reference="pay_dup", match="strong")
        card = (await conn.execute(text("select title from app.approvals where kind = 'payment_review'"))).scalar_one()
    assert "already paid" in card


async def test_reminders_ended_card_and_timezone(team_org):
    from agentry.invoices import enroll_open
    from agentry.sequences import _anchor, next_action
    oid, _h = await live_client(team_org)
    async with tenant_session(oid) as conn:
        await conn.execute(text("""insert into app.contacts (org_id, name, email, phone_e164) values (:o, 'Rohan', 'r@x.example', '+919000000009')"""), {"o": oid})
        cid = (await conn.execute(text("select id from app.contacts where email = 'r@x.example'"))).scalar_one()
        await conn.execute(text("""insert into app.invoices (org_id, contact_id, number, currency, amount, due_on, status, source)
            values (:o, :c, 'L-1', 'INR', 9000, current_date - 40, 'open', 'test')"""), {"o": oid, "c": cid})
        await enroll_open(conn, oid)
    eid = await enrollment_for(oid, "L-1")
    async with tenant_session(oid) as conn:  # the final reminder is still waiting for approval: not "finished" yet
        await conn.execute(text("""update app.sequence_enrollments set last_step = 3,
            log = '[{"step": 3, "results": [{"channel": "email", "status": "awaiting_approval"}]}]' where id = cast(:e as uuid)"""), {"e": eid})
    assert (await next_action(oid, eid))["reason"] == "all steps sent"
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.approvals where kind = 'escalation'"))).scalar_one() == 0
        await conn.execute(text("""update app.sequence_enrollments set status = 'active',
            log = '[{"step": 3, "results": [{"channel": "email", "status": "sent"}]}]' where id = cast(:e as uuid)"""), {"e": eid})
    assert (await next_action(oid, eid))["reason"] == "all steps sent"
    await next_action(oid, eid)  # once only
    async with tenant_session(oid) as conn:
        cards = (await conn.execute(text("select title, payload from app.approvals where kind = 'escalation'"))).all()
    assert len(cards) == 1 and "Reminders finished: invoice L-1" in cards[0][0] and cards[0][1]["phone"] == "+919000000009"
    from agentry.invoices import withdraw_reminder_cards
    async with tenant_session(oid) as conn:  # disputed (or paid): no call needed any more
        iid = (await conn.execute(text("select id::text from app.invoices where number = 'L-1'"))).scalar_one()
        await withdraw_reminder_cards(conn, iid, "disputed")
        assert (await conn.execute(text("select count(*) from app.approvals where kind = 'escalation' and status = 'pending'"))).scalar_one() == 0
    e = {"timezone": "Asia/Kolkata", "next_run_at": None, "created_at": datetime.now(UTC)}
    at = _anchor(e, {"due_on": TODAY}, {"anchor": "due"})
    assert at.hour == 4 and at.minute == 30  # 10:00 in India is 04:30 UTC


async def test_payment_link_follows_the_balance_and_stripe(team_org, monkeypatch):
    from decimal import Decimal

    from agentry.invoices import payment_link
    oid, _h = await live_client(team_org)
    calls = []

    def provider(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "razorpay" in str(req.url):
            body = json.loads(req.content)
            return httpx.Response(200, json={"short_url": f"https://rzp.io/i/{body['reference_id']}"})
        if req.url.path == "/v1/prices":
            return httpx.Response(200, json={"id": "price_1"})
        return httpx.Response(200, json={"url": "https://buy.stripe.com/test_123"})
    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(provider))
    await save_connection(oid, provider="razorpay", account_ref="rzp_1", secret={"key_id": "rzp_1", "key_secret": "s"})
    invoice = {"id": "00000000-0000-0000-0000-000000000001", "number": "L-9", "amount": Decimal(10000), "amount_paid": Decimal(0), "currency": "INR"}
    async with tenant_session(oid) as conn:
        first = await payment_link(conn, oid, invoice)
        again = await payment_link(conn, oid, invoice | {"payment_link": first, "payment_link_amount": Decimal(10000)})
        after_part = await payment_link(conn, oid, invoice | {"amount_paid": Decimal(4000), "payment_link": first, "payment_link_amount": Decimal(10000)})
    assert first == again and after_part != first and len([c for c in calls if "razorpay" in c]) == 2  # a new link for the new balance
    await save_connection(oid, provider="stripe", account_ref="Stripe", secret={"webhook_secret": "whsec_x", "secret_key": "sk_test_1"})
    async with tenant_session(oid) as conn:
        usd = await payment_link(conn, oid, invoice | {"currency": "USD", "number": "US-1"})
    assert usd == "https://buy.stripe.com/test_123"


async def test_import_reports_no_contact_and_records_whatsapp_consent(client, team_org):
    from agentry.leads import can_contact
    oid, h = await live_client(team_org)
    rows = [inv("W-1", TODAY - timedelta(days=9)) | {"WhatsApp consent": "yes"},
            {"Invoice": "W-2", "Company": "Nobody Ltd", "Contact": "", "Email": "", "Phone": "", "Amount": 100, "Amount paid": 0,
             "Due date": (TODAY - timedelta(days=9)).isoformat(), "WhatsApp consent": ""}]
    r = await import_rows(client, h, rows)
    assert r["no_contact"] == 1
    async with tenant_session(oid) as conn:
        contact = (await conn.execute(text("select contact_id from app.invoices where number = 'W-1'"))).scalar_one()
        assert (await can_contact(conn, str(contact), "whatsapp"))[0] is True
    listed = {i["number"]: i["contactable"] for i in (await client.get("/org/invoices", headers=h["owner"])).json()["items"]}
    assert listed == {"W-1": True, "W-2": False}


async def test_reminders_continue_the_same_gmail_thread(team_org, monkeypatch):
    from fakes import FakeProviders

    from agentry.config import settings
    oid, _h = await live_client(team_org)
    f = FakeProviders(mailbox="accounts@client.example")
    sent = []
    orig = f.gmail

    def gmail(req, path, m):
        if path.startswith("/messages/send"):
            body = json.loads(req.content)
            sent.append(body)
            return httpx.Response(200, json={"id": f"s{len(sent)}", "threadId": body.get("threadId", "T-REM")})
        return orig(req, path, m)
    f.gmail = gmail
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "s")
    await save_connection(oid, provider="gmail", account_ref="accounts@client.example", secret={"refresh_token": "rt"})
    from agentry.invoices import enroll_open
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'live' where template_key = 'invoice_follow_up'"))
        await conn.execute(text("""insert into app.contacts (org_id, name, email, email_norm) values (:o, 'Rohan', 'r2@x.example', 'r2@x.example')"""), {"o": oid})
        cid = (await conn.execute(text("select id from app.contacts where email = 'r2@x.example'"))).scalar_one()
        await conn.execute(text("""insert into app.invoices (org_id, contact_id, number, currency, amount, due_on, status, source)
            values (:o, :c, 'G-1', 'INR', 9000, current_date - 15, 'open', 'test')"""), {"o": oid, "c": cid})
        await enroll_open(conn, oid)
    eid = await enrollment_for(oid, "G-1")
    first = await send_step(oid, eid, 0)
    second = await send_step(oid, eid, 1)
    assert len(sent) == 2, (first, second)
    assert "threadId" not in sent[0] and sent[1]["threadId"] == "T-REM"  # the second reminder continues the first thread
    async with tenant_session(oid) as conn:
        convs = (await conn.execute(text("select count(*), max(contact_id::text) from app.conversations where metadata->>'enrollment_id' = :e"), {"e": eid})).one()
    assert convs[0] == 1 and convs[1] == str(cid)  # one conversation, with the customer on it


async def test_no_whatsapp_card_when_whatsapp_cannot_send(client, team_org):
    """Approving a WhatsApp reminder must never silently do nothing: no card while WhatsApp isn't connected, and a card
    left over from before a disconnect can't be approved (it says why)."""
    from agentry.invoices import enroll_open
    from agentry.leads import record_consent
    oid, h = await go_live_invoice_client(client, team_org)
    async with tenant_session(oid) as conn:
        contact = (await conn.execute(text("select contact_id::text from app.invoices where number = 'E-1'"))).scalar_one()
        await record_consent(conn, oid, contact, "whatsapp", True, "import")
        await enroll_open(conn, oid)
    eid = await enrollment_for(oid, "E-1")
    out = await send_step(oid, eid, 1)  # "polite": email + WhatsApp
    assert [(r["channel"], r["status"]) for r in out["results"]] == [("email", "awaiting_approval"), ("whatsapp", "skipped")]
    assert out["results"][1]["reason"] == "WhatsApp not connected"
    wa = await save_connection(oid, provider="whatsapp", account_ref="pn-inv-1", secret={"access_token": "t"})
    out = await send_step(oid, eid, 2)
    assert [r["status"] for r in out["results"]] == ["awaiting_approval", "awaiting_approval"]
    async with tenant_session(oid) as conn:  # WhatsApp disconnected while the card waits
        await conn.execute(text("update app.connections set status = 'revoked' where id = cast(:c as uuid)"), {"c": wa})
    items = (await client.get("/org/approvals", headers=h["finance"])).json()["items"]
    card = next(i for i in items if i["kind"] == "outbound_draft" and i["payload"]["channel"] == "whatsapp")
    assert card["channel_problem"] == "WhatsApp not connected"
    assert all(i["channel_problem"] is None for i in items if i["kind"] == "outbound_draft" and i["payload"]["channel"] == "email")
    r = await client.post(f"/org/approvals/{card['id']}", headers=h["finance"], json={"action": "approve"})
    assert r.status_code == 409 and "WhatsApp not connected" in r.json()["detail"]
    assert (await client.post(f"/org/approvals/{card['id']}", headers=h["finance"], json={"action": "reject"})).status_code == 200
