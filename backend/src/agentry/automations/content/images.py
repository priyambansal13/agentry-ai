"""Quote cards (Phase 6.3): the moment's words on a branded image, no image model needed.

Three templates use the brand kit's two colours and logo: "bold" (quote on the brand colour), "light" (on white with
an accent bar) and "split" (a colour panel beside the quote). Instagram gets a 1080x1080 square; LinkedIn and X a
1200x675 landscape. Text size shrinks until the quote fits; very long quotes are cut at a sentence end.
"""
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZES = {"instagram": (1080, 1080), "linkedin": (1200, 675), "x": (1200, 675)}


def _rgb(hex_color: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (hex_color or "").strip())
    return tuple(int(m[1][i:i + 2], 16) for i in (0, 2, 4)) if m else default  # type: ignore[return-value]


def _ink_on(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]
    return (20, 24, 18) if lum > 150 else (250, 250, 245)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, box_w: int, box_h: int, start: int, smallest: int = 26) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = start
    while True:
        font = _font(size)
        lines = _wrap(draw, text, font, box_w)
        if len(lines) * size * 1.3 <= box_h or size <= smallest:
            return font, lines
        size -= 2


def _shorten(quote: str, limit: int = 260) -> str:
    if len(quote) <= limit:
        return quote
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", quote):
        if len(out) + len(sent) > limit:
            break
        out = f"{out} {sent}".strip()
    return out or quote[:limit].rsplit(" ", 1)[0] + "…"


def render(platform: str, quote: str, speaker: str | None, kit: dict, logo: Path | None = None) -> bytes:
    w, h = SIZES[platform]
    primary = _rgb(kit.get("primary_color"), (31, 42, 26))
    accent = _rgb(kit.get("accent_color"), (200, 240, 74))
    template = kit.get("template") or "bold"
    if template == "light":
        bg, ink, mark = (255, 255, 252), primary, accent
    else:
        bg, ink, mark = primary, _ink_on(primary), accent
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    pad = int(min(w, h) * 0.09)
    left = pad
    if template == "split":
        panel = int(w * 0.28)
        d.rectangle([0, 0, panel, h], fill=accent)
        left = panel + pad
        mark = _ink_on(accent)
        d.text((panel // 2, h // 2), "“", font=_font(int(h * 0.45)), fill=mark, anchor="mm")
    elif template == "light":
        d.rectangle([0, 0, int(w * 0.018), h], fill=accent)
        d.text((left, pad - 10), "“", font=_font(int(h * 0.18)), fill=accent, anchor="lt")
    else:
        d.text((left, pad - 10), "“", font=_font(int(h * 0.18)), fill=accent, anchor="lt")
    top = pad + (0 if template == "split" else int(h * 0.15))
    footer = int(h * 0.16)
    box_w, box_h = w - left - pad, h - top - footer - pad // 2
    text = _shorten(quote)
    font, lines = _fit(d, text, box_w, box_h, start=int(h * (0.075 if w == h else 0.1)))
    y = top
    for line in lines:
        d.text((left, y), line, font=font, fill=ink)
        y += int(font.size * 1.3)
    small = _font(max(22, int(h * 0.034)))
    by = h - pad - small.size
    handle = (kit.get("handle") or "").strip()
    x_right = w - pad
    if logo and logo.is_file():
        try:
            lg = Image.open(logo).convert("RGBA")
            lg.thumbnail((int(h * 0.16), int(h * 0.09)))
            img.paste(lg, (x_right - lg.width, h - pad - lg.height), lg)
            x_right -= lg.width + 16
        except OSError:
            pass  # a broken logo file shouldn't stop the card
    name_w = d.textlength(speaker, font=small) if speaker else 0
    hand_w = d.textlength(handle, font=small) if handle else 0
    if handle and left + name_w + 24 + hand_w > x_right:  # not enough room on one line: the handle goes above the name
        d.text((left, by - int(small.size * 1.5)), handle, font=small, fill=accent if template == "bold" else ink)
        handle = ""
    if speaker:  # (the built-in font has no em dash, so the name stands on its own)
        d.text((left, by), speaker, font=small, fill=ink)
    if handle:
        d.text((x_right, by), handle, font=small, fill=ink if template != "bold" else accent, anchor="ra")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
