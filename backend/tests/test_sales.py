"""Agentry's own sales pipeline: a website demo request worked in HQ (demo, send, follow-ups, win), mirrored as a lead in
Agentry's own organisation."""
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import create_engine, text

from agentry import sales
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.worker import sales_jobs


async def lead_stage(lead_id: str) -> str:
    async with system_session() as conn:
        org = await sales.agentry_org_id(conn)
    async with tenant_session(org) as conn:
        return (await conn.execute(text("select stage from app.leads where id = cast(:l as uuid)"), {"l": lead_id})).scalar_one()


async def cleanup(demo_id: str, org_id: str | None) -> None:
    """Leave no test prospects in HQ or in Agentry's own leads."""
    async with system_session() as conn:
        d = (await conn.execute(text("select lead_id from app.demo_requests where id = cast(:i as uuid)"), {"i": demo_id})).first()
        if d and d.lead_id:
            contact = (await conn.execute(text("delete from app.leads where id = :l returning contact_id"), {"l": d.lead_id})).scalar_one()
            await conn.execute(text("delete from app.contacts where id = :c"), {"c": contact})
        await conn.execute(text("delete from app.events where payload->>'demo_request_id' = :i"), {"i": demo_id})
        await conn.execute(text("delete from app.demo_requests where id = cast(:i as uuid)"), {"i": demo_id})
    if org_id:
        with create_engine(settings.migrate_database_url).begin() as c:
            c.execute(text("delete from auth.organization where id = :i"), {"i": org_id})


async def test_demo_request_pipeline(client, login, monkeypatch):
    demo_id, org_id = None, None
    try:
        demo_id, org_id = await run_pipeline(client, login, monkeypatch)
    finally:
        if demo_id is None:  # failed before returning: find it by the test address
            async with system_session() as conn:
                demo_id = (await conn.execute(text("select id::text from app.demo_requests where email like 'owner-%@bright-smiles.example' order by created_at desc limit 1"))).scalar()
        if demo_id:
            await cleanup(demo_id, org_id)


async def run_pipeline(client, login, monkeypatch) -> tuple[str, str]:
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr("agentry.api.routes.hq.send_email", lambda to, s, b: sent.append((to, s, b)))
    monkeypatch.setattr(sales_jobs, "send_email", lambda to, s, b: sent.append((to, s, b)))
    monkeypatch.setattr(settings, "sales_signature", "Priya, Agentry")
    monkeypatch.setattr(settings, "web_url", "http://localhost:3200")
    staff = login("admin@agentry.dev")
    email = f"owner-{uuid.uuid4().hex[:6]}@bright-smiles.example"
    r = await client.post("/public/demo-requests", json={"name": "Anita Rao", "email": email, "company": "Bright Smiles",
                                                         "website": "https://bright-smiles.example", "niche": "clinic_or_appointments"})
    demo_id = r.json()["id"]

    # the prospect's confirmation is personal and signed; the request becomes a lead in Agentry's own organisation
    subject, body = sales.confirmation_email(await sales.get(demo_id))
    assert subject == "Your Agentry demo for Bright Smiles" and "Hi Anita" in body and body.endswith("Priya, Agentry")
    lead = await sales.mirror_lead(demo_id)
    assert lead and await sales.mirror_lead(demo_id) == lead and await lead_stage(lead) == "new"

    # HQ only
    assert (await client.get(f"/hq/demo-requests/{demo_id}", headers=login("riya@sharmadigital.example"))).status_code == 403
    d = (await client.get(f"/hq/demo-requests/{demo_id}", headers=staff)).json()
    assert d["status"] == "new" and d["suggested_pack"] == "dental-clinic" and d["demo_url"] is None
    assert (await client.post(f"/hq/demo-requests/{demo_id}/send", headers=staff, json={})).status_code == 409  # no demo yet

    # "Build demo" links the demo organisation: status demo_built, link known, lead contacted
    org_id, slug = str(uuid.uuid4()), f"bright-smiles-{uuid.uuid4().hex[:4]}"
    with create_engine(settings.migrate_database_url).begin() as c:
        c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Bright Smiles', :s, now())"""), {"i": org_id, "s": slug})
    d = (await client.patch(f"/hq/demo-requests/{demo_id}", headers=staff, json={"demo_org_id": org_id})).json()
    assert d["status"] == "demo_built" and d["demo_slug"] == slug and await lead_stage(lead) == "contacted"

    # preview, then send: the email has the demo link and the video; follow-ups get scheduled
    p = (await client.post(f"/hq/demo-requests/{demo_id}/preview-email", headers=staff,
                           json={"video_url": "https://loom.com/share/abc"})).json()
    assert f"/demo/{slug}" in p["body"] and "loom.com/share/abc" in p["body"] and p["to"] == email
    assert (await client.post(f"/hq/demo-requests/{demo_id}/send", headers=staff, json={"video_url": "javascript:x"})).status_code == 422
    # a demo link that only works on this computer is never sent
    blocked = await client.post(f"/hq/demo-requests/{demo_id}/send", headers=staff, json={})
    assert blocked.status_code == 409 and "AGENTRY_WEB_URL" in blocked.json()["detail"] and not sent
    monkeypatch.setattr(settings, "web_url", "https://agentry.example")
    d = (await client.post(f"/hq/demo-requests/{demo_id}/send", headers=staff, json={"video_url": "https://loom.com/share/abc"})).json()
    assert d["status"] == "demo_sent" and sent[-1][0] == email and f"/demo/{slug}" in sent[-1][2]
    async with system_session() as conn:
        assert (await conn.execute(text("select count(*) from app.events where type = 'demo.sent' and payload->>'demo_request_id' = :i"),
                                   {"i": demo_id})).scalar_one() == 1

    # follow-ups: day 2, 5, 10 after sending, only while they haven't replied
    assert (await sales_jobs.follow_up_plan(demo_id))["action"] == "wait"
    async with system_session() as conn:
        await conn.execute(text("update app.demo_requests set demo_sent_at = now() - interval '3 days' where id = cast(:i as uuid)"), {"i": demo_id})
    assert (await sales_jobs.follow_up_plan(demo_id))["action"] == "send"
    assert await sales_jobs.send_follow_up(demo_id) is True and sent[-1][1].startswith("Re: Your Agentry demo")
    assert await sales_jobs.send_follow_up(demo_id) is False  # the day-5 one isn't due yet
    plan = await sales_jobs.follow_up_plan(demo_id)
    assert plan["action"] == "wait" and 1.5 * 86400 < plan["seconds"] < 2.5 * 86400

    # they reply -> in talks: follow-ups stop, the lead is engaged
    await client.patch(f"/hq/demo-requests/{demo_id}", headers=staff, json={"status": "in_talks", "notes": "Wants WhatsApp first"})
    assert (await sales_jobs.follow_up_plan(demo_id))["action"] == "done" and await lead_stage(lead) == "engaged"
    assert (await client.patch(f"/hq/demo-requests/{demo_id}", headers=staff, json={"status": "maybe"})).status_code == 422

    # converted to a client -> won
    d = (await client.patch(f"/hq/demo-requests/{demo_id}", headers=staff, json={"client_org_id": org_id})).json()
    assert d["status"] == "won" and d["notes"] == "Wants WhatsApp first" and await lead_stage(lead) == "won"
    return demo_id, org_id


