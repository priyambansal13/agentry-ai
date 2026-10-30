"""Content repurposing 6.1-6.4 (+ test-mode publishing): one 45-minute podcast -> 10 moments x 3 platforms = 30 posts
with quote cards, exact quotes only, review, calendar rules, brand kit, roles."""
import io
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import expect
from PIL import Image
from sqlalchemy import text

from agentry.automations.content import calendar, drafts, moments, pipeline, sources
from agentry.config import settings
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


@pytest.fixture(autouse=True)
def content_test_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "content_transcriber", "mock")
    monkeypatch.setattr(settings, "content_publisher", "mock")
    monkeypatch.setattr(settings, "content_dir", str(tmp_path / "content"))


async def sample_source(client, h, oid: str) -> str:
    r = await client.post("/org/content/sources/sample", headers=h["owner"])
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert await pipeline.content_process_source(oid, sid) == "ready"
    return sid


async def test_one_podcast_becomes_30_checked_posts_with_cards(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    sid = await sample_source(client, h, oid)
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["status"] == "ready" and s["duration_seconds"] == 2700 and s["progress"]["moments_done"] == 10
    assert len(s["moments"]) == 10 and len({m["topic"] for m in s["moments"]}) >= 6  # varied, not ten takes on one idea
    transcript = sources.full_text(sources.sample_transcript())
    assert all(moments.quote_in(m["quote"], transcript) for m in s["moments"])  # every moment is an exact quote
    assert len(s["posts"]) == 30 and {p["platform"] for p in s["posts"]} == {"linkedin", "instagram", "x"}
    assert all(p["has_image"] and p["critic"]["ok"] and p["review"] == "pending" for p in s["posts"])
    assert all(len(p["body"]) + sum(len(t) + 2 for t in p["hashtags"]) <= 280 for p in s["posts"] if p["platform"] == "x")
    img = await client.get(f"/org/content/posts/{s['posts'][0]['id']}/image", headers=h["staff"])
    assert img.status_code == 200 and Image.open(io.BytesIO(img.content)).size in ((1080, 1080), (1200, 675))
    listed = (await client.get("/org/content/sources", headers=h["owner"])).json()["items"]
    assert listed[0]["posts"] == 30 and listed[0]["to_review"] == 30


async def test_a_misquote_is_caught_and_needs_a_person(client, team_org, monkeypatch):
    oid, h = await team_org(["content_repurposing"])
    real = drafts.complete

    async def misquoting(tier, messages, **kw):
        if kw.get("prompt_key") == "content_post":
            from types import SimpleNamespace
            return SimpleNamespace(data={"body": "Big lesson.\n\n“We missed 300 calls every single week.”", "hashtags": ["a"]}, text="", mock=False)
        return await real(tier, messages, **kw)
    monkeypatch.setattr(drafts, "complete", misquoting)
    sid = await sample_source(client, h, oid)
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    p = next(p for p in s["posts"] if p["platform"] == "linkedin")
    assert p["review"] == "needs_attention" and p["critic"]["attempts"] == 3
    assert any("word for word" in x for x in p["critic"]["problems"]) and any("300" in x for x in p["critic"]["problems"])
    r = await client.post(f"/org/content/posts/{p['id']}", headers=h["manager"], json={"action": "approve"})
    assert r.status_code == 409
    fixed = "A missed call is a patient lost.\n\n“A missed call is not a missed call.”\n\nPick up, or call back fast."
    r = await client.post(f"/org/content/posts/{p['id']}", headers=h["manager"], json={"action": "approve", "body": fixed})
    assert r.json() == {"id": p["id"], "review": "approved", "edited": True}
    monkeypatch.setattr(drafts, "complete", real)  # regenerate gives a clean draft again
    r = await client.post(f"/org/content/posts/{s['posts'][1]['id']}", headers=h["owner"], json={"action": "regenerate"})
    assert r.json()["review"] == "pending"


async def test_uploads_need_rights_and_a_known_file_type(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    audio = {"file": ("episode.mp3", io.BytesIO(b"ID3fake-audio"), "audio/mpeg")}
    assert (await client.post("/org/content/sources", headers=h["owner"], files=audio, data={"title": "Ep 12"})).status_code == 422
    bad = {"file": ("notes.pdf", io.BytesIO(b"%PDF"), "application/pdf")}
    assert (await client.post("/org/content/sources", headers=h["owner"], files=bad, data={"title": "x", "owns_rights": "true"})).status_code == 422
    r = await client.post("/org/content/sources", headers=h["owner"], files=audio, data={"title": "Ep 12", "owns_rights": "true"})
    assert r.status_code == 201 and r.json()["kind"] == "audio"
    assert await pipeline.content_process_source(oid, r.json()["id"]) == "ready"  # mock transcriber: the sample episode
    srt = ("1\n00:00:01,000 --> 00:00:09,500\nDr. Rao: We cut our waiting time to under ten minutes by texting patients when we run late.\n\n"
           "2\n00:00:10,000 --> 00:00:19,000\nDr. Rao: Every patient gets a written plan with prices before we start, and acceptance went up.\n")
    r = await client.post("/org/content/sources", headers=h["owner"], files={"file": ("ep.srt", io.BytesIO(srt.encode()), "text/plain")},
                          data={"title": "Short talk", "owns_rights": "true"})
    sid = r.json()["id"]
    assert await pipeline.content_process_source(oid, sid) == "ready"
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["kind"] == "transcript" and s["moments"] and s["moments"][0]["speaker"] == "Dr. Rao"
    # deleting removes the files too
    folder = sources.folder(oid, sid)
    assert any(folder.iterdir())
    assert (await client.delete(f"/org/content/sources/{sid}", headers=h["owner"])).json() == {"deleted": True}
    assert not folder.exists()


def test_transcript_files():
    vtt = "WEBVTT\n\n00:01.000 --> 00:04.000\n<v Neha>Speed is everything.\n\n00:05.000 --> 00:09.000\nHost: Why?\n"
    t = sources.parse_transcript(vtt, "a.vtt")
    assert [s["start"] for s in t["segments"]] == [1.0, 5.0] and t["segments"][1]["speaker"] == "Host"
    txt = sources.parse_transcript("Neha: A missed call is a patient who chose someone else.\n\nHost: Wow.", "a.txt")
    assert txt["segments"][0]["speaker"] == "Neha" and txt["segments"][1]["start"] > 0
    with pytest.raises(sources.TranscribeError):
        sources.parse_transcript("   ", "a.txt")


async def test_review_schedule_and_test_mode_publishing(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    sid = await sample_source(client, h, oid)
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    got = {r: (await client.post(f"/org/content/posts/{s['posts'][0]['id']}", headers=h[r], json={"action": "drop"})).status_code
           for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    r = await client.post(f"/org/content/moments/{s['moments'][-1]['id']}/drop", headers=h["owner"])
    assert r.json() == {"dropped_posts": 3}
    assert (await client.post(f"/org/content/sources/{sid}/approve-ready", headers=h["owner"])).json() == {"approved": 27}
    assert (await client.post("/org/content/schedule", headers=h["manager"], json={"source_id": sid})).json() == {"scheduled": 27}
    cal = (await client.get("/org/content/calendar?days=60", headers=h["staff"])).json()
    assert len(cal["items"]) == 27 and cal["approved_unscheduled"] == 0
    tz = ZoneInfo("Asia/Kolkata")
    by_day: dict = {}
    for p in cal["items"]:
        at = datetime.fromisoformat(p["scheduled_at"]).astimezone(tz)
        by_day.setdefault(at.date(), []).append((p["platform"], p["moment_id"], at.strftime("%H:%M")))
        if p["platform"] == "linkedin":
            assert at.weekday() < 5 and at.strftime("%H:%M") == "09:30"
    for posts in by_day.values():
        assert len({m for _, m, _ in posts}) == len(posts)  # never two posts from the same moment on one day
        assert sum(1 for p, _, _ in posts if p == "x") <= 2 and sum(1 for p, _, _ in posts if p == "instagram") <= 1
    first = min(datetime.fromisoformat(p["scheduled_at"]) for p in cal["items"])
    assert first.astimezone(tz).date() > datetime.now(tz).date()  # starts tomorrow
    # moving one post, then publishing everything that's due
    one = cal["items"][0]["id"]
    later = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    assert (await client.patch(f"/org/content/posts/{one}/slot", headers=h["owner"], json={"scheduled_at": later})).status_code == 200
    out = await calendar.publish_due(oid, datetime.now(UTC) + timedelta(days=60))
    assert out == {"published": 26, "failed": 0}
    async with tenant_session(oid) as conn:
        refs = (await conn.execute(text("select publish_ref from app.content_posts where published_at is not null"))).scalars().all()
    assert len(refs) == 26 and all(r.startswith("test-mode:") for r in refs)
    listed = (await client.get("/org/content/sources", headers=h["owner"])).json()["items"][0]
    assert listed["published"] == 26


async def test_brand_kit_voice_logo_and_redraw(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    await sample_source(client, h, oid)
    got = {r: (await client.put("/org/content/brand", headers=h[r], json={"template": "light"})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    r = (await client.put("/org/content/brand", headers=h["owner"], json={"accent_color": "#FF5A1F", "handle": "@smilecraft"})).json()
    assert r["images_redrawn"] == 30
    assert (await client.put("/org/content/brand", headers=h["owner"], json={"accent_color": "orange"})).status_code == 422
    png = io.BytesIO()
    Image.new("RGBA", (300, 120), (255, 90, 31, 255)).save(png, "PNG")
    r = await client.post("/org/content/brand/logo", headers=h["owner"], files={"file": ("logo.png", png.getvalue(), "image/png")})
    assert r.json() == {"saved": True, "images_redrawn": 30}
    assert (await client.post("/org/content/brand/logo", headers=h["owner"], files={"file": ("x.png", b"nope", "image/png")})).status_code == 422
    posts = "\n\n".join(["Big news today! We opened our second chair 🎉 #dentist #pune", "I learned this the hard way: answer every call. Every one.",  # noqa: FLY002 - one post per list item reads clearer
                         "What's the one question you ask a new dentist? Tell me below.", "Our team turned five today. Thank you, Pune 🙏 #smile"])
    r = (await client.post("/org/content/brand/voice", headers=h["owner"], json={"posts": posts})).json()
    assert r["learned"] and r["samples"] == 4 and "words" in r["voice"]
    kit = (await client.get("/org/content/brand", headers=h["staff"])).json()
    assert kit["has_logo"] and kit["voice_samples"] == 4 and kit["accent_color"] == "#FF5A1F"
    prev = await client.get("/org/content/brand/preview?platform=linkedin", headers=h["owner"])
    assert prev.status_code == 200 and Image.open(io.BytesIO(prev.content)).size == (1200, 675)


async def test_roles_and_hidden_without_the_agent(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    got = {r: (await client.get("/org/content/sources", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    got = {r: (await client.post("/org/content/sources/sample", headers=h[r])).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    other, ho = await team_org(["inbox_triage"])
    assert (await client.get("/org/content/sources", headers=ho["owner"])).status_code == 404
    assert oid and other


def test_numbers_may_change_form_but_not_value():
    m = {"quote": "We had a no-show rate of almost 22 percent in 2019.", "hook": "", "insight": ""}
    ok = drafts.check("x", "No-shows were 22% in 2019.", [], m, m["quote"], m["quote"])
    bad = drafts.check("x", "No-shows were 32% in 2019.", [], m, m["quote"], m["quote"])
    assert ok == [] and bad == ["the number 32% isn't in the recording around this moment"]
