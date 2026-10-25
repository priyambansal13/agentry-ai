"""Demo Studio: crawled site -> sandboxed demo tenant with the prospect's name."""
import uuid

import pytest
from sqlalchemy import create_engine, text

from agentry import demo_studio
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.knowledge import Page, search

PAGES = [
    Page("https://brightsmile.example/", "Bright Smile Dental Studio | Kothrud, Pune",
         "Gentle dentistry in Kothrud.\n\nWe offer invisible aligners, implants and same-day emergency care.\n\n"
         "Open Monday to Saturday, 10am to 8pm. Free parking for patients.",
         {"og:site_name": "Bright Smile Dental Studio", "theme-color": "#1e88e5",
          "og:image": "https://brightsmile.example/logo.png", "description": "Gentle dentistry in Kothrud, Pune."}),
    Page("https://brightsmile.example/aligners", "Clear aligners",
         "Clear aligners start at Rs 65,000 including all trays and reviews. EMI available.", {}),
]


@pytest.fixture
async def demo_org():
    """A bare organisation, as the dashboard creates it, removed afterwards."""
    owner = create_engine(settings.migrate_database_url)
    org_id, slug = str(uuid.uuid4()), f"bright-smile-{uuid.uuid4().hex[:4]}"
    with owner.begin() as c:
        c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Bright Smile Dental Studio', :s, now())"""),
                  {"i": org_id, "s": slug})
    yield org_id, slug
    with owner.begin() as c:
        for t in ("approvals", "conversations", "bookings", "leads", "staff", "services", "kb_documents", "events",
                  "contacts", "automation_instances", "audit_log", "org_settings", "llm_calls"):
            c.execute(text(f"delete from app.{t} where org_id = :o"), {"o": org_id})
        c.execute(text("delete from auth.organization where id = :o"), {"o": org_id})


async def test_demo_is_built_from_the_prospects_site(demo_org, monkeypatch, client):
    org_id, slug = demo_org

    async def fake_crawl(url, max_pages=8):
        return PAGES[:max_pages]

    monkeypatch.setattr(demo_studio, "crawl", fake_crawl)
    assert (await demo_studio.preview("brightsmile.example"))["name"] == "Bright Smile Dental Studio"

    r = await demo_studio.build_demo(org_id, url="https://brightsmile.example/", pack_key="dental-clinic", created_by="staff")
    assert r["pages_learned"] == 2 and r["brand"]["color"] == "#1e88e5"

    hits = await search(org_id, "how much are clear aligners", k=2)
    assert any("65,000" in h.content for h in hits)
    async with tenant_session(org_id) as conn:
        s = (await conn.execute(text("select status, widget_key, persona, demo_expires_at from app.org_settings"))).mappings().one()
        inbox = (await conn.execute(text("select count(*) from app.conversations where channel = 'email'"))).scalar_one()
    assert s["status"] == "demo" and s["widget_key"] and s["persona"]["greeting"].startswith("Hi, I'm Asha, Bright Smile")
    assert inbox == 3  # sample inbox addressed to them

    page = (await client.get(f"/public/demos/{slug}")).json()
    assert page["name"] == "Bright Smile Dental Studio" and page["widget_key"] == s["widget_key"]
    assert (await client.get(f"/widget/{s['widget_key']}")).json()["color"] == "#1e88e5"

    with pytest.raises(ValueError, match="already set up"):
        await demo_studio.build_demo(org_id, url="https://brightsmile.example/", pack_key="dental-clinic", created_by="staff")

    async with system_session() as conn:
        await conn.execute(text("update app.org_settings set demo_expires_at = now() - interval '1 day' where org_id = :o"), {"o": org_id})
    assert (await client.get(f"/public/demos/{slug}")).status_code == 410
    assert (await client.get(f"/widget/{s['widget_key']}")).status_code == 410


async def test_hq_demo_endpoints_are_staff_only(client, login):
    assert (await client.post("/hq/demos/preview", headers=login("riya@sharmadigital.example"),
                              json={"url": "https://example.com"})).status_code == 403
    r = await client.post("/hq/demos/preview", headers=login("admin@agentry.dev"), json={"url": "http://127.0.0.1:8801"})
    assert r.status_code == 422 and "non-public" in r.text
