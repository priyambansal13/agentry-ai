"""Local SEO (ROADMAP-V3 B1): the audit finds what's missing on a site; articles stay inside the business's facts."""
import httpx
from sqlalchemy import text

from agentry.automations import local_seo as seo
from agentry.db import tenant_session

HOME = """<html><head><title>Cool Air Services</title></head><body><h1>AC service in Pune</h1>
<p>Call +91 98100 00071 for AC repair.</p><a href="/services">Services</a><a href="/missing">Old page</a><img src="a.jpg"></body></html>"""
SERVICES = """<html><head><title>Cool Air Services</title><meta name="viewport" content="width=device-width">
<meta name="description" content="AC repair, gas filling and installation across Pune by Cool Air Services, open 9 to 8 every day."></head>
<body><h1>Services</h1><h1>More</h1><p>We repair ACs.</p><a href="https://wa.me/919810000071">WhatsApp</a></body></html>"""


def fake_site(monkeypatch):
    async def get(client, url, max_redirects=3):
        pages = {"https://coolair.example/": HOME, "https://coolair.example/services": SERVICES}
        if url in pages:
            return httpx.Response(200, text=pages[url], headers={"content-type": "text/html"}, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))
    monkeypatch.setattr(seo, "_get_checked", get)
    monkeypatch.setattr(seo, "_check_public", lambda u: None)


async def test_audit_lists_fixes_by_impact(client, team_org, monkeypatch):
    fake_site(monkeypatch)
    oid, h = await team_org(["local_seo"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.org_settings set website = 'https://coolair.example/', profile = profile || '{"phone": "+91 98100 00099"}'"""))
    r = await client.post("/org/seo/audit", headers=h["owner"], json={})
    assert r.status_code == 201, r.text
    a = r.json()
    found = {i["issue"] for i in a["issues"]}
    assert "No LocalBusiness structured data" in found and "No mobile viewport" in found
    assert any(i.startswith("1 broken link") for i in found) and "1 title(s) used on more than one page" in found
    assert "The phone on the site differs from the one in your profile" in found and "No Google Maps link" in found
    assert "No click-to-WhatsApp link" not in found  # the services page has one
    assert a["issues"][0]["severity"] == "high" and a["score"] < 50
    assert (await client.post("/org/seo/audit", headers=h["staff"], json={})).status_code == 403
    assert (await client.get("/org/seo", headers=h["viewer"])).json()["latest"]["score"] == a["score"]


async def test_articles_and_export(client, team_org):
    oid, h = await team_org(["local_seo"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"city": "Pune"}'"""))
    r = await client.post("/org/seo/articles", headers=h["owner"], json={"topic": "AC gas refilling"})
    assert r.status_code == 201 and r.json()["status"] == "draft"
    a = (await client.get(f"/org/seo/articles/{r.json()['id']}", headers=h["owner"])).json()
    assert "Pune" in a["title"] and len(a["faqs"]) == 3
    x = await client.get(f"/org/seo/articles/{a['id']}/export", headers=h["owner"])
    assert '"@type": "FAQPage"' in x.text and "<h1>" in x.text
    assert (await client.patch(f"/org/seo/articles/{a['id']}", headers=h["owner"], json={"status": "approved"})).status_code == 200


def test_numbers_must_come_from_the_facts():
    facts = "- Prices: AC service starts at ₹499. Open since 2015."
    ok = {"title": "t", "body": "AC service starts at ₹499 here. " * 80, "faqs": []}
    bad = {"title": "t", "body": "We have served 5000 customers and charge ₹299. " * 80, "faqs": []}
    assert seo.article_problems(ok, facts) == []
    assert any("isn't in the business's facts" in p for p in seo.article_problems(bad, facts))
    assert any("risky" in p for p in seo.article_problems({"title": "Best in Pune", "body": "x " * 400, "faqs": []}, facts))
