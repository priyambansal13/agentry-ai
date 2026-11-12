"""The free website audit (agentry/site_audit.py, /public/audits): limits, cache, budget, captcha, the score and the
report, and the lead it makes in Agentry HQ. The site and the assistants are stand-ins (no network, no cost)."""
import random
import uuid

import pytest
from sqlalchemy import text

from agentry import site_audit
from agentry.automations import local_seo
from agentry.config import settings
from agentry.db import system_session

HOME = """<html><head><title>Brightsmile Dental | Indiranagar</title><meta name="description" content="Dentist in Indiranagar"></head>
<body><h1>Brightsmile Dental</h1><p>Call +91 98450 12345</p><a href="https://wa.me/919845012345">WhatsApp</a></body></html>"""


@pytest.fixture(autouse=True)
def stand_in_site(monkeypatch):
    async def crawl(url, max_pages=12):
        return [local_seo.page_facts(HOME, url, 300)], {"https": True, "broken": [], "robots.txt": True, "sitemap.xml": False}
    monkeypatch.setattr(local_seo, "crawl", crawl)
    monkeypatch.setattr("agentry.knowledge._check_public", lambda url: None)
    monkeypatch.setattr(settings, "audit_daily_budget_usd", 1000.0)  # earlier runs' queued audits share the database: tests set their own budget


def visitor() -> dict:
    return {"x-forwarded-for": f"10.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"}


def site() -> str:
    return f"brightsmile-{uuid.uuid4().hex[:8]}.example"


