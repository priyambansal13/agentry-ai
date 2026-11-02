"""Veo 3.1 through the Gemini API: start a generation, poll it, download the video.

    start     POST models/{model}:predictLongRunning {"instances": [{"prompt"}], "parameters": {aspectRatio, durationSeconds,
              negativePrompt}} -> an operation name
    poll      GET {operation} until "done"; the video is response.generateVideoResponse.generatedSamples[0].video.uri
    download  GET that uri with the API key (it redirects to the file)
Without settings.video_api_key everything runs in test mode: the "operation" is done at once and the clip is a plain
branded test card made with ffmpeg, so the whole studio can be tried (and tested) without cost.
"""
import asyncio
import hashlib
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from agentry.automations.content import images
from agentry.config import settings
from agentry.connectors.http import client

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = {"fast": "veo-3.1-fast-generate-preview", "standard": "veo-3.1-generate-preview"}
NEGATIVE = "text, captions, subtitles, watermark, logo, distorted faces, extra fingers, low quality"


class VeoError(RuntimeError):
    def __init__(self, message: str, retry: bool = False):
        super().__init__(message)
        self.retry = retry


def test_mode() -> bool:
    return not settings.video_api_key


def _headers() -> dict:
    return {"x-goog-api-key": settings.video_api_key or "", "Content-Type": "application/json"}


async def start(prompt: str, *, quality: str = "fast", aspect: str = "9:16", seconds: int = 8) -> str:
    if test_mode():
        return "test:" + hashlib.sha1(prompt.encode()).hexdigest()[:16]
    body = {"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": aspect, "durationSeconds": seconds, "negativePrompt": NEGATIVE}}
    async with client(timeout=60) as c:
        r = await c.post(f"{BASE}/models/{MODELS[quality]}:predictLongRunning", json=body, headers=_headers())
    if r.status_code == 429 or r.status_code >= 500:
        raise VeoError(f"Veo is busy ({r.status_code})", retry=True)
    if r.status_code >= 400:
        raise VeoError(f"Veo refused the request: {r.text[:300]}")
    return r.json()["name"]


async def poll(name: str) -> dict:
    """{"done": bool, "uri": str | None, "error": str | None}"""
    if name.startswith("test:"):
        return {"done": True, "uri": name, "error": None}
    async with client(timeout=30) as c:
        r = await c.get(f"{BASE}/{name}", headers=_headers())
    if r.status_code >= 500 or r.status_code == 429:
        return {"done": False, "uri": None, "error": None}
    if r.status_code >= 400:
        return {"done": True, "uri": None, "error": f"Veo {r.status_code}: {r.text[:200]}"}
    op = r.json()
    if not op.get("done"):
        return {"done": False, "uri": None, "error": None}
    if op.get("error"):
        return {"done": True, "uri": None, "error": (op["error"].get("message") or "Veo failed")[:300]}
    resp = op.get("response") or {}
    samples = (resp.get("generateVideoResponse") or {}).get("generatedSamples") or resp.get("generatedVideos") or []
    uri = ((samples[0] if samples else {}).get("video") or {}).get("uri")
    if not uri:
        reasons = (resp.get("generateVideoResponse") or {}).get("raiMediaFilteredReasons") or []
        return {"done": True, "uri": None, "error": "Veo filtered the scene: " + "; ".join(reasons)[:200] if reasons else "Veo returned no video"}
    return {"done": True, "uri": uri, "error": None}


async def download(uri: str, out: Path, caption: str = "", kit: dict | None = None, seconds: int = 8, aspect: str = "9:16") -> Path:
    if uri.startswith("test:"):
        return await test_clip(out, caption, kit or {}, seconds, aspect)
    async with client(timeout=180) as c:
        r = await c.get(uri, headers={"x-goog-api-key": settings.video_api_key or ""}, follow_redirects=True)
    if r.status_code >= 400 or not r.content:
        raise VeoError(f"couldn't download the video ({r.status_code})", retry=r.status_code >= 500)
    out.write_bytes(r.content)
    return out


async def test_clip(out: Path, caption: str, kit: dict, seconds: int = 8, aspect: str = "9:16") -> Path:
    """A branded test card (brand colour, 'TEST MODE', the scene's caption) with a quiet tone: no cost, no network."""
    w, h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
    primary = images._rgb(kit.get("primary_color"), (31, 42, 26))
    img = Image.new("RGB", (w, h), primary)
    d = ImageDraw.Draw(img)
    ink = images._ink_on(primary)
    d.text((w / 2, h * 0.3), "TEST MODE", font=images._font(70), fill=ink, anchor="mm")
    font, lines = images._fit(d, caption or "Scene", w - 200, int(h * 0.4), start=80, smallest=44)
    y = h * 0.45
    for ln in lines:
        d.text((w / 2, y), ln, font=font, fill=ink, anchor="ma")
        y += int(font.size * 1.25)
    with tempfile.TemporaryDirectory() as t:
        png = Path(t) / "card.png"
        img.save(png)
        proc = await asyncio.create_subprocess_exec(
            shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-y", "-loop", "1", "-i", str(png), "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
            "-t", str(seconds), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-af", "volume=0.05",
            "-shortest", str(out), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
    if proc.returncode:
        raise VeoError(f"ffmpeg failed: {err.decode(errors='ignore')[-200:]}")
    return out
