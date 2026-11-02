"""AI video studio (docs/flows/agents/ai-video-studio.md), end to end in test mode (no Veo key: branded test clips)."""
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from agentry.automations import video_studio as vs
from agentry.automations.content import clips
from agentry.connectors import youtube
from agentry.db import tenant_session

pytestmark = pytest.mark.skipif(not vs.available(), reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def no_video_keys(monkeypatch):
    """Test mode for both video models, whatever keys this machine has (no real renders, no cost)."""
    from agentry.automations.video_studio import sora
    from agentry.config import settings
    monkeypatch.setattr(sora, "key", lambda: None)
    monkeypatch.setattr(settings, "video_api_key", None)


async def _yt(oid: str) -> None:
    from agentry.connectors.store import save_connection
    await save_connection(oid, provider="youtube", account_ref="UC123", display_name="Smile Studio",
                          secret={"refresh_token": "r", "access_token": "a", "expires_at": 9e9})


async def _config(oid: str, **cfg: object) -> None:
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set config = config || cast(:c as jsonb) where template_key = 'video_studio'"),
                           {"c": json.dumps(cfg)})


async def test_made_reviewed_and_published(client, team_org, monkeypatch):
    oid, h = await team_org(["video_studio"], live=False)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    await _config(oid, scenes=2, topics=["How we clean an AC in 20 minutes"])
    r = await client.post("/org/videos", headers=h["manager"], json={})
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    assert (await client.post("/org/videos", headers=h["staff"], json={})).status_code == 403  # front desk can watch, not make
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    v = (await client.get(f"/org/videos/{vid}", headers=h["staff"])).json()
    assert v["status"] == "review" and v["topic"] == "How we clean an AC in 20 minutes" and v["has_file"]
    assert v["plan"]["hashtags"][0] == "#Shorts" and len(v["plan"]["scenes"]) == 2 and v["model"] == "test" and float(v["cost_usd"]) == 0
    info = await clips.probe(vs.resolve(await _path(oid, vid)))
    assert info["video"] and info["audio"] and 17 <= info["duration"] <= 19  # 2 scenes x 8 s + the 2 s end card
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select title, body from app.approvals where kind = 'video_review'"))).mappings().one()
        mock = (await conn.execute(text("select payload->>'mock' from app.events where type = 'video.generated'"))).scalar_one()
    assert card["title"].startswith("New video to approve") and "Connect YouTube" in card["body"] and mock == "true"  # test mode isn't billed
    f = await client.get(f"/org/videos/{vid}/file", headers=h["owner"])
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    # publishing needs YouTube
    assert (await client.post(f"/org/videos/{vid}/publish", headers=h["owner"])).status_code == 409
    await _yt(oid)
    sent = {}

    async def fake_upload(self, data, **kw):
        sent.update(kw, size=len(data))
        return {"id": "abc123", "url": "https://youtube.com/shorts/abc123", "privacy": kw["privacy"]}
    monkeypatch.setattr(youtube.YouTube, "upload", fake_upload)
    await client.patch(f"/org/videos/{vid}", headers=h["owner"], json={"title": "AC cleaning in 20 minutes", "description": "Watch us.",
                                                                       "hashtags": ["#AC", "#Shorts"], "hook": "Dusty AC?"})
    await _set_status(oid, vid, "review")
    p = await client.post(f"/org/videos/{vid}/publish", headers=h["owner"])
    assert p.status_code == 200 and p.json()["url"].endswith("abc123")
    assert sent["title"] == "AC cleaning in 20 minutes" and sent["privacy"] == "public" and sent["tags"] == ["Shorts", "AC"] and sent["size"] > 10000
    v = (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()
    assert v["status"] == "published" and v["publish"]["id"] == "abc123"
    # the same topic isn't picked again
    vid2 = (await client.post("/org/videos", headers=h["owner"], json={})).json()["id"]
    await _config(oid, topics=["How we clean an AC in 20 minutes", "Signs your AC needs gas"])
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid2}})
    assert (await client.get(f"/org/videos/{vid2}", headers=h["owner"])).json()["topic"] == "Signs your AC needs gas"