async def test_audit_report_and_lead(client):
    ip, url = visitor(), site()
    r = await client.post("/public/audits", headers=ip, json={"url": url, "city": "Bengaluru", "service": "dentist", "source": "utm_source=google"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    again = (await client.post("/public/audits", headers=visitor(), json={"url": f"https://www.{url}/", "city": "bengaluru", "service": "Dentist"})).json()
    assert again["id"] == aid and again["cached"] is True  # same site today: the same report
    assert (await client.get(f"/public/audits/{aid}")).json()["status"] == "queued"

    out = await site_audit.run(aid)
    assert out["status"] == "done" and 0 < out["score"] <= 100
    reach = out["parts"]["reach"]
    assert reach["whatsapp"] and reach["phone"] and not reach["chat"] and reach["points"] == 13
    assert out["name"] == "Brightsmile Dental" and out["parts"]["assistants"]["asked"] == settings.audit_questions * 2
    titles = [p["title"] for p in out["problems"]]
    assert any("No instant answers" in t for t in titles)

    pub = (await client.get(f"/public/audits/{aid}")).json()
    assert pub["status"] == "done" and pub["unlocked"] is False and "answers" not in pub
    assert isinstance(pub["parts"]["website"]["issues"], int)  # count only until they leave their details
    assert (await client.post(f"/public/audits/{aid}/report", headers=ip, json={"name": "Asha Rao", "email": "not-an-email"})).status_code == 422
    r = await client.post(f"/public/audits/{aid}/report", headers=ip, json={"name": "Asha Rao", "email": "asha@brightsmile.example", "phone": "+919845012345"})
    assert r.status_code == 200 and r.json()["demo_request_id"]
    full = (await client.get(f"/public/audits/{aid}")).json()
    assert full["unlocked"] is True and len(full["answers"]) == settings.audit_questions * 2 and isinstance(full["parts"]["website"]["issues"], list)
    async with system_session() as conn:
        d = (await conn.execute(text("select company, niche, message from app.demo_requests where id = cast(:i as uuid)"), {"i": r.json()["demo_request_id"]})).first()
        ev = (await conn.execute(text("select count(*) from app.events where type = 'site_audit.unlocked' and payload->>'audit_id' = :a"), {"a": aid})).scalar_one()
    assert d.company == "Brightsmile Dental" and d.niche == "clinic_or_appointments" and "/audit/r/" in d.message and "utm_source=google" in d.message
    assert ev == 1
    subject, body = site_audit.report_email("Asha Rao", {**(await _row(aid))})
    assert "/100" in subject and f"/audit/r/{aid}" in body


async def _row(aid):
    async with system_session() as conn:
        return dict((await conn.execute(text("select *, id::text as id from app.site_audits where id = cast(:i as uuid)"), {"i": aid})).mappings().first())


async def test_limits_captcha_and_bad_addresses(client, monkeypatch):
    ip = visitor()
    for _ in range(3):
        assert (await client.post("/public/audits", headers=ip, json={"url": site(), "city": "Pune", "service": "AC repair"})).status_code == 201
    r = await client.post("/public/audits", headers=ip, json={"url": site(), "city": "Pune", "service": "AC repair"})
    assert r.status_code == 429
    assert (await client.post("/public/audits", headers=visitor(), json={"url": "localhost", "city": "Pune", "service": "AC repair"})).status_code == 422
    assert (await client.post("/public/audits", headers=visitor(), json={"url": site(), "city": "Pune", "service": "AC", "company_url": "x"})).status_code == 422
    monkeypatch.setattr(settings, "turnstile_secret", "set")
    assert (await client.post("/public/audits", headers=visitor(), json={"url": site(), "city": "Pune", "service": "AC repair"})).status_code == 400
    assert (await client.get(f"/public/audits/{uuid.uuid4()}")).status_code == 404
    assert (await client.get("/public/audits/not-a-uuid")).status_code == 404


async def test_over_the_daily_budget_it_waits(client, monkeypatch):
    monkeypatch.setattr(settings, "audit_daily_budget_usd", 0.0)
    r = (await client.post("/public/audits", headers=visitor(), json={"url": site(), "city": "Mumbai", "service": "CA firm"})).json()
    assert r["busy"] is True
    assert (await client.get(f"/public/audits/{r['id']}")).json()["waiting"] is True
    assert await site_audit.release_waiting() == 0  # still no room
    monkeypatch.setattr(settings, "audit_daily_budget_usd", 1000.0)
    assert await site_audit.release_waiting() >= 1
    assert (await client.get(f"/public/audits/{r['id']}")).json()["waiting"] is False


async def test_instant_demo_answers_from_the_website(client, monkeypatch):
    from agentry import knowledge
    page = knowledge.Page(url="https://brightsmile.example/", title="Brightsmile Dental | Indiranagar",
                          text="Brightsmile Dental in Indiranagar. Open Monday to Saturday 10 am to 8 pm. Book an appointment online. " * 5,
                          meta={"theme-color": "#0f766e"})

    async def crawl(url, max_pages=8, timeout=10.0):
        return [page]
    monkeypatch.setattr(knowledge, "crawl", crawl)
    ip = visitor()
    r = await client.post("/public/try", headers=ip, json={"url": site()})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    d = (await client.get(f"/public/try/{did}")).json()
    assert d["name"] == "Brightsmile Dental" and d["brand"]["color"] == "#0f766e" and d["messages_left"] == 30
    assert "Can I book for tomorrow evening?" in d["suggestions"]
    m = await client.post(f"/public/try/{did}/messages", headers=ip, json={"messages": [{"role": "user", "content": "Are you open on Sunday?"}]})
    assert m.status_code == 200 and "Brightsmile Dental" in m.json()["reply"] and m.json()["messages_left"] == 29
    assert (await client.post(f"/public/try/{did}/messages", headers=ip, json={"messages": [{"role": "system", "content": "x"}]})).status_code == 422
    assert (await client.post("/public/try", headers=ip, json={"url": site()})).status_code == 201
    assert (await client.post("/public/try", headers=ip, json={"url": site()})).status_code == 429  # 2 a day per visitor
    async with system_session() as conn:
        await conn.execute(text("update app.instant_demos set expires_at = now() - interval '1 hour' where id = cast(:i as uuid)"), {"i": did})
    assert (await client.post(f"/public/try/{did}/messages", headers=visitor(), json={"messages": [{"role": "user", "content": "hi"}]})).status_code == 410
