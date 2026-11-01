"""Vertical clips (ROADMAP-V2 8.2): each best moment of a video, cut as a 9:16 Reel/Short with burned-in captions.

    window     the moment snapped to whole transcript segments, then grown or trimmed to 20-60 s (a clip never starts
               or ends mid-sentence when the transcript allows it)
    captions   from the transcript: each segment split into short lines (<= 5 words), timed by word count inside it
    framing    centre crop to 1080x1920 (a landscape video keeps the middle, where the speaker usually is); face
               tracking later
    brand      the moment's hook as a banner for the first 3 s, the captions in a dark box with a brand-colour bar,
               and a 2 s end card (brand colour, logo or handle) after the speech
Captions, banner and end card are drawn with Pillow and laid over the video by ffmpeg, so any ffmpeg build works (no
libass or freetype needed). Video sources only; a moment past the end of the file is skipped, not failed.
"""
import asyncio
import io
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.content import brand, images, sources

W, H = 1080, 1920
MIN_S, MAX_S, PAD = 20.0, 60.0, 0.3
HOOK_S, OUTRO_S, WORDS_PER_LINE = 3.0, 2.0, 5


class ClipError(RuntimeError):
    pass


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def window(segments: list[dict], start: float, end: float, video_s: float) -> tuple[float, float]:
    """Clip bounds in seconds: whole segments covering the moment, grown to MIN_S and trimmed to MAX_S."""
    segs = [s for s in segments if s["start"] < video_s]
    inside = [s for s in segs if s["end"] > start and s["start"] < end] or [s for s in segs if s["start"] >= start][:1]
    if not inside:
        raise ClipError("the moment is past the end of the video")
    a, b = inside[0]["start"], inside[-1]["end"]
    later = [s for s in segs if s["start"] >= b]
    while b - a < MIN_S and later:
        b = later.pop(0)["end"]
    earlier = [s for s in segs if s["end"] <= a]
    while b - a < MIN_S and earlier:
        a = earlier.pop()["start"]
    if b - a > MAX_S:
        fits = [s["end"] for s in segs if a < s["end"] <= a + MAX_S]
        b = max(fits) if fits and max(fits) - a >= MIN_S else a + MAX_S
    a, b = max(0.0, a - PAD), min(video_s, b + PAD)
    return round(a, 2), round(b, 2)


