"""Engagement loop (ROADMAP-V3 B5): numbers at +24 h / +7 d, what worked, and the next moments ranked by it."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from agentry.automations.content import engagement as eg
from agentry.connectors.store import save_connection
from agentry.db import tenant_session


async def _video(oid: str, topic: str, ext: str, days_ago: float) -> str:
    at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    async with tenant_session(oid) as conn:
        return str((await conn.execute(text("""insert into app.ai_videos (org_id, status, topic, plan, publish) values (:o, 'published', :t,
            cast(:p as jsonb), cast(:pub as jsonb)) returning id"""), {"o": oid, "t": topic, "p": '{"hook": "Hook for ' + topic + '", "title": "' + topic + '"}',
                                                                        "pub": f'{{"id": "{ext}", "at": "{at}", "url": "https://youtube.com/shorts/{ext}"}}'})).scalar_one())


async def test_youtube_numbers_learning_and_ranking(client, team_org, monkeypatch):
    oid, h = await team_org(["video_studio", "content_repurposing"])
    await save_connection(oid, provider="youtube", account_ref="UC1", display_name="Ch", secret={"refresh_token": "r", "access_token": "a", "expires_at": 9e9})
    await _video(oid, "AC gas refilling", "v1", 8)
    await _video(oid, "Office party tips", "v2", 8)
    await _video(oid, "AC servicing checklist", "v3", 1.5)
    stats = {"v1": {"viewCount": "5000", "likeCount": "300", "commentCount": "40"}, "v2": {"viewCount": "200", "likeCount": "4", "commentCount": "0"},
             "v3": {"viewCount": "900", "likeCount": "50", "commentCount": "6"}}

    class Fake:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a): ...
        async def get(self, url, params=None, headers=None):
            import httpx
            return httpx.Response(200, json={"items": [{"statistics": stats[params["id"]]}]}, request=httpx.Request("GET", url))
    monkeypatch.setattr(eg, "client", Fake)
    assert await eg.collect(oid) == 3      # 7 d for the two old ones (too old for a 24 h reading), 24 h for the new one
    assert await eg.collect(oid) == 0      # once
    d = (await client.get("/org/content/engagement", headers=h["owner"])).json()
    learn = d["learning"]
    assert learn["top_topics"][0] == "AC gas refilling" and "Office party tips" in learn["weak_topics"] and learn["best_platform"] == "youtube"
    assert d["top"][0]["score"] == eg.score({"views": 5000, "likes": 300, "comments": 40})
    ranked = eg.boost([{"topic": "AC gas refilling at home", "score": 20.0}, {"topic": "Office party tips", "score": 21.0}, {"topic": "Other", "score": 20.5}], learn)
    assert [m["score"] for m in ranked] == [22.0, 20.0, 20.5]


async def test_instagram_needs_a_media_id(team_org):
    oid, _h = await team_org(["content_repurposing"])
    async with tenant_session(oid) as conn:
        assert await eg.due(conn, datetime.now(UTC)) == []  # nothing published with an id: nothing to measure
