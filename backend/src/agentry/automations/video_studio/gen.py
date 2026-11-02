"""One door to the video model: Google Veo 3.1, or test mode when there's no key (branded test clips, free).

OpenAI removed its Videos API (Sora 2 / Sora 2 Pro) on 24 Sep 2026 with no replacement, so Veo is the video model.
Its key: AGENTRY_VIDEO_API_KEY, else the GEMINI_API_KEY the language models use (Veo needs a paid Gemini API plan).
"""
import hashlib
import os
from pathlib import Path

from agentry.automations.video_studio import veo

COST = {"fast": "cost_per_second_fast", "standard": "cost_per_second_standard"}


def key() -> str | None:
    from agentry.config import settings
    return settings.video_api_key or os.environ.get("GEMINI_API_KEY") or None


def test_mode(provider: str = "google") -> bool:
    return not key()


def model_name(provider: str, quality: str) -> str:
    return "test" if test_mode() else veo.MODELS[quality]


def rate(cfg: dict) -> float:
    return float(cfg[COST[cfg["quality"]]])


async def start(provider: str, prompt: str, *, quality: str, aspect: str = "9:16", seconds: int = 8) -> str:
    if test_mode():
        return "test:" + hashlib.sha1(prompt.encode()).hexdigest()[:16]
    return await veo.start(prompt, quality=quality, aspect=aspect, seconds=seconds)


async def poll(name: str) -> dict:
    return await veo.poll(name)


async def download(uri: str, out: Path, caption: str = "", kit: dict | None = None, seconds: int = 8) -> Path:
    return await veo.download(uri, out, caption=caption, kit=kit, seconds=seconds)
