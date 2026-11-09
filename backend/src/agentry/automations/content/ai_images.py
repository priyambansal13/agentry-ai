"""AI images (ROADMAP-V2 8.7): an opt-in generated background behind a moment's quote cards.

    switch    off by default; per business in the brand kit (ai_images), with a style ("soft watercolour, pastel") and a
              monthly cap (images_per_month); every image's cost is recorded in llm_calls (prompt_key ai_image) and the
              month's count and spend show on the brand kit
    prompt    built here, never free text from a customer: the business's style + the moment's topic, plus fixed rules:
              no people, faces, hands or bodies, no text, letters, logos or watermarks, calm space for the quote
    check     the vision model looks at the result; anything showing people or text is retried once, then dropped (the card
              is drawn as before, without a background)
    use       one background per moment, shared by its LinkedIn / Instagram / X cards (each cropped to its size); the
              card lays it under a brand-colour veil so the quote stays readable. "New background" makes another.
"""
import base64
import io
import json
import time
from datetime import UTC, datetime

from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.content import images, sources
from agentry.config import settings
from agentry.llm.gateway import AllModelsFailed, _record, complete, has_key

RULES = ("No people, no faces, no hands, no bodies or silhouettes of people. No text, letters, numbers, logos or watermarks. "
         "Leave calm, uncluttered space in the middle for a quote to be written over it. Square format.")
DEFAULT_STYLE = "a soft, modern abstract illustration with gentle shapes and light"
CHECK = """Look at this image. Answer in JSON: {"people": true/false, "text": true/false}.
"people" = any person, face, hand, body or silhouette of a person (furniture and objects shaped like parts of a body are not people). "text" = any readable letters, numbers or logos."""


class ImageError(RuntimeError):
    pass


def prompt_for(kit: dict, moment: dict) -> str:
    style = (kit.get("image_style") or DEFAULT_STYLE).strip()[:300]
    topic = (moment.get("topic") or moment.get("insight") or moment.get("hook") or moment.get("quote") or "").strip()[:240]
    return (f"Background image in this style: {style}. Show simple objects, textures, nature or abstract shapes that suggest "
            f"this idea (not a scene with people or furniture people sit on): {topic}. {RULES}")


def mock_png(kit: dict, seed: str) -> bytes:
    """Test mode: a brand-colour gradient with soft circles (no network, no cost)."""
    a, b = images._rgb(kit.get("primary_color"), (31, 42, 26)), images._rgb(kit.get("accent_color"), (200, 240, 74))
    img = Image.new("RGB", (1024, 1024))
    d = ImageDraw.Draw(img)
    for y in range(1024):
        t = y / 1023
        d.line([(0, y), (1024, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    h = abs(hash(seed))
    for k in range(4):
        x, y, r = (h >> (k * 5)) % 900, (h >> (k * 7)) % 900, 80 + (h >> k) % 160
        d.ellipse([x, y, x + r, y + r], outline=b, width=6)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def live() -> bool:
    return settings.model_image != "mock" and has_key(settings.model_image)


async def generate(org_id: str, prompt: str, kit: dict) -> tuple[bytes, float]:
    """One 1024x1024 image. Returns (png, cost in USD); test mode costs nothing."""
    if not live():
        return mock_png(kit, prompt), 0.0
    import litellm
    t0 = time.monotonic()
    try:
        resp = await litellm.aimage_generation(model=settings.model_image, prompt=prompt, n=1, size="1024x1024",
                                               quality=settings.image_quality)
        item = resp.data[0]
        if getattr(item, "b64_json", None):
            png = base64.b64decode(item.b64_json)
        else:
            from agentry.connectors.http import client
            async with client() as c:
                png = (await c.get(item.url)).content
        cost = float((getattr(resp, "_hidden_params", None) or {}).get("response_cost") or 0) or settings.image_cost_usd
    except Exception as e:
        await _record(org_id, "image", settings.model_image, "ai_image", "v1", 0, 0, 0.0, int((time.monotonic() - t0) * 1000), "error", str(e)[:500])
        raise ImageError(type(e).__name__) from e
    await _record(org_id, "image", settings.model_image, "ai_image", "v1", 0, 0, cost, int((time.monotonic() - t0) * 1000), "ok", None)
    return png, cost


async def shows_people_or_text(org_id: str, png: bytes) -> bool:
    if not live():
        return False
    msg = [{"role": "user", "content": [{"type": "text", "text": CHECK},
                                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]
    try:
        r = await complete("vision", msg, org_id=org_id, prompt_key="ai_image_check", prompt_version="v1", json_output=True,
                           mock_response=json.dumps({"people": False, "text": False}))
    except AllModelsFailed:
        return True  # can't check it: don't use it
    d = r.data or {}
    return bool(d.get("people")) or bool(d.get("text"))


async def month_usage(conn: AsyncConnection) -> dict:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = (await conn.execute(text("""select count(*) as n, coalesce(sum(cost_usd), 0) as usd from app.llm_calls
        where prompt_key = 'ai_image' and status = 'ok' and at >= :s"""), {"s": start})).mappings().one()
    made = (await conn.execute(text("select count(*) from app.content_moments where ai_bg_path is not null"))).scalar_one()
    return {"images": int(row["n"]), "usd": round(float(row["usd"]), 3), "per_image_usd": settings.image_cost_usd,
            "test_mode": not live(), "backgrounds": int(made)}


async def background(conn: AsyncConnection, org_id: str, kit: dict, moment: dict, *, again: bool = False) -> str | None:
    """The moment's background (made once, or again on request). None when switched off, over the cap, or unsafe."""
    if not kit.get("ai_images"):
        return None
    if moment.get("ai_bg_path") and not again:
        return moment["ai_bg_path"]
    if live() and (await month_usage(conn))["images"] >= int(kit.get("images_per_month") or 0):
        return moment.get("ai_bg_path")
    prompt = prompt_for(kit, moment)
    for _attempt in range(2):
        try:
            png, _cost = await generate(org_id, prompt, kit)
        except ImageError:
            return moment.get("ai_bg_path")
        if not await shows_people_or_text(org_id, png):
            path = sources.folder(org_id, "backgrounds") / f"{moment['id']}-{int(time.time())}.png"
            path.write_bytes(png)
            rel = sources.relative(path)
            await conn.execute(text("update app.content_moments set ai_bg_path = :p where id = cast(:i as uuid)"), {"p": rel, "i": str(moment["id"])})
            return rel
        prompt += " Absolutely no people and no writing of any kind."
    return moment.get("ai_bg_path")
