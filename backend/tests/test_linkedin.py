"""LinkedIn publishing (content 8.1) against a fake LinkedIn: connect (posting must be granted), post the quote card
with the text (reserved characters escaped), keep the link; an expired token holds posts and marks the connection."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import text
from test_content import sample_source

from agentry.automations.content import calendar
from agentry.config import settings
from agentry.connectors import http, linkedin
from agentry.db import tenant_session


class FakeLinkedIn:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.scope = "openid profile w_member_social"
        self.dead = False

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path, req.content))
        if self.dead and req.url.host == "api.linkedin.com":
            return httpx.Response(401, json={"message": "Expired access token"})
        if req.url.path == "/oauth/v2/accessToken":
            return httpx.Response(200, json={"access_token": "LI", "expires_in": 5184000, "scope": self.scope})
        if req.url.path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "abc123", "name": "Priyam Bansal"})
        if req.url.path == "/rest/images":
            return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin.example/img1", "image": "urn:li:image:img1"}})
        if req.url.host == "upload.linkedin.example":
            return httpx.Response(201)
        if req.url.path == "/rest/posts":
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:777"})
        return httpx.Response(404, json={"message": "unexpected"})


@pytest.fixture
def li(monkeypatch):
    f = FakeLinkedIn()
    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(f.handle))
    monkeypatch.setattr(settings, "linkedin_client_id", "cid")
    monkeypatch.setattr(settings, "linkedin_client_secret", "csecret")
    return f


async def connect(client, h):
    r = await client.post("/org/connections/linkedin/start", headers=h["owner"])
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["scope"] == ["openid profile w_member_social"]
    return await client.get(f"/connect/linkedin/callback?code=c&state={q['state'][0]}")


def test_little_text_escapes_reserved_characters():
    assert linkedin.little_text("Hi (all) #dental *now* @team") == r"Hi \(all\) \#dental \*now\* \@team"


async def test_connect_requires_posting_permission(client, team_org, li):
    oid, h = await team_org(["content_repurposing"])
    li.scope = "openid profile"
    bad = await connect(client, h)
    assert "error=" in bad.headers["location"] and "w_member_social" in bad.headers["location"]
    li.scope = "openid profile w_member_social"
    ok = await connect(client, h)
    assert "connected=linkedin" in ok.headers["location"]
    async with tenant_session(oid) as conn:
        assert tuple((await conn.execute(text("select account_ref, display_name from app.connections where provider = 'linkedin'"))).one()) \
            == ("urn:li:person:abc123", "Priyam Bansal")


async def test_post_with_card_then_expired_token_holds(client, team_org, li):
    oid, h = await team_org(["content_repurposing"])
    await connect(client, h)
    sid = await sample_source(client, h, oid)
    async with tenant_session(oid) as conn:
        pids = (await conn.execute(text("""select id::text from app.content_posts where source_id = cast(:s as uuid) and platform = 'linkedin'
            and image_path is not null order by created_at limit 2"""), {"s": sid})).scalars().all()
        await conn.execute(text("""update app.content_posts set review = 'approved', scheduled_at = now() - interval '1 minute'
            where id = cast(:i as uuid)"""), {"i": pids[0]})
    assert await calendar.publish_due(oid) == {"published": 1, "failed": 0}
    post = json.loads(next(c[2] for c in li.calls if c[1] == "/rest/posts"))
    assert post["author"] == "urn:li:person:abc123" and post["content"] == {"media": {"id": "urn:li:image:img1"}} and post["visibility"] == "PUBLIC"
    assert any(c[1] == "/img1" and c[0] == "PUT" for c in li.calls)
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select publish_ref from app.content_posts where id = cast(:i as uuid)"), {"i": pids[0]})).scalar_one() \
            == "https://www.linkedin.com/feed/update/urn:li:share:777/"
        await conn.execute(text("""update app.content_posts set review = 'approved', scheduled_at = now() - interval '1 minute'
            where id = cast(:i as uuid)"""), {"i": pids[1]})
    li.dead = True
    assert await calendar.publish_due(oid) == {"published": 0, "failed": 0}
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select published_at from app.content_posts where id = cast(:i as uuid)"), {"i": pids[1]})).scalar_one() is None
        assert (await conn.execute(text("select status from app.connections where provider = 'linkedin'"))).scalar_one() == "error"
