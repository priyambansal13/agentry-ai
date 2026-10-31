"""LinkedIn publishing (content 8.1): posts on a person's LinkedIn profile ("Share on LinkedIn", w_member_social).

Connect:  /org/connections/linkedin/start -> LinkedIn's sign-in (openid profile w_member_social) -> /connect/linkedin/callback
          -> access token (about 60 days; LinkedIn gives refresh tokens only to approved partners, so a reminder to
          reconnect goes out 7 days before it expires) -> the member's id from /v2/userinfo.
Publish:  upload the quote card (images API: initializeUpload, then PUT the bytes) -> POST /rest/posts with the
          commentary (LinkedIn's "little text" format: reserved characters escaped) -> the post's URN -> its link.
Company pages need LinkedIn's Community Management API (an application LinkedIn reviews): not in this version.
"""
import re
import time
from urllib.parse import urlencode

from agentry.config import settings
from agentry.connectors.http import client

AUTH = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = "openid profile w_member_social"
RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


class LinkedInError(Exception):
    def __init__(self, message: str, auth: bool = False, transient: bool = False):
        super().__init__(message)
        self.auth, self.transient = auth, transient


def configured() -> bool:
    return bool(settings.linkedin_client_id and settings.linkedin_client_secret)


def redirect_uri() -> str:
    return settings.api_public_url.rstrip("/") + "/connect/linkedin/callback"


def auth_url(state: str) -> str:
    return f"{AUTH}?{urlencode({'response_type': 'code', 'client_id': settings.linkedin_client_id, 'redirect_uri': redirect_uri(), 'state': state, 'scope': SCOPES})}"


def _raise(r) -> None:
    try:
        body = r.json()
    except ValueError:
        body = {}
    msg = body.get("message") or body.get("error_description") or f"HTTP {r.status_code}"
    raise LinkedInError(f"LinkedIn: {msg}", auth=r.status_code == 401, transient=r.status_code >= 500 or r.status_code == 429)


async def exchange_code(code: str) -> dict:
    async with client() as c:
        r = await c.post(TOKEN, data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                                      "client_id": settings.linkedin_client_id, "client_secret": settings.linkedin_client_secret})
    if r.status_code != 200:
        _raise(r)
    tok = r.json()
    if "w_member_social" not in tok.get("scope", ""):
        raise LinkedInError("LinkedIn didn't grant posting (w_member_social): is 'Share on LinkedIn' added to the LinkedIn app?")
    async with client() as c:
        me = await c.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"})
    if me.status_code != 200:
        _raise(me)
    info = me.json()
    return {"access_token": tok["access_token"], "expires_at": int(time.time()) + int(tok.get("expires_in", 5184000)),
            "person": f"urn:li:person:{info['sub']}", "name": info.get("name") or "LinkedIn member"}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "LinkedIn-Version": settings.linkedin_version, "X-Restli-Protocol-Version": "2.0.0"}


def little_text(s: str) -> str:
    """LinkedIn's commentary format treats some characters as markup: escape them so the post reads as written."""
    return RESERVED.sub(r"\\\1", s)


async def publish(secret: dict, image: bytes | None, text: str) -> dict:
    """Post to the member's feed (with the image if given). Returns {"id", "permalink"}."""
    if secret.get("expires_at") and secret["expires_at"] < time.time():
        raise LinkedInError("LinkedIn access expired: reconnect it", auth=True)
    token, author = secret["access_token"], secret["person"]
    content = None
    async with client(timeout=60) as c:
        if image:
            r = await c.post(f"{API}/rest/images?action=initializeUpload", headers=_headers(token),
                             json={"initializeUploadRequest": {"owner": author}})
            if r.status_code >= 400:
                _raise(r)
            up = r.json()["value"]
            put = await c.put(up["uploadUrl"], content=image, headers={"Authorization": f"Bearer {token}"})
            if put.status_code >= 400:
                _raise(put)
            content = {"media": {"id": up["image"]}}
        body = {"author": author, "commentary": little_text(text[:3000]), "visibility": "PUBLIC", "lifecycleState": "PUBLISHED",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "isReshareDisabledByAuthor": False, **({"content": content} if content else {})}
        r = await c.post(f"{API}/rest/posts", headers=_headers(token), json=body)
    if r.status_code not in (200, 201):
        _raise(r)
    urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or ""
    return {"id": urn, "permalink": f"https://www.linkedin.com/feed/update/{urn}/" if urn else None}
