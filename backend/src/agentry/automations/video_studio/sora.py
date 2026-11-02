"""Sora 2 through the OpenAI Videos API: start a render, poll it, download the MP4.

    start     POST /v1/videos (multipart): model sora-2 / sora-2-pro, prompt, size 720x1280 (vertical), seconds 4 / 8 / 12
              -> {"id": "video_...", "status": "queued"}
    poll      GET /v1/videos/{id}: queued / in_progress -> completed or failed (error.message)
    download  GET /v1/videos/{id}/content -> the MP4
Uses the same OPENAI_API_KEY as the language models.
"""
import os
from pathlib import Path

from agentry.automations.video_studio.veo import VeoError
from agentry.connectors.http import client

BASE = "https://api.openai.com/v1/videos"
MODELS = {"fast": "sora-2", "standard": "sora-2-pro"}
SIZES = {"9:16": "720x1280", "16:9": "1280x720"}


def key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def _auth() -> dict:
    return {"Authorization": f"Bearer {key() or ''}"}


async def start(prompt: str, *, quality: str = "fast", aspect: str = "9:16", seconds: int = 8) -> str:
    form = {"model": (None, MODELS[quality]), "prompt": (None, prompt), "size": (None, SIZES[aspect]), "seconds": (None, str(seconds))}
    async with client(timeout=60) as c:
        r = await c.post(BASE, files=form, headers=_auth())
    if r.status_code == 429 or r.status_code >= 500:
        raise VeoError(f"Sora is busy ({r.status_code})", retry=True)
    if r.status_code >= 400:
        raise VeoError(f"Sora refused the request ({r.status_code}): {r.text[:300]}")
    return "sora:" + r.json()["id"]


async def poll(name: str) -> dict:
    vid = name.removeprefix("sora:")
    async with client(timeout=30) as c:
        r = await c.get(f"{BASE}/{vid}", headers=_auth())
    if r.status_code >= 500 or r.status_code == 429:
        return {"done": False, "uri": None, "error": None}
    if r.status_code >= 400:
        return {"done": True, "uri": None, "error": f"Sora {r.status_code}: {r.text[:200]}"}
    v = r.json()
    if v.get("status") == "completed":
        return {"done": True, "uri": name, "error": None}
    if v.get("status") == "failed":
        return {"done": True, "uri": None, "error": ((v.get("error") or {}).get("message") or "Sora failed")[:300]}
    return {"done": False, "uri": None, "error": None}


async def download(name: str, out: Path) -> Path:
    async with client(timeout=180) as c:
        r = await c.get(f"{BASE}/{name.removeprefix('sora:')}/content", headers=_auth(), follow_redirects=True)
    if r.status_code >= 400 or not r.content:
        raise VeoError(f"couldn't download the video ({r.status_code})", retry=r.status_code >= 500)
    out.write_bytes(r.content)
    return out
