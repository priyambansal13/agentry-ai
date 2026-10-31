"""Instagram publishing (content 6.5) through Meta's Facebook Login for Business ("unified login" configuration).

Connect:  /org/connections/instagram/start -> Meta's login dialog (config_id) -> /connect/instagram/callback
          -> code exchanged for a user token, then a long-lived one (about 60 days) -> the Instagram professional
          accounts the person granted (via their Facebook Pages) -> one connection per business (the first account).
Publish:  POST /{ig}/media (image_url + caption) -> wait until the container is FINISHED -> POST /{ig}/media_publish
          -> the post's permalink. The image must be at a public URL (a signed, expiring link to the quote card).
Refresh:  a token with under 10 days left is exchanged for a fresh long-lived one before publishing.
"""
import asyncio
import time
from urllib.parse import urlencode

from agentry.config import settings
from agentry.connectors.http import client


class InstagramError(Exception):
    def __init__(self, message: str, auth: bool = False, transient: bool = False):
        super().__init__(message)
        self.auth = auth  # the token no longer works: the business must reconnect
        self.transient = transient  # try again at the next run


def _secret() -> str | None:
    return settings.meta_app_secret or settings.whatsapp_app_secret


def configured() -> bool:
    return bool(settings.meta_app_id and _secret() and settings.instagram_config_id)


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{path.lstrip('/')}"


def redirect_uri() -> str:
    return settings.api_public_url.rstrip("/") + "/connect/instagram/callback"


def auth_url(state: str) -> str:
    q = {"client_id": settings.meta_app_id, "redirect_uri": redirect_uri(), "state": state, "config_id": settings.instagram_config_id,
         "response_type": "code", "override_default_response_type": "true"}
    return f"https://www.facebook.com/{settings.whatsapp_graph_version}/dialog/oauth?{urlencode(q)}"


async def _get(path: str, **params: object) -> dict:
    async with client(timeout=30) as c:
        r = await c.get(_graph(path), params=params)
    return _check(r)


async def _post(path: str, **params: object) -> dict:
    async with client(timeout=60) as c:
        r = await c.post(_graph(path), data=params)
    return _check(r)


def _check(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error") or {}
        msg = err.get("error_user_msg") or err.get("message") or f"HTTP {r.status_code}"
        raise InstagramError(f"Instagram: {msg}", auth=err.get("code") == 190 or (err.get("type") == "OAuthException" and r.status_code == 401),
                             transient=r.status_code >= 500 or err.get("code") in (1, 2, 4, 17, 32, 613) or bool(err.get("is_transient")))
    return body


async def exchange_code(code: str) -> dict:
    """code -> long-lived user token: {"access_token", "expires_at" (epoch seconds or None = no expiry)}."""
    short = await _get("oauth/access_token", client_id=settings.meta_app_id, client_secret=_secret(), redirect_uri=redirect_uri(), code=code)
    return await extend(short["access_token"])


async def extend(token: str) -> dict:
    long = await _get("oauth/access_token", grant_type="fb_exchange_token", client_id=settings.meta_app_id, client_secret=_secret(),
                      fb_exchange_token=token)
    expires_in = long.get("expires_in")
    return {"access_token": long["access_token"], "expires_at": int(time.time()) + int(expires_in) if expires_in else None}


IG_SCOPES = ("instagram_content_publish", "instagram_business_content_publish", "instagram_basic", "instagram_business_basic")


async def accounts(token: str) -> list[dict]:
    """Instagram professional accounts this person granted: [{id, username, page}]. Two ways: the accounts they ticked
    in Meta's dialog (the token's granular scopes: no Facebook Page needed), and Instagram accounts linked to granted Pages."""
    out: dict[str, dict] = {}
    try:
        info = (await _get("debug_token", input_token=token, access_token=f"{settings.meta_app_id}|{_secret()}")).get("data", {})
        ids = {t for g in info.get("granular_scopes", []) if g.get("scope") in IG_SCOPES for t in g.get("target_ids", [])}
        for ig_id in ids:
            try:
                me = await _get(ig_id, fields="id,username", access_token=token)
                out[ig_id] = {"id": ig_id, "username": me.get("username") or ig_id, "page": None}
            except InstagramError:
                continue  # not an Instagram account (e.g. a Page id under the same scope)
    except InstagramError:
        pass
    try:
        pages = await _get("me/accounts", access_token=token, fields="id,name,instagram_business_account{id,username}", limit=50)
        for p in pages.get("data", []):
            ig = p.get("instagram_business_account")
            if ig:
                out[ig["id"]] = {"id": ig["id"], "username": ig.get("username") or out.get(ig["id"], {}).get("username") or ig["id"], "page": p.get("name")}
    except InstagramError:
        pass
    return list(out.values())


async def fresh_token(secret: dict) -> tuple[str, dict | None]:
    """(token to use, updated secret if it was refreshed)."""
    exp = secret.get("expires_at")
    if exp and exp - time.time() < 10 * 86400:
        new = await extend(secret["access_token"])
        return new["access_token"], {**secret, **new}
    return secret["access_token"], None


async def publish(ig_id: str, token: str, image_url: str, caption: str, *, wait_s: float = 2.0, tries: int = 15) -> dict:
    """Post one image with its caption. Returns {"id", "permalink"}."""
    container = (await _post(f"{ig_id}/media", image_url=image_url, caption=caption[:2200], access_token=token))["id"]
    for _ in range(tries):  # Instagram fetches and processes the image first
        status = (await _get(container, fields="status_code,status", access_token=token)).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError("Instagram couldn't process the image")
        await asyncio.sleep(wait_s)
    else:
        raise InstagramError("Instagram is still processing the image", transient=True)
    media = (await _post(f"{ig_id}/media_publish", creation_id=container, access_token=token))["id"]
    link = (await _get(media, fields="permalink", access_token=token)).get("permalink")
    return {"id": media, "permalink": link}