async def _path(oid: str, vid: str) -> str:
    async with tenant_session(oid) as conn:
        return (await conn.execute(text("select path from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).scalar_one()


async def _set_status(oid: str, vid: str, status: str) -> None:
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.ai_videos set status = :s where id = cast(:i as uuid)"), {"s": status, "i": vid})


async def test_live_publishes_by_itself(client, team_org, monkeypatch):
    oid, h = await team_org(["video_studio"])
    await _config(oid, scenes=1, privacy="unlisted")
    await _yt(oid)

    async def fake_upload(self, data, **kw):
        return {"id": "zz9", "url": "https://youtube.com/shorts/zz9", "privacy": kw["privacy"]}
    monkeypatch.setattr(youtube.YouTube, "upload", fake_upload)
    vid = (await client.post("/org/videos", headers=h["owner"], json={"topic": "A day at our clinic"})).json()["id"]
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    v = (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()
    assert v["status"] == "published" and v["publish"]["privacy"] == "unlisted"


async def test_a_risky_plan_waits_for_a_person(client, team_org):
    oid, h = await team_org(["video_studio"])
    vid = (await client.post("/org/videos", headers=h["owner"], json={"topic": "Guaranteed whiter teeth"})).json()["id"]
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    v = (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()
    assert v["status"] == "needs_attention" and "Guaranteed" in v["error"]
    bad = await client.post(f"/org/videos/{vid}/publish", headers=h["owner"])
    assert bad.status_code == 409
    scenes = [{"prompt": s["prompt"].replace("Guaranteed whiter teeth", "a gentle cleaning"), "caption": "A gentle cleaning"} for s in v["plan"]["scenes"]]
    await client.patch(f"/org/videos/{vid}", headers=h["owner"], json={"title": "What a cleaning feels like", "hook": "Nervous about cleanings?",
                                                                       "description": "", "hashtags": [], "scenes": scenes})
    assert (await client.post(f"/org/videos/{vid}/generate", headers=h["owner"])).status_code == 202
    await vs.make_video_from_plan({"org_id": oid, "payload": {"video_id": vid}})
    assert (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()["status"] == "review"  # live but no YouTube yet


async def test_the_budget_stops_it(client, team_org):
    oid, h = await team_org(["video_studio"])
    await _config(oid, monthly_budget_usd=1)  # 2 scenes x 8 s x $0.10 (Sora 2) = $1.60
    vid = (await client.post("/org/videos", headers=h["owner"], json={})).json()["id"]
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    v = (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()
    assert v["status"] == "skipped" and "budget" in v["error"]


async def test_the_schedule_makes_one_per_slot(client, team_org):
    oid, _h = await team_org(["video_studio"])
    await _config(oid, days=["mon"], time="11:00")
    monday_noon_ist = datetime(2026, 11, 2, 6, 30, tzinfo=UTC)  # 12:00 IST
    assert await vs.schedule(monday_noon_ist) >= 1
    assert await vs.schedule(monday_noon_ist) == 0  # never twice for the same slot
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select slot, trigger from app.ai_videos"))).one() == ("2026-11-02 11:00", "schedule")


def test_rules_and_slots():
    cfg = vs.VideoConfig(days=["mon", "thu"], time="11:00").model_dump()
    assert vs.due_slot(cfg, "Asia/Kolkata", datetime(2026, 11, 2, 5, 29, tzinfo=UTC)) is None   # 10:59 IST
    assert vs.due_slot(cfg, "Asia/Kolkata", datetime(2026, 11, 2, 5, 30, tzinfo=UTC)) == "2026-11-02 11:00"
    assert vs.due_slot(cfg, "Asia/Kolkata", datetime(2026, 11, 3, 6, 0, tzinfo=UTC)) is None    # a Tuesday
    plan = {"title": "Cheapest AC service in town", "description": "Only ₹499", "hook": "x", "scenes": [{"prompt": "short", "caption": "c"}]}
    probs = vs.rule_problems(plan, 2)
    assert any("exactly 2" in p for p in probs) and any("risky" in p for p in probs) and any("fuller prompt" in p for p in probs)
    assert vs.estimate(vs.VideoConfig(scenes=3, quality="standard", provider="google").model_dump()) == 9.6   # Veo
    assert vs.estimate(vs.VideoConfig(scenes=3, quality="standard").model_dump()) == 7.2                      # Sora 2 Pro
    assert vs.estimate(vs.VideoConfig(scenes=2).model_dump()) == 1.6                                          # Sora 2


async def test_veo_requests_and_replies(monkeypatch):
    """The real Veo path against canned Gemini API answers (no network)."""
    from agentry.automations.video_studio import veo
    from agentry.config import settings
    monkeypatch.setattr(settings, "video_api_key", "k")
    calls, answers = [], []

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._b, self.content, self.text = status, body, b"x", json.dumps(body)

        def json(self):
            return self._b

    class Fake:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a): ...
        async def post(self, url, json=None, headers=None):
            calls.append((url, json, headers))
            return Resp(200, {"name": "models/veo-3.1-fast-generate-preview/operations/op1"})
        async def get(self, url, headers=None, **k):
            calls.append((url, None, headers))
            return Resp(200, answers.pop(0))
    monkeypatch.setattr(veo, "client", Fake)
    name = await veo.start("a barista pours latte art", quality="fast")
    url, body, headers = calls[0]
    assert url.endswith("/models/veo-3.1-fast-generate-preview:predictLongRunning") and headers["x-goog-api-key"] == "k"
    assert body["parameters"] == {"aspectRatio": "9:16", "durationSeconds": 8, "negativePrompt": veo.NEGATIVE}
    answers += [{"name": name, "done": False},
                {"name": name, "done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://x/v.mp4"}}]}}},
                {"name": name, "done": True, "response": {"generateVideoResponse": {"raiMediaFilteredReasons": ["a person's face"]}}}]
    assert (await veo.poll(name)) == {"done": False, "uri": None, "error": None}
    assert (await veo.poll(name))["uri"] == "https://x/v.mp4"
    filtered = await veo.poll(name)
    assert filtered["done"] and "filtered" in filtered["error"]


async def test_plan_again_after_the_models_were_busy(client, team_org, monkeypatch):
    from agentry.llm import gateway
    oid, h = await team_org(["video_studio"])
    real = vs.complete

    async def busy(*a, **k):
        raise gateway.AllModelsFailed("writer", ["busy"])
    monkeypatch.setattr(vs, "complete", busy)
    vid = (await client.post("/org/videos", headers=h["owner"], json={"topic": "A day at our studio"})).json()["id"]
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    v = (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()
    assert v["status"] == "needs_attention" and "busy" in v["error"]
    monkeypatch.setattr(vs, "complete", real)
    assert (await client.post(f"/org/videos/{vid}/replan", headers=h["owner"])).status_code == 202
    await vs.make_video({"org_id": oid, "payload": {"video_id": vid}})
    assert (await client.get(f"/org/videos/{vid}", headers=h["owner"])).json()["status"] == "review"
    assert (await client.post(f"/org/videos/{vid}/replan", headers=h["owner"])).status_code == 409  # only when it needs a look


async def test_sora_requests_and_replies(monkeypatch):
    """The real Sora 2 path against canned OpenAI answers (no network)."""
    from agentry.automations.video_studio import gen, sora
    monkeypatch.setattr(sora, "key", lambda: "sk-test")
    assert not gen.test_mode("openai") and gen.model_name("openai", "standard") == "sora-2-pro"
    calls, answers = [], []

    class Resp:
        def __init__(self, status, body, content=b"x"):
            self.status_code, self._b, self.content, self.text = status, body, content, json.dumps(body)

        def json(self):
            return self._b

    class Fake:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a): ...
        async def post(self, url, files=None, headers=None):
            calls.append((url, {k: v[1] for k, v in files.items()}, headers))
            return Resp(200, {"id": "video_123", "status": "queued"})
        async def get(self, url, headers=None, **k):
            calls.append((url, None, headers))
            return answers.pop(0)
    monkeypatch.setattr(sora, "client", Fake)
    name = await gen.start("openai", "a chai stall at dawn", quality="fast")
    url, form, headers = calls[0]
    assert name == "sora:video_123" and url == "https://api.openai.com/v1/videos" and headers["Authorization"] == "Bearer sk-test"
    assert form == {"model": "sora-2", "prompt": "a chai stall at dawn", "size": "720x1280", "seconds": "8"}
    answers += [Resp(200, {"id": "video_123", "status": "in_progress", "progress": 40}), Resp(200, {"id": "video_123", "status": "completed"}),
                Resp(200, {}, content=b"MP4DATA"), Resp(200, {"id": "video_123", "status": "failed", "error": {"message": "moderation"}})]
    assert (await gen.poll(name))["done"] is False
    assert (await gen.poll(name)) == {"done": True, "uri": "sora:video_123", "error": None}
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        out = await gen.download(name, Path(t) / "s.mp4")
        assert out.read_bytes() == b"MP4DATA" and calls[-1][0].endswith("/videos/video_123/content")
    assert (await gen.poll(name))["error"] == "moderation"


async def test_the_planner_prefers_openai(monkeypatch):
    from agentry.llm import gateway
    monkeypatch.setattr(gateway, "models_for", _chain)
    seen = []

    async def fake_acompletion(model, **kw):
        seen.append(model)
        raise RuntimeError("stop")
    monkeypatch.setattr(gateway.litellm, "acompletion", fake_acompletion)
    with pytest.raises(gateway.AllModelsFailed):
        await gateway.complete("writer", [{"role": "user", "content": "x"}], prefer="openai", record=False)
    assert seen[0].startswith("openai/") and seen[1].startswith("gemini/")


async def _chain(tier, org_id=None):
    return ["gemini/gemini-3.5-flash", "openai/gpt-5.4-mini"]
