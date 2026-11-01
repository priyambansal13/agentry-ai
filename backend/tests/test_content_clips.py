"""Vertical clips (content 8.2): each moment of a video upload cut as a 9:16 MP4 with captions from the transcript,
the hook banner and an end card; whole sentences, 20-60 s; moments past the end of the video are skipped, not failed."""
import io

import pytest
from conftest import expect
from test_content import content_test_mode  # noqa: F401 - mock transcriber, files in a temp folder

from agentry.automations.content import clips, pipeline

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
SEGS = [{"start": i * 4.0, "end": i * 4.0 + 3.8, "speaker": None, "text": f"Sentence {i} is about how we answer every missed call fast"}
        for i in range(30)]
needs_ffmpeg = pytest.mark.skipif(not clips.available(), reason="ffmpeg not installed")


def test_the_cut_is_whole_sentences_and_20_to_60_seconds():
    a, b = clips.window(SEGS, 41.0, 46.0, 120.0)  # a 5 s moment grows to whole segments of at least 20 s
    assert a == 39.7 and b - a >= clips.MIN_S and b == 64.1
    a, b = clips.window(SEGS, 8.0, 110.0, 120.0)  # too long: cut at the last sentence end within 60 s
    assert b - a <= clips.MAX_S + 2 * clips.PAD and b == 67.8 + clips.PAD
    a, b = clips.window(SEGS, 112.0, 115.0, 120.0)  # near the end of the video: grows backwards
    assert b <= 120.0 and b - a >= clips.MIN_S
    with pytest.raises(clips.ClipError, match="past the end"):
        clips.window(SEGS, 500.0, 520.0, 120.0)


def test_captions_are_short_lines_timed_inside_the_clip():
    lines = clips.captions(SEGS, 39.7, 64.1)
    assert all(len(t.split()) <= clips.WORDS_PER_LINE for _, _, t in lines)
    assert lines[0][0] >= 0 and lines[-1][1] <= 64.1 - 39.7 and all(a < b for a, b, _ in lines)
    assert lines[0][2].startswith("Sentence 10")


@needs_ffmpeg
async def test_a_real_clip_is_vertical_with_sound(tmp_path):
    src, out = tmp_path / "src.mp4", tmp_path / "clip.mp4"
    await clips._exec("ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15", "-f", "lavfi", "-i", "sine",
                      "-t", "30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src))
    a, b = clips.window(SEGS, 2.0, 6.0, 30.0)
    length = await clips.render(src, out, a, b, clips.captions(SEGS, a, b), "Missed calls cost more than you think",
                                {"primary_color": "#1F2A1A", "handle": "@clinic"}, "Smile Dental", None)
    info = await clips.probe(out)
    assert info["video"] and info["audio"] and abs(info["duration"] - length) < 0.3 and length == round(b - a + clips.OUTRO_S, 2)
    dims = (await clips._exec("ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                              str(out))).decode().strip()
    assert dims == "1080,1920"


@needs_ffmpeg
async def test_a_video_upload_gets_a_clip_per_moment(client, team_org, monkeypatch, tmp_path):
    oid, h = await team_org(["content_repurposing"])

    async def long_video(path):  # the mock transcript is a 45-minute episode
        return {"duration": 2700.0, "video": True, "audio": True}
    cut = []

    async def fake_render(src, out, a, b, lines, hook, kit, business, logo, audio=True):
        cut.append((a, b, len(lines), hook))
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video")
        return round(b - a + clips.OUTRO_S, 2)
    monkeypatch.setattr(clips, "probe", long_video)
    monkeypatch.setattr(clips, "render", fake_render)
    video = {"file": ("talk.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}
    r = await client.post("/org/content/sources", headers=h["owner"], files=video, data={"title": "Clinic talk", "owns_rights": "true"})
    sid = r.json()["id"]
    assert r.json()["kind"] == "video" and await pipeline.content_process_source(oid, sid) == "ready"
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert len(s["clips"]) == len(s["moments"]) == 10 and {c["status"] for c in s["clips"].values()} == {"ready"}
    assert all(clips.MIN_S <= b - a <= clips.MAX_S + 1 and n > 0 for a, b, n, _ in cut)
    mid = s["moments"][0]["id"]
    got = {r: (await client.get(f"/org/content/clips/{mid}/video", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    v = await client.get(f"/org/content/clips/{mid}/video", headers=h["owner"])
    assert v.headers["content-type"] == "video/mp4" and v.headers["content-disposition"].startswith("inline")
    # recut on request (e.g. after a brand kit change): owners and managers only
    got = {r: (await client.post(f"/org/content/sources/{sid}/clips", headers=h[r])).status_code for r in ALL}
    expect(got, owner=202, manager=202, staff=403, finance=403, viewer=403, agentry=202)
    assert {c["status"] for c in (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()["clips"].values()} == {"cutting"}
    await pipeline.content_cut_clips({"org_id": oid, "payload": {"source_id": sid, "moment_ids": [mid]}})
    assert (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()["clips"][mid]["status"] == "ready"


async def test_audio_and_transcripts_get_no_clips(client, team_org):
    from test_content import sample_source
    oid, h = await team_org(["content_repurposing"])
    sid = await sample_source(client, h, oid)
    s = (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()
    assert s["clips"] == {}
    r = await client.post(f"/org/content/sources/{sid}/clips", headers=h["owner"])
    assert r.status_code == 409 and "video" in r.json()["detail"]

