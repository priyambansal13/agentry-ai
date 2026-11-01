"""Recordings from a link (YouTube, Vimeo, a direct MP4…): checked before anything is created, downloaded in the
background, the platform's own captions used as the transcript (no transcription cost), plain-word errors."""
from conftest import expect
from test_content import content_test_mode  # noqa: F401 - mock transcriber, files in a temp folder

from agentry.automations.content import links, pipeline, sources

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


def captions_vtt(minutes: int = 12) -> str:
    """The first minutes of the sample episode, as the captions file a platform would give."""
    clock = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"
    segs = [x for x in sources.sample_transcript()["segments"] if x["end"] <= minutes * 60]
    return "WEBVTT\n\n" + "\n\n".join(f"{clock(x['start'])} --> {clock(x['end'])}\n{x['text']}" for x in segs) + "\n"


def fake_link(monkeypatch, captions: bool = True, kind: str = "video"):
    async def check(url):
        if "playlist" in url:
            raise links.LinkError("that's a playlist or channel: paste the link of one video")
        return {"url": url, "title": "Clinic talk on YouTube", "duration": 1260, "site": "Youtube"}

    async def fetch(url, folder):
        path = folder / ("source.mp4" if kind == "video" else "source.m4a")
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return {"path": path, "bytes": path.stat().st_size, "kind": kind, "title": "Clinic talk on YouTube",
                "transcript": sources.parse_transcript(captions_vtt(), "source.en.vtt") if captions else None}
    monkeypatch.setattr(links, "check", check)
    monkeypatch.setattr(links, "fetch", fetch)


async def test_a_youtube_link_becomes_posts_using_its_captions(client, team_org, monkeypatch):
    oid, h = await team_org(["content_repurposing"])
    fake_link(monkeypatch)
    url = "https://www.youtube.com/watch?v=abc123"
    got = {r: (await client.post("/org/content/sources/link", headers=h[r], json={"url": url, "owns_rights": True})).status_code for r in ALL}
    expect(got, owner=201, manager=201, staff=403, finance=403, viewer=403, agentry=201)
    r = await client.post("/org/content/sources/link", headers=h["owner"], json={"url": url, "owns_rights": True})
    sid = r.json()["id"]
    assert r.json()["title"] == "Clinic talk on YouTube" and r.json()["site"] == "Youtube"
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["status"] == "downloading" and s["source_url"] == url
    res = await pipeline.content_process_source(oid, sid)
    assert res == "ready", (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()["error"]
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["kind"] == "video" and s["duration_seconds"] <= 720  # the captions (12 minutes), not the mock transcriber's 45
    assert float(s["cost_usd"]) == 0 and s["moments"] and all(float(m["end_s"]) <= 720 for m in s["moments"])


async def test_without_captions_it_is_transcribed_and_a_title_given_is_kept(client, team_org, monkeypatch):
    oid, h = await team_org(["content_repurposing"])
    fake_link(monkeypatch, captions=False, kind="audio")
    r = await client.post("/org/content/sources/link", headers=h["owner"],
                          json={"url": "https://podcasts.example.com/ep-12", "title": "Episode 12", "owns_rights": True})
    sid = r.json()["id"]
    assert await pipeline.content_process_source(oid, sid) == "ready"
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["title"] == "Episode 12" and s["kind"] == "audio" and s["duration_seconds"] == 2700  # the mock transcriber's episode


async def test_links_are_checked_before_anything_is_created(client, team_org, monkeypatch):
    _oid, h = await team_org(["content_repurposing"])
    r = await client.post("/org/content/sources/link", headers=h["owner"], json={"url": "https://www.youtube.com/watch?v=x1", "owns_rights": False})
    assert r.status_code == 422 and "rights" in r.json()["detail"]
    r = await client.post("/org/content/sources/link", headers=h["owner"], json={"url": "http://127.0.0.1:8801/health", "owns_rights": True})
    assert r.status_code == 422 and r.json()["detail"] == "that isn't a public web address"
    fake_link(monkeypatch)
    r = await client.post("/org/content/sources/link", headers=h["owner"], json={"url": "https://youtube.com/playlist?list=PL1", "owns_rights": True})
    assert r.status_code == 422 and "playlist" in r.json()["detail"]
    assert (await client.get("/org/content/sources", headers=h["owner"])).json()["items"] == []


async def test_a_failed_download_says_why_and_can_be_retried(client, team_org, monkeypatch):
    oid, h = await team_org(["content_repurposing"])
    fake_link(monkeypatch)

    async def blocked(url, folder):
        raise links.LinkError("the site asked us to sign in (it sometimes blocks servers): download the video and upload the file instead")
    monkeypatch.setattr(links, "fetch", blocked)
    sid = (await client.post("/org/content/sources/link", headers=h["owner"], json={"url": "https://youtu.be/x2", "owns_rights": True})).json()["id"]
    assert await pipeline.content_process_source(oid, sid) == "failed"
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["status"] == "failed" and "upload the file instead" in s["error"]
    fake_link(monkeypatch)
    assert (await client.post(f"/org/content/sources/{sid}/retry", headers=h["owner"])).status_code == 200
    assert await pipeline.content_process_source(oid, sid) == "ready"


def test_yt_dlp_errors_in_plain_words():
    assert "private" in links._plain(Exception("ERROR: [youtube] x: Private video. Please sign in. Use --cookies"))
    assert "sign in" in links._plain(Exception("ERROR: [youtube] x: Sign in to confirm you're not a bot"))
    assert "couldn't find a video" in links._plain(Exception("ERROR: Unsupported URL: https://example.com/"))
