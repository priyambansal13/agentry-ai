"""One door to the video models: OpenAI Sora 2 (default) or Google Veo 3.1, and test mode when the chosen provider has
no key (branded test clips, free). Operation names carry their provider ("sora:…", "test:…", Veo's own names)."""
import hashlib
from pathlib import Path

from agentry.automations.video_studio import sora, veo
from agentry.config import settings

COST = {("openai", "fast"): "cost_per_second_sora", ("openai", "standard"): "cost_per_second_sora_pro",
        ("google", "fast"): "cost_per_second_fast", ("google", "standard"): "cost_per_second_standard"}


def test_mode(provider: str) -> bool:
    return not (sora.key() if provider == "openai" else settings.video_api_key)


def model_name(provider: str, quality: str) -> str:
    if test_mode(provider):
        return "test"
    return (sora.MODELS if provider == "openai" else veo.MODELS)[quality]


def rate(cfg: dict) -> float:
    return float(cfg[COST[(cfg["provider"], cfg["quality"])]])


async def start(provider: str, prompt: str, *, quality: str, aspect: str = "9:16", seconds: int = 8) -> str:
    if test_mode(provider):
        return "test:" + hashlib.sha1(prompt.encode()).hexdigest()[:16]
    if provider == "openai":
        return await sora.start(prompt, quality=quality, aspect=aspect, seconds=seconds)
    return await veo.start(prompt, quality=quality, aspect=aspect, seconds=seconds)


async def poll(name: str) -> dict:
    if name.startswith("sora:"):
        return await sora.poll(name)
    return await veo.poll(name)


async def download(uri: str, out: Path, caption: str = "", kit: dict | None = None, seconds: int = 8) -> Path:
    if uri.startswith("sora:"):
        return await sora.download(uri, out)
    return await veo.download(uri, out, caption=caption, kit=kit, seconds=seconds)
