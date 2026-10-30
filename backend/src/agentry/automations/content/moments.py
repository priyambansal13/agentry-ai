"""The best moments of a long recording (Phase 6.2): mined window by window, kept only if the quote is exact, ranked,
de-duplicated, top N.

Windows are ~6 minutes with 1 minute of overlap, so a moment on a boundary isn't lost. The `writer` model proposes
2-4 moments per window; a pattern-based fallback does the same offline (tests, or when the models are down).
"""
import json
import re

from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

WINDOW, OVERLAP = 360, 60
STRONG = re.compile(r"\b(never|always|every|everything|nobody|first|best|worst|biggest|hardest|honestly|not .{1,40}\. it'?s|"
                    r"changed|dropped|doubled|beats|instead)\b", re.IGNORECASE)
TOPICS = [("missed calls", r"\bcall"), ("no-shows", r"no-show|remind|cancel"), ("pricing", r"price|bill|cost|treatment plan"),
          ("children", r"child|kid|parent"), ("reviews", r"review|waiting|late"), ("team", r"team|hire|front desk|staff|burn"),
          ("technology", r"scanner|screen|software"), ("AI", r"\bai\b|ai assistant|\bbot\b"), ("marketing", r"marketing|camp|ads"),
          ("opening hours", r"sunday|hours"), ("numbers", r"revenue|profit|money|measure|track"), ("advice", r"advice|first clinic")]


def norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", re.sub(r"[^\w'%,.\- ]", " ", s)).strip(" .,")


def quote_in(quote: str, transcript_text: str) -> bool:
    """Word for word (ignoring case, punctuation and spacing)."""
    q = norm(quote)
    return len(q) >= 12 and q in norm(transcript_text)


def windows(segments: list[dict]) -> list[list[dict]]:
    if not segments:
        return []
    end = segments[-1]["end"]
    out, t = [], 0.0
    while t < end:
        w = [s for s in segments if s["end"] > t and s["start"] < t + WINDOW]
        if w:
            out.append(w)
        t += WINDOW - OVERLAP
    return out


def topic_of(text: str) -> str:
    t = text.lower()
    return next((name for name, pat in TOPICS if re.search(pat, t)), "other")


def _first_sentence(s: str, limit: int = 90) -> str:
    first = re.split(r"(?<=[.!?])\s+", s.strip())[0]
    return first if len(first) <= limit else first[: limit - 1].rsplit(" ", 1)[0] + "…"


def heuristic_moments(segs: list[dict]) -> list[dict]:
    """Offline fallback: answers (not questions) with a number or a strong claim, scored by how quotable they are."""
    picked = []
    for s in segs:
        t = s["text"]
        if t.rstrip().endswith("?") or len(t) < 50:
            continue
        insight = 3 * bool(re.search(r"\d", t)) + 2 * bool(STRONG.search(t)) + 2 * (60 <= len(t) <= 230) + 2 * bool(s.get("speaker") and s["speaker"] != "Host")
        if insight < 5:
            continue
        picked.append({"start": s["start"], "end": s["end"], "speaker": s.get("speaker"), "quote": t, "hook": _first_sentence(t),
                       "insight": _first_sentence(t, 140), "topic": topic_of(t),
                       "scores": {"insight": min(10, insight), "hook": 6 + bool(STRONG.search(t)) * 2, "standalone": 7}})
    return sorted(picked, key=lambda m: -m["scores"]["insight"])[:4]


async def mine(org_id: str, title: str, transcript: dict) -> list[dict]:
    """Candidates from every window, with exact quotes only."""
    prompt = load("content_moments")
    text = " ".join(s["text"] for s in transcript["segments"])
    found = []
    for w in windows(transcript["segments"]):
        lines = "\n".join(f"[{s['start']:.0f}] {s.get('speaker') or 'Speaker'}: {s['text']}" for s in w)
        fallback = {"moments": heuristic_moments(w)}
        try:
            res = await complete(prompt.tier, prompt.render(title=title, window=f"{w[0]['start'] / 60:.0f}–{w[-1]['end'] / 60:.0f} min",
                                                            lines=lines), org_id=org_id, prompt_key=prompt.key,
                                 prompt_version=prompt.version, json_output=True, mock_response=json.dumps(fallback))
            items = (res.data or {}).get("moments") if isinstance(res.data, dict) else None
        except AllModelsFailed:
            items = None
        for m in items if isinstance(items, list) else fallback["moments"]:
            if not isinstance(m, dict) or not m.get("quote") or not quote_in(str(m["quote"]), text):
                continue  # a model that paraphrased the "quote" doesn't get a moment
            sc = m.get("scores") or {}
            found.append({"start": float(m.get("start") or w[0]["start"]), "end": float(m.get("end") or w[-1]["end"]),
                          "speaker": m.get("speaker"), "quote": str(m["quote"]).strip(), "hook": str(m.get("hook") or _first_sentence(m["quote"]))[:140],
                          "insight": str(m.get("insight") or "")[:300] or _first_sentence(m["quote"], 140),
                          "topic": str(m.get("topic") or topic_of(m["quote"]))[:40],
                          "score": float(sc.get("insight", 5)) + float(sc.get("hook", 5)) + float(sc.get("standalone", 5))})
    return found


def _words(s: str) -> set[str]:
    return {w for w in norm(s).split() if len(w) > 3}


def _same(a: dict, b: dict) -> bool:
    """Mostly the same words, or one quote inside the other (overlapping windows find the same line twice)."""
    wa, wb = _words(a["quote"]), _words(b["quote"])
    na, nb = norm(a["quote"]), norm(b["quote"])
    return len(wa & wb) / max(1, len(wa | wb)) > 0.5 or na in nb or nb in na


def rank(candidates: list[dict], n: int) -> list[dict]:
    """Best first; near-duplicates dropped; at most 2 per topic while other topics still have candidates."""
    kept: list[dict] = []
    per_topic: dict[str, int] = {}
    pool = sorted(candidates, key=lambda m: -m["score"])
    for relaxed in (False, True):
        for m in pool:
            if len(kept) >= n or m in kept:
                continue
            dup = any(_same(m, k) for k in kept)
            if dup or (not relaxed and per_topic.get(m["topic"], 0) >= 2):
                continue
            kept.append(m)
            per_topic[m["topic"]] = per_topic.get(m["topic"], 0) + 1
    return kept