def test_follow_up_schedule():
    sent_at = datetime(2026, 10, 1, 10, tzinfo=UTC)
    d = {"status": "demo_sent", "demo_sent_at": sent_at, "followups_sent": 0}
    assert sales.next_follow_up(d, sent_at + timedelta(days=1))[0] == "wait"
    assert sales.next_follow_up(d, sent_at + timedelta(days=2))[0] == "send"
    assert sales.next_follow_up(d | {"followups_sent": 2}, sent_at + timedelta(days=9))[0] == "wait"
    assert sales.next_follow_up(d | {"followups_sent": 3}, sent_at + timedelta(days=30))[0] == "done"
    assert sales.next_follow_up(d | {"status": "lost"}, sent_at + timedelta(days=3))[0] == "done"


SNAPSHOT = {"business": "Glow Clinic", "contact": "Meera Shah", "date": "25 October 2026", "preparedBy": "Agentry Admin",
            "lost": "₹90,000", "leads": 150, "missed": 45, "closePct": 25, "lostCustomers": "11.3", "valuePerCustomer": "₹8,000",
            "cards": [], "agents": ["Website chat agent", "AI receptionist"], "modelLabel": "Setup + monthly retainer",
            "investment": [{"label": "One-time setup", "amount": "₹15,000"}, {"label": "Monthly retainer", "amount": "₹4,999 / month"}],
            "gstNote": True, "startSmall": False}


async def new_request(status: str = "demo_sent") -> tuple[str, str]:
    email = f"meera-{uuid.uuid4().hex[:6]}@glow-clinic.example"
    async with system_session() as conn:
        demo_id = str((await conn.execute(text("""insert into app.demo_requests (name, email, company, status, demo_sent_at)
            values ('Meera Shah', :e, 'Glow Clinic', :s, now()) returning id"""), {"e": email, "s": status})).scalar_one())
    return demo_id, email


