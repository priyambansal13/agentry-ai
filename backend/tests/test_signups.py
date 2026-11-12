"""Self-serve start (agentry/signups.py): plans, checkout (the gateway is a stand-in), the paid webhook, the emailed link,
the claim by the portal, provisioning by the signed-in owner, and the hand-off when no gateway is set up."""
import hashlib
import hmac
import json
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

from agentry import auth as auth_mod
from agentry import signups
from agentry.config import settings
from agentry.db import system_session, tenant_session


def visitor() -> dict:
    return {"x-forwarded-for": f"10.9.{random.randint(1, 250)}.{random.randint(1, 250)}"}


BODY = {"pack": "starter", "business": "SmileCraft Dental", "website": "smilecraft.example", "name": "Neha Sharma", "phone": "+919810000011", "country": "IN"}


@pytest.fixture
def gateway(monkeypatch):
    links = []

    async def pay_link(sid, amount, currency, business, name, email, phone, pack):
        links.append((sid, amount))
        return f"https://rzp.io/l/test-{sid[:6]}"
    monkeypatch.setattr(signups, "_pay_link", pay_link)
    monkeypatch.setattr(settings, "billing_razorpay_webhook_secret", "whsec")
    sent = []
    monkeypatch.setattr("agentry.notify.email.send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return links, sent


async def pay(client, sid: str) -> None:
    ev = {"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"notes": {"signup_id": sid}}}, "payment": {"entity": {"id": "pay_123"}}}}
    raw = json.dumps(ev).encode()
    sig = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    r = await client.post("/webhooks/billing/razorpay", content=raw, headers={"x-razorpay-signature": sig, "content-type": "application/json"})
    assert r.status_code == 200, r.text


@pytest.fixture
def new_org(monkeypatch, users):
    """An organisation and its owner as the portal makes them (no settings yet)."""
    db = create_engine(settings.migrate_database_url)
    ids, made = dict(users), []

    def _decode(token: str) -> dict:
        return {"sub": ids[token], "email": token, "name": token, "platform_role": "admin" if token == "admin@agentry.dev" else "user"}
    monkeypatch.setattr(auth_mod, "_decode", _decode)

    def make(email: str) -> tuple[str, dict]:
        oid, uid = str(uuid.uuid4()), str(uuid.uuid4())
        ids[email] = uid
        with db.begin() as c:
            c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'SmileCraft Dental', :s, now())"""), {"i": oid, "s": f"sc-{oid[:8]}"})
            c.execute(text("""insert into auth."user" (id, name, email, "emailVerified", role, "createdAt", "updatedAt") values (:u, 'Neha', :e, true, 'user', now(), now())"""),
                      {"u": uid, "e": email})
            c.execute(text("""insert into auth.member (id, "organizationId", "userId", role, "createdAt") values (:i, :o, :u, 'owner', now())"""),
                      {"i": str(uuid.uuid4()), "o": oid, "u": uid})
        made.append((oid, email))
        return oid, {"Authorization": f"Bearer {email}", "X-Org-Id": oid}
    yield make
    with db.begin() as c:
        for oid, email in made:
            for t in ("automation_instances", "onboarding_progress", "pricing_plans", "audit_log", "events", "org_settings"):
                c.execute(text(f"delete from app.{t} where org_id = :i"), {"i": oid})
            c.execute(text("""delete from auth.member where "organizationId" = :i"""), {"i": oid})
            c.execute(text("delete from auth.organization where id = :i"), {"i": oid})
            c.execute(text("""delete from auth."user" where email = :e"""), {"e": email})


async def test_plans_show_the_first_payment(client):
    plans = (await client.get("/public/plans")).json()["plans"]
    starter = next(p for p in plans if p["key"] == "starter")
    assert starter["monthly"] == "2999" and starter["first_payment"] == "3538.82"  # + 18% GST
    assert "Website chat agent" in starter["agents"] and {p["key"] for p in plans} >= {"starter", "clinic-growth", "ca-firm"}


async def test_buy_open_and_set_up(client, gateway, new_org):
    links, sent = gateway
    email = f"neha-{uuid.uuid4().hex[:6]}@smilecraft.example"
    r = await client.post("/public/signups", headers=visitor(), json=BODY | {"email": email})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["pay_url"].startswith("https://rzp.io/") and str(links[0][1]) == "3538.82"
    assert (await client.get(f"/public/signups/{sid}")).json()["status"] == "pending_payment"

    await pay(client, sid)
    await pay(client, sid)  # Razorpay retries: one email only
    mails = [m for m in sent if m[0] == email]
    assert len(mails) == 1 and f"/start/{sid}?k=" in mails[0][2]
    token = mails[0][2].split("?k=")[1].split()[0]
    assert any("New self-serve customer" in m[1] for m in sent)
    assert (await client.get(f"/public/signups/{sid}?k=wrong")).status_code == 404
    info = (await client.get(f"/public/signups/{sid}?k={token}")).json()
    assert info["status"] == "paid" and info["email"] == email

    oid, h = new_org(email)
    assert (await client.post(f"/public/signups/{sid}/claim", json={"k": token, "org_id": oid})).json() == {"claimed": True}
    assert (await client.post(f"/public/signups/{sid}/claim", json={"k": token, "org_id": str(uuid.uuid4())})).json() == {"claimed": False}
    r = await client.post(f"/signups/{sid}/provision", headers=h, json={"k": token})
    assert r.status_code == 200, r.text
    async with tenant_session(oid) as conn:
        agents = set((await conn.execute(text("select template_key from app.automation_instances"))).scalars())
        plan = (await conn.execute(text("select retainer, setup_billed, pilot_until from app.pricing_plans"))).one()
        status = (await conn.execute(text("select status from app.org_settings"))).scalar_one()
    assert agents >= {"website_chat", "whatsapp_assistant", "speed_to_lead"} and status == "onboarding"
    assert float(plan.retainer) == 2999 and plan.setup_billed and plan.pilot_until is not None  # this month is paid
    async with system_session() as conn:
        assert (await conn.execute(text("select count(*) from app.events where type = 'signup.provisioned' and org_id = :o"), {"o": oid})).scalar_one() == 1
    again = await client.post(f"/signups/{sid}/provision", headers=h, json={"k": token})
    assert again.json()["status"] == "provisioned"  # a second click is harmless


async def test_only_the_payer_can_set_it_up(client, gateway, new_org):
    _links, sent = gateway
    email = f"owner-{uuid.uuid4().hex[:6]}@clinic.example"
    sid = (await client.post("/public/signups", headers=visitor(), json=BODY | {"email": email})).json()["id"]
    await pay(client, sid)
    token = next(m for m in sent if m[0] == email)[2].split("?k=")[1].split()[0]
    oid, _h = new_org(email)
    await client.post(f"/public/signups/{sid}/claim", json={"k": token, "org_id": oid})
    _other_oid, other = new_org(f"someone-{uuid.uuid4().hex[:6]}@else.example")
    assert (await client.post(f"/signups/{sid}/provision", headers=other, json={"k": token})).status_code == 409  # not the claimed org


async def test_no_gateway_hands_over_to_a_person(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_razorpay_key_id", None)
    email = f"x-{uuid.uuid4().hex[:6]}@shop.example"
    r = (await client.post("/public/signups", headers=visitor(), json=BODY | {"email": email})).json()
    assert r["handoff"] and r["pay_url"] is None
    async with system_session() as conn:
        msg = (await conn.execute(text("select message from app.demo_requests where email = :e"), {"e": email})).scalar_one()
    assert "Starter plan" in msg
    assert (await client.post("/public/signups", headers=visitor(), json=BODY | {"email": email, "pack": "nope"})).status_code == 422
