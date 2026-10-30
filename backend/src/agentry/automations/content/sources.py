"""Uploaded videos and podcasts (Phase 6.1): where the files live, and turning them into a timestamped transcript.

    video / audio  -> OpenAI transcription (whisper-1 gives segments with timestamps). ffmpeg first pulls a small mono
                      audio track out of the file and splits anything long into 10-minute parts (the API takes 25 MB).
    transcript     -> SRT or VTT keep their timestamps; plain text gets estimated times (150 words a minute).
    sample         -> mock-data/content/sample-podcast.json (test mode, and the "try a sample" button).

settings.content_transcriber = "mock" makes every audio/video upload return the sample podcast (tests, no key needed).
"""
import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path

from agentry.config import ROOT, settings

SAMPLE = ROOT / "mock-data" / "content" / "sample-podcast.json"
API_LIMIT = 24 * 1024 * 1024
USD_PER_MINUTE = 0.006  # whisper-1 list price at the time of writing; shown in HQ as an estimate
VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
AUDIO = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".oga", ".flac", ".mpga", ".mpeg"}
TRANSCRIPT = {".srt", ".vtt", ".txt"}


class TranscribeError(RuntimeError):
    pass


def kind_of(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    return "video" if ext in VIDEO else "audio" if ext in AUDIO else "transcript" if ext in TRANSCRIPT else None


def folder(org_id: str, source_id: str) -> Path:
    p = Path(settings.content_dir) / org_id / source_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve(rel: str | None) -> Path | None:
    """A stored relative path, only if it is inside the content folder and exists."""
    if not rel:
        return None
    root = Path(settings.content_dir).resolve()
    path = (root / rel).resolve()
    return path if root in path.parents and path.is_file() else None


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(Path(settings.content_dir).resolve()))


def remove_files(org_id: str, source_id: str) -> None:
    shutil.rmtree(Path(settings.content_dir) / org_id / source_id, ignore_errors=True)


def sample_transcript() -> dict:
    d = json.loads(SAMPLE.read_text())
    return {"language": d["language"], "duration_seconds": d["duration_seconds"], "segments": d["segments"], "title": d["title"]}


# ---------- transcript files ----------

_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})|(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _secs(m: re.Match) -> float:
    if m.group(1) is not None:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4].ljust(3, "0")) / 1000
    return int(m[5]) * 60 + int(m[6]) + int(m[7].ljust(3, "0")) / 1000


def parse_transcript(raw: str, filename: str) -> dict:
    """SRT/VTT cues keep their times (and "Name: text" speakers); plain text gets estimated times."""
    segments: list[dict] = []
    if Path(filename).suffix.lower() in (".srt", ".vtt") or "-->" in raw[:2000]:
        for block in re.split(r"\n\s*\n", raw.replace("\r", "")):
            lines = [x.strip() for x in block.strip().splitlines() if x.strip()]
            arrow = next((i for i, x in enumerate(lines) if "-->" in x), None)
            if arrow is None:
                continue
            times = list(_TS.finditer(lines[arrow]))
            body = re.sub(r"<[^>]+>", "", " ".join(lines[arrow + 1:])).strip()
            if len(times) < 2 or not body:
                continue
            speaker, text = None, body
            if m := re.match(r"^([A-Z][\w. ]{1,30}):\s+(.+)$", body):
                speaker, text = m[1], m[2]
            segments.append({"start": round(_secs(times[0]), 1), "end": round(_secs(times[1]), 1), "speaker": speaker, "text": text})
    else:
        t = 0.0
        for para in [p.strip() for p in re.split(r"\n+", raw) if p.strip()]:
            speaker, text = None, para
            if m := re.match(r"^([A-Z][\w. ]{1,30}):\s+(.+)$", para):
                speaker, text = m[1], m[2]
            secs = max(2.0, len(text.split()) / 150 * 60)
            segments.append({"start": round(t, 1), "end": round(t + secs, 1), "speaker": speaker, "text": text})
            t += secs
    if not segments:
        raise TranscribeError("no text found in the transcript file")
    return {"language": None, "duration_seconds": int(segments[-1]["end"]), "segments": segments}


# ---------- audio / video ----------

async def _run(*cmd: str) -> None:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode:
        raise TranscribeError(f"{cmd[0]} failed: {err.decode(errors='ignore')[-300:]}")


async def audio_parts(path: Path, workdir: Path) -> list[tuple[Path, float]]:
    """Small mono MP3 parts of at most 10 minutes, with each part's start offset. Without ffmpeg: the file itself, if small."""
    if not shutil.which("ffmpeg"):
        if path.stat().st_size > API_LIMIT:
            raise TranscribeError("files over 25 MB need ffmpeg on the server to be split (brew install ffmpeg)")
        return [(path, 0.0)]
    pattern = workdir / "part%03d.mp3"
    await _run("ffmpeg", "-nostdin", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
               "-f", "segment", "-segment_time", "600", "-reset_timestamps", "1", str(pattern))
    parts = sorted(workdir.glob("part*.mp3"))
    if not parts:
        raise TranscribeError("no audio found in the file")
    return [(p, i * 600.0) for i, p in enumerate(parts)]


async def transcribe_file(path: Path) -> tuple[dict, float]:
    """(transcript, estimated cost in USD)."""
    if settings.content_transcriber == "mock":
        return sample_transcript(), 0.0
    import litellm
    segments: list[dict] = []
    language = None
    with tempfile.TemporaryDirectory() as tmp:
        for part, offset in await audio_parts(path, Path(tmp)):
            with part.open("rb") as f:
                try:
                    r = await litellm.atranscription(model=settings.content_transcribe_model, file=f, response_format="verbose_json")
                except Exception as e:
                    raise TranscribeError(f"transcription failed: {str(e)[:200]}") from e
            data = r.model_dump() if hasattr(r, "model_dump") else dict(r)
            language = language or data.get("language")
            for s in data.get("segments") or [{"start": 0, "end": data.get("duration") or 0, "text": data.get("text") or ""}]:
                if (s.get("text") or "").strip():
                    segments.append({"start": round(offset + float(s["start"]), 1), "end": round(offset + float(s["end"]), 1),
                                     "speaker": None, "text": s["text"].strip()})
    if not segments:
        raise TranscribeError("no speech found in the file")
    duration = int(segments[-1]["end"])
    return {"language": language, "duration_seconds": duration, "segments": segments}, round(duration / 60 * USD_PER_MINUTE, 4)


def full_text(transcript: dict) -> str:
    return " ".join(s["text"] for s in transcript["segments"])
