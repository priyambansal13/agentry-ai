"""Blog + newsletter (content 8.3): drafted from the recording's moments, quotes word for word, numbers from the
recording, a person approves (never a misquote), Markdown/HTML export; and every module with background workflows is
loaded at start, so DBOS can resume them after a deploy."""
import pathlib
import sys

from conftest import expect
from sqlalchemy import text
from test_content import sample_source

from agentry.automations.content import longform
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


def test_checks_catch_misquotes_and_invented_numbers():
    tx = "We cut waiting time to under ten minutes by texting patients when we run late. No-shows went from 22 percent to 8 percent."
    good = 'Clinics can fix waiting rooms. "We cut waiting time to under ten minutes by texting patients" was the change. ' * 10
    assert longform.check(good, "Less waiting", tx) == []
    bad = good + ' As she said, "we doubled our revenue in a month". Bookings rose 40% too.'
    problems = longform.check(bad, "Less waiting", tx)
    assert any(p.startswith("quote not found") for p in problems) and any("40%" in p for p in problems)
    assert longform.check(good.replace("waiting rooms", "22% of no-shows"), "x", tx) == []  # "22 percent" in the recording


def test_html_export():
    h = longform.to_html("Title", "Meta", "Intro **bold**.\n\n## Section\n\n- one\n- two\n\n> \"A quote here please\"", "blog")
    assert '<meta name="description" content="Meta">' in h and "<h1>Title</h1>" in h and "<h3>Section</h3>" in h
    assert "<ul><li>one</li><li>two</li></ul>" in h and "<strong>bold</strong>" in h and "<blockquote>" in h
    assert "<script>" not in longform.to_html("t", None, "<script>alert(1)</script>", "newsletter")


async def test_blog_and_newsletter_from_a_recording(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    sid = await sample_source(client, h, oid)
    got = {r: (await client.post(f"/org/content/sources/{sid}/longform", headers=h[r], json={})).status_code for r in ALL}
    expect(got, owner=202, manager=202, staff=403, finance=403, viewer=403, agentry=202)
    for kind in ("blog", "newsletter"):
        out = await longform.write(oid, sid, kind)
        assert out["status"] == "ready", out["problems"]
    items = {i["kind"]: i for i in (await client.get(f"/org/content/sources/{sid}/longform", headers=h["staff"])).json()["items"]}
    blog, news = items["blog"], items["newsletter"]
    assert blog["slug"] and blog["summary"] and "## FAQ" in blog["body"] and blog["problems"] == []
    assert news["title"].startswith("3 ideas from") and news["body"].startswith("Hi there")
    misquote = blog["body"] + '\n\n"We tripled our patients in a single weekend without any ads"'
    r = await client.put(f"/org/content/longform/{blog['id']}", headers=h["owner"], json={"title": blog["title"], "body": misquote, "approve": True})
    assert r.status_code == 422 and "quote not found" in r.json()["detail"]
    r = await client.put(f"/org/content/longform/{blog['id']}", headers=h["owner"], json={"title": blog["title"], "summary": blog["summary"],
                                                                                         "body": blog["body"], "approve": True})
    assert r.json()["status"] == "approved"
    md = await client.get(f"/org/content/longform/{blog['id']}/export?format=md", headers=h["staff"])
    assert md.status_code == 200 and md.text.startswith(f"# {blog['title']}") and f'filename="{blog["slug"]}.md"' in md.headers["content-disposition"]
    html = await client.get(f"/org/content/longform/{news['id']}/export?format=html", headers=h["manager"])
    assert html.headers["content-type"].startswith("text/html") and "<ul>" in html.text
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.agent_runs where kind like 'longform_%'"))).scalar_one() == 2


def test_every_workflow_module_is_loaded_at_start():
    """A workflow DBOS can't find after a restart fails ("not a registered workflow function"): load them all up front."""
    from agentry.automations import load_all
    load_all()
    root = pathlib.Path(__file__).parents[1] / "src"
    missing = [m for f in root.rglob("*.py") if "@DBOS.workflow" in f.read_text()
               if (m := ".".join(f.relative_to(root).with_suffix("").parts).removesuffix(".__init__")) not in sys.modules
               and not m.startswith("agentry.worker")]  # worker modules are imported by the worker itself
    assert missing == []
