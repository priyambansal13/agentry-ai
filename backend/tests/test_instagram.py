"""Instagram publishing (content 6.5) against a fake Meta Graph API: connect through the unified login, post the quote
card (as JPEG at a signed public link) with its caption, keep the permalink; a dead token marks the connection broken
and holds posts (never "test mode" once a business has connected Instagram); a temporary error retries."""
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from PIL import Image
from sqlalchemy import text
from test_content import sample_source

from agentry.automations.content import calendar
from agentry.config import settings
from agentry.connectors import http, instagram
from agentry.db import tenant_session
from agentry.secrets import sign_state


class FakeMeta:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.token_dead = False
        self.processing = 0  # how many status checks say IN_PROGRESS first
        self.pages = [{"id": "p1", "name": "Rao Clinic", "instagram_business_account": {"id": "ig123", "username": "raoclinic"}}]
        self.granted: list[str] = []  # Instagram ids ticked in Meta's dialog (granular scopes)

    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.split("/", 2)[-1]  # drop the /vNN.0 prefix
        params = dict(req.url.params) | ({k: v[0] for k, v in parse_qs(req.content.decode()).items()} if req.method == "POST" else {})
        self.calls.append((req.method, path, params))
        if self.token_dead and "access_token" in params:
            return httpx.Response(400, json={"error": {"message": "Error validating access token", "type": "OAuthException", "code": 190}})
        if path == "oauth/access_token":
            if params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(200, json={"access_token": "LONG", "expires_in": 5184000})
            return httpx.Response(200, json={"access_token": "SHORT"})
        if path == "debug_token":
            return httpx.Response(200, json={"data": {"granular_scopes": [{"scope": "instagram_business_content_publish", "target_ids": self.granted},
                                                                          {"scope": "pages_show_list", "target_ids": ["p1"]}]}})
        if path == "ig777":
            return httpx.Response(200, json={"id": "ig777", "username": "funkyshunkycartoon"})
        if path == "me/accounts":
            return httpx.Response(200, json={"data": self.pages})
        if path == "ig123/media":
            return httpx.Response(200, json={"id": "container1"})
        if path == "container1":
            if self.processing:
                self.processing -= 1
                return httpx.Response(200, json={"status_code": "IN_PROGRESS"})
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if path == "ig123/media_publish":
            return httpx.Response(200, json={"id": "media9"})
        if path == "media9":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/ABC123/"})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})


@pytest.fixture
def meta(monkeypatch):
    f = FakeMeta()
    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(f.handle))
    monkeypatch.setattr(settings, "meta_app_id", "1419")
    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    monkeypatch.setattr(settings, "instagram_config_id", "cfg77")
    monkeypatch.setattr(instagram.asyncio, "sleep", _no_sleep)
    return f


async def _no_sleep(_s):
    return None


async def connect(client, h, oid, users_owner_id=None) -> httpx.Response:
    r = await client.post("/org/connections/instagram/start", headers=h["owner"])
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["config_id"] == ["cfg77"] and q["redirect_uri"] == [f"{settings.api_public_url.rstrip('/')}/connect/instagram/callback"]
    return await client.get(f"/connect/instagram/callback?code=abc&state={q['state'][0]}")


async def ready_instagram_post(client, h, oid) -> str:
    """A sample recording processed, one Instagram post approved and due now."""
    sid = await sample_source(client, h, oid)
    async with tenant_session(oid) as conn:
        pid = (await conn.execute(text("""select id::text from app.content_posts where source_id = cast(:s as uuid) and platform = 'instagram'
            and image_path is not null order by created_at limit 1"""), {"s": sid})).scalar_one()
        await conn.execute(text("""update app.content_posts set review = 'approved', scheduled_at = now() - interval '1 minute' where id = cast(:i as uuid)"""),
                           {"i": pid})
    return pid