def captions(segments: list[dict], a: float, b: float) -> list[tuple[float, float, str]]:
    """(start, end, line) relative to the clip, at most WORDS_PER_LINE words each."""
    out = []
    for s in segments:
        if s["end"] <= a or s["start"] >= b:
            continue
        words = s["text"].split()
        if not words:
            continue
        per = (s["end"] - s["start"]) / len(words)
        for i in range(0, len(words), WORDS_PER_LINE):
            t0 = s["start"] + i * per
            t1 = s["start"] + min(len(words), i + WORDS_PER_LINE) * per
            if min(t1, b) - max(t0, a) < 0.4:  # a sliver of a line at the edge of the clip would only flash
                continue
            out.append((round(max(t0, a) - a, 2), round(min(t1, b) - a, 2), " ".join(words[i:i + WORDS_PER_LINE])))
    return out


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def caption_png(line: str, kit: dict) -> bytes:
    """A caption box for the lower third: white text on a dark rounded box with a brand-colour bar."""
    accent = images._rgb(kit.get("accent_color"), (200, 240, 74))
    img = Image.new("RGBA", (W, 320), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font, lines = images._fit(d, line, W - 200, 220, start=64, smallest=40)
    tw = max(d.textlength(x, font=font) for x in lines)
    th = len(lines) * int(font.size * 1.25)
    x0, y0 = (W - tw) / 2 - 36, (320 - th) / 2 - 22
    d.rounded_rectangle([x0, y0, W - x0, y0 + th + 44], radius=28, fill=(15, 18, 14, 215))
    d.rectangle([x0 + 28, y0 + th + 34, W - x0 - 28, y0 + th + 40], fill=(*accent, 255))
    y = y0 + 22
    for x in lines:
        d.text((W / 2, y), x, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += int(font.size * 1.25)
    return _png(img)


def hook_png(hook: str, kit: dict) -> bytes:
    """The moment's hook as a banner across the top for the first seconds."""
    primary = images._rgb(kit.get("primary_color"), (31, 42, 26))
    img = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font, lines = images._fit(d, hook, W - 180, 260, start=78, smallest=44)
    th = len(lines) * int(font.size * 1.2)
    d.rounded_rectangle([50, 60, W - 50, 60 + th + 70], radius=32, fill=(*primary, 235))
    y = 95
    for x in lines:
        d.text((W / 2, y), x, font=font, fill=(*images._ink_on(primary), 255), anchor="ma")
        y += int(font.size * 1.2)
    return _png(img)


def end_card_png(kit: dict, business: str, logo: Path | None) -> bytes:
    primary = images._rgb(kit.get("primary_color"), (31, 42, 26))
    accent = images._rgb(kit.get("accent_color"), (200, 240, 74))
    ink = images._ink_on(primary)
    img = Image.new("RGB", (W, H), primary)
    d = ImageDraw.Draw(img)
    y = H // 2 - 120
    if logo and logo.is_file():
        try:
            lg = Image.open(logo).convert("RGBA")
            lg.thumbnail((520, 300))
            img.paste(lg, ((W - lg.width) // 2, y - lg.height - 40), lg)
        except OSError:
            pass
    font, lines = images._fit(d, business, W - 200, 300, start=96, smallest=48)
    for x in lines:
        d.text((W / 2, y), x, font=font, fill=ink, anchor="ma")
        y += int(font.size * 1.2)
    d.rectangle([W / 2 - 90, y + 30, W / 2 + 90, y + 42], fill=accent)
    if handle := (kit.get("handle") or "").strip():
        d.text((W / 2, y + 90), handle, font=images._font(54), fill=accent, anchor="ma")
    return _png(img)


async def _exec(*cmd: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode:
        raise ClipError(f"{cmd[0]} failed: {err.decode(errors='ignore')[-300:]}")
    return out


async def probe(path: Path) -> dict:
    """Duration and whether there is a video and an audio stream."""
    info = json.loads(await _exec("ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)))
    kinds = {s.get("codec_type") for s in info.get("streams", [])}
    return {"duration": float(info.get("format", {}).get("duration") or 0), "video": "video" in kinds, "audio": "audio" in kinds}


async def render(src: Path, out: Path, a: float, b: float, lines: list[tuple[float, float, str]], hook: str, kit: dict,
                 business: str, logo: Path | None, audio: bool = True) -> float:
    """Cut [a, b] from src into a 1080x1920 MP4 at out with captions, the hook banner and the end card. Returns its length."""
    dur = round(b - a, 2)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        inputs: list[str] = ["-ss", f"{a}", "-t", f"{dur}", "-i", str(src)]
        overlays: list[tuple[str, str]] = []  # (input file, enable expression + position)

        def add(png: bytes, where: str) -> None:
            p = t / f"o{len(overlays)}.png"
            p.write_bytes(png)
            overlays.append((str(p), where))
        add(hook_png(hook, kit), f"x=0:y=0:enable='lt(t,{HOOK_S})'")
        for i, (t0, t1, line) in enumerate(lines):
            end = min(t1, lines[i + 1][0]) if i + 1 < len(lines) and lines[i + 1][0] > t0 else t1
            add(caption_png(line, kit), f"x=0:y={H - 620}:enable='between(t,{t0},{end})'")
        add(end_card_png(kit, business, logo), f"x=0:y=0:enable='gte(t,{dur})'")
        for p, _ in overlays:
            inputs += ["-i", p]
        chain = [(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,"
                 f"tpad=stop_mode=clone:stop_duration={OUTRO_S}[v0]")]
        for i, (_, where) in enumerate(overlays, 1):
            chain.append(f"[v{i - 1}][{i}:v]overlay={where}[v{i}]")
        cmd = ["ffmpeg", "-nostdin", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[v{len(overlays)}]"]
        if audio:
            cmd += ["-map", "0:a:0", "-af", f"apad=whole_dur={dur + OUTRO_S}", "-c:a", "aac", "-b:a", "128k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-t", f"{dur + OUTRO_S}", str(out)]
        await _exec(*cmd)
    return round(dur + OUTRO_S, 2)


async def make(conn: AsyncConnection, org_id: str, moment_id: str) -> dict:
    """Cut (or recut) one moment's clip and record it. Returns {"status", "error"?}."""
    m = (await conn.execute(text("""select m.id, m.source_id, m.start_s, m.end_s, m.hook, s.kind, s.file_path, s.transcript
        from app.content_moments m join app.content_sources s on s.id = m.source_id where m.id = cast(:i as uuid)"""), {"i": moment_id})).mappings().one()
    status, error, path, a, b, length = "failed", None, None, None, None, None
    try:
        if m["kind"] != "video":
            raise ClipError("clips are made from video uploads only")
        if not available():
            raise ClipError("ffmpeg isn't installed on the server")
        src = sources.resolve(m["file_path"])
        if not src:
            raise ClipError("the uploaded video is missing")
        info = await probe(src)
        if not info["video"]:
            raise ClipError("the file has no video track")
        segments = (m["transcript"] or {}).get("segments", [])
        a, b = window(segments, float(m["start_s"]), float(m["end_s"]), info["duration"])
        kit = await brand.get_kit(conn, org_id)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        out = sources.folder(org_id, str(m["source_id"])) / f"clip-{moment_id}.mp4"
        length = await render(src, out, a, b, captions(segments, a, b), m["hook"], kit, business, brand.logo_path(kit), info["audio"])
        status, path = "ready", sources.relative(out)
    except ClipError as e:
        error = str(e)
        status = "skipped" if "past the end" in error or "video uploads only" in error else "failed"
    await conn.execute(text("""insert into app.content_clips (org_id, source_id, moment_id, status, path, start_s, end_s, duration_s, error)
        values (:o, :s, cast(:m as uuid), :st, :p, :a, :b, :d, :e)
        on conflict (moment_id) do update set status = excluded.status, path = excluded.path, start_s = excluded.start_s,
          end_s = excluded.end_s, duration_s = excluded.duration_s, error = excluded.error, updated_at = now()"""),
        {"o": org_id, "s": m["source_id"], "m": moment_id, "st": status, "p": path, "a": a, "b": b, "d": length, "e": error})
    return {"status": status, **({"error": error} if error else {})}