async def test_send_proposal_and_track_views(client, login, monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr("agentry.api.routes.hq.send_email", lambda to, s, b: sent.append((to, s, b)))
    monkeypatch.setattr(settings, "web_url", "https://agentry.example")
    demo_id, email = await new_request()
    staff = login("admin@agentry.dev")
    try:
        body = {"email": email, "snapshot": SNAPSHOT, "plan": {"currency": "INR", "retainer": 4999}, "note": "As discussed on the call.",
                "demo_request_id": demo_id}
        assert (await client.post("/hq/proposals", headers=login("riya@sharmadigital.example"), json=body)).status_code == 403
        assert (await client.post("/hq/proposals", headers=staff, json=body | {"snapshot": SNAPSHOT | {"agents": []}})).status_code == 422
        r = (await client.post("/hq/proposals", headers=staff, json=body)).json()
        token = r["url"].rsplit("/", 1)[1]
        assert r["url"].startswith("https://agentry.example/proposal/") and len(token) > 20
        to, subject, text_ = sent[-1]
        assert to == email and subject == "Agentry proposal for Glow Clinic" and r["url"] in text_ and "₹4,999 / month" in text_
        assert "As discussed on the call." in text_ and "Hi Meera" in text_
        # a proposal means you're talking: the request leaves "demo sent" (no more demo follow-ups)
        assert (await sales.get(demo_id))["status"] == "in_talks"
        # the client opens it (public, no sign-in): exact snapshot; the first view alerts the team once
        for _ in range(2):
            v = await client.get(f"/public/proposals/{token}")
            assert v.status_code == 200 and v.json()["snapshot"] == SNAPSHOT
        assert (await client.get("/public/proposals/not-a-real-token")).status_code == 404
        async with system_session() as conn:
            assert (await conn.execute(text("select count(*) from app.events where type = 'proposal.viewed' and payload->>'proposal_id' = :p"),
                                       {"p": r["id"]})).scalar_one() == 1
        d = (await client.get(f"/hq/demo-requests/{demo_id}", headers=staff)).json()
        assert d["proposals"][0]["views"] == 2 and d["proposals"][0]["first_viewed_at"]
        # never send a link that only works on this computer
        monkeypatch.setattr(settings, "web_url", "http://localhost:3200")
        assert (await client.post("/hq/proposals", headers=staff, json=body)).status_code == 409
    finally:
        async with system_session() as conn:
            await conn.execute(text("delete from app.events where payload->>'proposal_id' in (select id::text from app.proposals where demo_request_id = cast(:i as uuid))"), {"i": demo_id})
            await conn.execute(text("delete from app.proposals where demo_request_id = cast(:i as uuid)"), {"i": demo_id})
            await conn.execute(text("delete from app.demo_requests where id = cast(:i as uuid)"), {"i": demo_id})


def mail(frm: str, subject: str, body: str, *, mid: str | None = None, **headers) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "agentry@example.com", subject
    m["Message-ID"] = mid or f"<{uuid.uuid4().hex}@mail.example>"
    m["Date"] = "Sun, 25 Oct 2026 12:00:00 +0530"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m


async def test_replies_found_in_the_sales_inbox(monkeypatch):
    from agentry import sales_inbox
    alerts: list[tuple[str, str, str]] = []
    monkeypatch.setattr(sales_jobs, "send_email", lambda to, s, b: alerts.append((to, s, b)))
    demo_id, email = await new_request("demo_sent")
    other_id, other = await new_request("demo_built")
    try:
        reply = mail(f"Meera Shah <{email.upper()}>", "Re: Your Agentry demo for Glow Clinic is ready",
                     "Looks great! Can we talk Thursday at 4?\n\nOn Sun, 25 Oct 2026 Agentry wrote:\n> Your demo is ready")
        msgs = [reply,
                mail(other, "Automatic reply: Your Agentry demo", "I'm away until Monday.", Auto_Submitted="auto-replied"),
                mail("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification (Failure)",
                     f"Your message wasn't delivered to {other} because the address couldn't be found."),
                mail("someone@else.example", "Unrelated", "Hello")]
        new = await sales_inbox.process(msgs)
        assert sorted(m["kind"] for m in new) == ["auto_reply", "bounce", "reply"]
        assert await sales_inbox.process(msgs) == []  # each message is recorded once
        got = next(m for m in new if m["kind"] == "reply")
        assert got["snippet"] == "Looks great! Can we talk Thursday at 4?"  # quoted text dropped
        for m in new:
            await sales_jobs.act_on_message(m)
        assert (await sales.get(demo_id))["status"] == "in_talks"  # a real reply stops the follow-ups
        assert (await sales_jobs.follow_up_plan(demo_id))["action"] == "done"
        assert (await sales.get(other_id))["status"] == "demo_built"  # out-of-office and bounces don't change the status
        subjects = [a[1] for a in alerts]
        assert any("Glow Clinic replied" in s for s in subjects) and any("bounced" in s for s in subjects) and len(alerts) == 2
    finally:
        async with system_session() as conn:
            await conn.execute(text("delete from app.demo_requests where id = any(cast(:i as uuid[]))"), {"i": [demo_id, other_id]})