async def test_connect_through_the_unified_login(client, team_org, meta):
    oid, h = await team_org(["content_repurposing"])
    assert (await client.post("/org/connections/instagram/start", headers=h["staff"])).status_code == 403
    r = await connect(client, h, oid)
    assert r.status_code == 303 and "connected=instagram" in r.headers["location"] and "account=%40raoclinic" in r.headers["location"]
    async with tenant_session(oid) as conn:
        row = (await conn.execute(text("select account_ref, display_name, status from app.connections where provider = 'instagram'"))).one()
    assert tuple(row) == ("ig123", "@raoclinic", "connected")
    assert [c[2].get("grant_type") for c in meta.calls if c[1] == "oauth/access_token"] == [None, "fb_exchange_token"]  # long-lived token
    meta.pages, meta.granted = [], ["ig777"]  # ticked in the dialog, no Facebook Page
    direct = await connect(client, h, oid)
    assert "account=%40funkyshunkycartoon" in direct.headers["location"]
    meta.pages, meta.granted = [{"id": "p2", "name": "No IG page"}], []
    bad = await connect(client, h, oid)
    assert "error=" in bad.headers["location"] and "professional" in bad.headers["location"]


async def test_post_goes_out_with_the_card_as_jpeg(client, team_org, meta):
    oid, h = await team_org(["content_repurposing"])
    await connect(client, h, oid)
    pid = await ready_instagram_post(client, h, oid)
    meta.processing = 2
    assert await calendar.publish_due(oid) == {"published": 1, "failed": 0}
    create = next(c for c in meta.calls if c[1] == "ig123/media")
    async with tenant_session(oid) as conn:
        post = (await conn.execute(text("select body, published_at, publish_ref, publish_error from app.content_posts where id = cast(:i as uuid)"),
                                   {"i": pid})).mappings().one()
        event = (await conn.execute(text("select payload from app.events where type = 'content.published'"))).scalar_one()
    assert create[2]["caption"] == post["body"] and create[2]["access_token"] == "LONG"
    assert post["publish_ref"] == "https://www.instagram.com/p/ABC123/" and post["published_at"] and post["publish_error"] is None
    assert event == {"post_id": pid, "platform": "instagram", "url": "https://www.instagram.com/p/ABC123/"}
    image = await client.get(urlparse(create[2]["image_url"]).path)  # what Instagram downloads: a JPEG, no sign-in
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg" and Image.open(io.BytesIO(image.content)).format == "JPEG"
    assert (await client.get("/public/content-image/" + sign_state({"p": "other", "org": oid, "post": pid}))).status_code == 404
    assert (await client.get("/public/content-image/forged.token")).status_code == 404


async def test_dead_token_breaks_the_connection_and_holds_posts(client, team_org, meta):
    oid, h = await team_org(["content_repurposing"])
    await connect(client, h, oid)
    pid = await ready_instagram_post(client, h, oid)
    meta.token_dead = True
    assert await calendar.publish_due(oid) == {"published": 0, "failed": 0}
    assert await calendar.publish_due(oid) == {"published": 0, "failed": 0}  # waits: not "test mode", not failed
    async with tenant_session(oid) as conn:
        post = (await conn.execute(text("select published_at, publish_error from app.content_posts where id = cast(:i as uuid)"), {"i": pid})).one()
        status = (await conn.execute(text("select status from app.connections where provider = 'instagram'"))).scalar_one()
        broken = (await conn.execute(text("select payload->>'provider' from app.events where type = 'connection.broken'"))).scalars().all()
    assert tuple(post) == (None, None) and status == "error" and broken == ["instagram"]


async def test_still_processing_retries_and_old_tokens_refresh(client, team_org, meta):
    oid, h = await team_org(["content_repurposing"])
    await connect(client, h, oid)
    pid = await ready_instagram_post(client, h, oid)
    meta.processing = 99  # never finishes this run
    assert await calendar.publish_due(oid) == {"published": 0, "failed": 0}
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select publish_error from app.content_posts where id = cast(:i as uuid)"), {"i": pid})).scalar_one() is None
    from agentry.connectors.store import get_connection, update_state
    c = await get_connection(oid, "instagram")
    await update_state(oid, c["id"], secret={**c["secret"], "access_token": "OLD", "expires_at": int((datetime.now(UTC) + timedelta(days=3)).timestamp())})
    meta.processing, meta.calls = 0, []
    assert await calendar.publish_due(oid) == {"published": 1, "failed": 0}
    assert meta.calls[0][2].get("fb_exchange_token") == "OLD" and next(c for c in meta.calls if c[1] == "ig123/media")[2]["access_token"] == "LONG"
