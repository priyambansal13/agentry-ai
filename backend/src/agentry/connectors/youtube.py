"""YouTube for the AI video studio: upload a finished Short to the business's channel.

Connect uses the same Google OAuth client and redirect as Gmail (state "p": "youtube") with the youtube.upload and
youtube.readonly scopes (readonly only to show the channel's name). The YouTube Data API v3 must be enabled in the
Google Cloud project. Uploads are resumable (one session per video). Videos uploaded by an API project that hasn't
passed Google's audit are locked to private by YouTube.
"""
import time
from urllib.parse import urlencode

from agentry.config import settings
from agentry.connectors import gmail
from agentry.connectors.http import client
from agentry.connectors.store import update_state

UPLOAD, READ = "https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = ["openid", "email", UPLOAD, READ]
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubeError(Exception):
    def __init__(self, message: str, auth: bool = False):
        super().__init__(message)
        self.auth = auth


def configured() -> bool:
    return gmail.configured()


def auth_url(state: str, login_hint: str | None = None) -> str:
    params = {"client_id": settings.google_client_id, "redirect_uri": gmail.redirect_uri(), "response_type": "code", "scope": " ".join(SCOPES),
              "access_type": "offline", "prompt": "consent", "state": state, **({"login_hint": login_hint} if login_hint else {})}
    return f"{gmail.AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with client() as c:
        r = await c.post(gmail.TOKEN_URL, data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                                "redirect_uri": gmail.redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise YouTubeError(f"Google rejected the sign-in: {r.text[:200]}")
    tok = r.json()
    if "refresh_token" not in tok:
        raise YouTubeError("Google did not return offline access; remove Agentry from your Google account and connect again")
    if UPLOAD not in set(tok.get("scope", "").split()):
        raise YouTubeError("YouTube upload access was not granted (tick the box to manage your YouTube videos)")
    secret = {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"], "expires_at": time.time() + tok.get("expires_in", 3600) - 60}
    async with client() as c:
        r = await c.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {tok['access_token']}"})
    items = (r.json() if r.status_code == 200 else {}).get("items") or []
    if not items:
        raise YouTubeError("This Google account has no YouTube channel: create one on youtube.com, then connect again")
    return secret | {"channel_id": items[0]["id"], "channel": items[0]["snippet"]["title"]}


class YouTube:
    def __init__(self, org_id: str, connection: dict):
        self.org_id, self.conn = org_id, connection
        self.secret = dict(connection["secret"])

    async def token(self) -> str:
        if self.secret.get("access_token") and self.secret.get("expires_at", 0) > time.time():
            return self.secret["access_token"]
        async with client() as c:
            r = await c.post(gmail.TOKEN_URL, data={"client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                                    "refresh_token": self.secret["refresh_token"], "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise YouTubeError("YouTube access was revoked or expired; reconnect it", auth=True)
        tok = r.json()
        self.secret.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
        await update_state(self.org_id, self.conn["id"], secret=self.secret)
        return self.secret["access_token"]

    async def upload(self, data: bytes, *, title: str, description: str, tags: list[str], privacy: str, language: str | None = None) -> dict:
        """Resumable upload in one go. Returns {"id", "url", "privacy"} (privacy as YouTube set it)."""
        meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15], "categoryId": "22",
                            **({"defaultLanguage": language, "defaultAudioLanguage": language} if language else {})},
                "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
        token = await self.token()
        async with client(timeout=120) as c:
            r = await c.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=meta,
                             headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))})
            if r.status_code >= 400:
                raise YouTubeError(f"YouTube {r.status_code}: {r.text[:300]}", auth=r.status_code in (401, 403))
            r = await c.put(r.headers["Location"], content=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
        if r.status_code >= 400:
            raise YouTubeError(f"YouTube {r.status_code}: {r.text[:300]}", auth=r.status_code in (401, 403))
        v = r.json()
        return {"id": v["id"], "url": f"https://youtube.com/shorts/{v['id']}", "privacy": (v.get("status") or {}).get("privacyStatus", privacy)}
