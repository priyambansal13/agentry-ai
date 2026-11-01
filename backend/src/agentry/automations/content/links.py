"""Recordings from a link: YouTube, Vimeo, Instagram, LinkedIn, Facebook, X, Google Drive, a podcast page, a direct
MP4/MP3 URL, and the other sites yt-dlp can read.

    check     before anything is created: a public http(s) address (the same SSRF guard as the website crawler), not a
              playlist or a live stream, at most MAX_SECONDS long
    fetch     the video at up to 720p (enough for 1080x1920 clips) or the audio if there's no video, at most 500 MB,
              into the recording's folder; plus the platform's own captions when the uploader wrote them, in English
              or Hindi (auto-generated captions are skipped: they repeat lines and have no punctuation)
    captions  become the transcript at no cost; without them the file is transcribed like an upload

Some platforms refuse servers (YouTube's "sign in to confirm you're not a bot", private or members-only videos):
the error says so in plain words, and the person can download the file and upload it instead. On a datacenter server
YouTube needs settings.content_download_proxy (a residential proxy) and/or content_download_cookies; deno in the image
is yt-dlp's JavaScript runtime for YouTube.
"""
import asyncio
import re
from pathlib import Path

from agentry.automations.content import sources
from agentry.config import settings
from agentry.knowledge import UnsafeUrl, _check_public

MAX_SECONDS = 3 * 3600
MAX_BYTES = 500 * 1024 * 1024
CAPTION_LANGS = ["en", "en-US", "en-GB", "en-IN", "hi", "hi-IN"]
FORMAT = "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b/ba"


class LinkError(RuntimeError):
    pass


def _plain(e: Exception) -> str:
    """yt-dlp's errors, in words a business owner can act on."""
    s = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    low = s.lower()
    if "private" in low or "members-only" in low or "unavailable" in low or "removed" in low:
        return "that video is private, removed or not available to us"
    if "sign in to confirm" in low or "not a bot" in low or "login required" in low or "cookies" in low:
        return "the site asked us to sign in (it sometimes blocks servers): download the video and upload the file instead"
    if "unsupported url" in low or "no video formats" in low or "unable to extract" in low:
        return "we couldn't find a video or audio file at that link"
    if "max-filesize" in low or "larger than max" in low:
        return "the file is over 500 MB: upload a shorter or smaller version"
    return f"couldn't download it: {s[:200]}"


class _Quiet:
    """yt-dlp prints errors to stderr even when quiet; they're raised and reported instead."""
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _options(**extra: object) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True, "socket_timeout": 30,
            "retries": 2, "max_filesize": MAX_BYTES, "logger": _Quiet(), **extra}
    if settings.content_download_proxy:
        opts["proxy"] = settings.content_download_proxy
    if settings.content_download_cookies and Path(settings.content_download_cookies).is_file():
        opts["cookiefile"] = settings.content_download_cookies
    return opts


def _info(url: str) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL(_options(extract_flat="in_playlist")) as ydl:  # a playlist is reported, not opened
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:  # every yt-dlp failure becomes a plain message
            raise LinkError(_plain(e)) from e
    if info.get("_type") == "playlist":
        raise LinkError("that's a playlist or channel: paste the link of one video")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise LinkError("live streams can't be used until they've finished")
    if (info.get("duration") or 0) > MAX_SECONDS:
        raise LinkError(f"that recording is longer than {MAX_SECONDS // 3600} hours")
    return info


async def check(url: str) -> dict:
    """Validate a link before a recording is created: its title and length, or a LinkError."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    try:
        _check_public(url)
    except UnsafeUrl as e:
        raise LinkError("that isn't a public web address") from e
    info = await asyncio.to_thread(_info, url)
    return {"url": info.get("webpage_url") or url, "title": (info.get("title") or "").strip()[:200] or None,
            "duration": info.get("duration"), "site": info.get("extractor_key") or info.get("extractor")}


def _media_is_public(info: dict) -> None:
    """The page was checked; the media file it points to must be on a public address too (a link can't send the server
    to an internal one)."""
    for f in info.get("requested_formats") or [info]:
        if f.get("url"):
            try:
                _check_public(f["url"])
            except UnsafeUrl as e:
                raise LinkError("that isn't a public web address") from e


def _download(url: str, folder: Path) -> dict:
    import yt_dlp
    opts = _options(format=FORMAT, merge_output_format="mp4", outtmpl=str(folder / "source.%(ext)s"),
                    writesubtitles=True, writeautomaticsub=False, subtitleslangs=CAPTION_LANGS, subtitlesformat="vtt")
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            _media_is_public(info)
            info = ydl.process_ie_result(info, download=True)
        except LinkError:
            raise
        except Exception as e:
            raise LinkError(_plain(e)) from e
    files = [p for p in folder.glob("source.*") if p.suffix not in (".vtt", ".part", ".ytdl")]
    if not files:
        raise LinkError("the download finished without a file")
    media = max(files, key=lambda p: p.stat().st_size)
    subs = sorted(folder.glob("source*.vtt"), key=lambda p: next((i for i, lang in enumerate(CAPTION_LANGS) if f".{lang}." in p.name), 99))
    has_video = bool(info.get("vcodec") and info["vcodec"] != "none") or media.suffix.lower() in sources.VIDEO
    return {"path": media, "bytes": media.stat().st_size, "kind": "video" if has_video else "audio",
            "title": (info.get("title") or "").strip()[:200] or None, "captions": subs[0] if subs else None}


async def fetch(url: str, folder: Path) -> dict:
    """Download into folder. Returns {path, bytes, kind, title, transcript (from captions, or None)}."""
    got = await asyncio.to_thread(_download, url, folder)
    transcript = None
    if got["captions"]:
        try:
            transcript = sources.parse_transcript(got["captions"].read_text(errors="ignore"), got["captions"].name)
        except sources.TranscribeError:
            transcript = None
        got["captions"].unlink(missing_ok=True)
    return {**{k: got[k] for k in ("path", "bytes", "kind", "title")}, "transcript": transcript}
