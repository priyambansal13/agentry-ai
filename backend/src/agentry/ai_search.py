"""Ask AI assistants (ChatGPT, Gemini, Perplexity) what a customer would ask, with web search on, and read who they name.

Used by the AI visibility agent (monthly, per client) and the public website audit (a few questions, once).

    engines   AGENTRY_AI_SEARCH_ENGINES = "chatgpt=openai/gpt-5.4-mini,gemini=gemini/gemini-3.5-flash,perplexity=perplexity/sonar";
              an engine whose provider key is missing is skipped; none left (or "" in tests) -> mock answers, no cost
    ask       one question to one engine: OpenAI through its Responses API with the web_search tool, the others through
              web_search_options (Gemini: Google Search grounding; Perplexity searches anyway); the answer text and the
              cited URLs; the cost is recorded in llm_calls (tier "search") like every other model call
    extract   the businesses named in an answer, in order (a cheap model; a bold-name reader in mock mode)
    match     is a named business the client (or a competitor)? by name, other names or website domain
    score     how often the client is named, average position, share of voice against competitors, the sites cited most
              and the businesses named instead
API answers are close to, not the same as, what a person sees in the apps (those depend on the person and place), so a
score is an estimate measured the same way every time.
"""
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

import litellm

from agentry.config import settings
from agentry.llm.gateway import AllModelsFailed, _cool, _cooling, _record, complete, has_key

LABEL = {"chatgpt": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity"}
URL = re.compile(r"https?://[^\s)\]>\"']+")


@dataclass
class Answer:
    engine: str
    question: str
    text: str
    citations: list[str]
    cost_usd: float = 0.0
    mock: bool = False
    error: str | None = None
    named: list[dict] = field(default_factory=list)  # [{"name", "position", "said"}]


def engines() -> dict[str, str]:
    """Engines that can run now: name -> model. Empty = mock mode."""
    out = {}
    for part in (settings.ai_search_engines or "").split(","):
        if "=" in part:
            name, model = (x.strip() for x in part.split("=", 1))
            if name and model and has_key(model):
                out[name] = model
    return out


def mock_engines() -> dict[str, str]:
    return {"chatgpt": "mock/chatgpt", "gemini": "mock/gemini"}


def active() -> tuple[dict[str, str], bool]:
    """(engines, mock)"""
    e = engines()
    return (e, False) if e else (mock_engines(), True)


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.blake2b("|".join(parts).encode(), digest_size=8).digest(), "big")


def mock_answer(engine: str, question: str, names: list[str], repeat: int = 0) -> str:
    """Deterministic test answer: some of the given businesses in a stable order; the first name (the client) appears in
    about half of the answers."""
    me, others = (names[0], names[1:]) if names else ("", [])
    pool = sorted(others + ["Popular Choice Clinic", "City Care Centre"], key=lambda n: _h(engine, question, str(repeat), n))[:3]
    if me and _h(engine, question, str(repeat), "me") % 2 == 0:
        pool.insert(_h(engine, question, "pos") % (len(pool) + 1), me)
    lines = [f"{i}. **{n}**: well reviewed by locals." for i, n in enumerate(pool, 1)]
    return "Here are some options people recommend:\n" + "\n".join(lines) + "\n\nSources: https://www.justdial.com/ https://www.practo.com/"


async def ask(engine: str, model: str, question: str, *, city: str | None = None, org_id: str | None = None,
              prompt_key: str = "ai_search", mock_names: list[str] | None = None, repeat: int = 0) -> Answer:
    if model.startswith("mock/"):
        txt = mock_answer(engine, question, mock_names or [], repeat)
        return Answer(engine, question, txt, sorted(set(URL.findall(txt))), 0.0, True)
    if _cooling.get(model, 0) > time.monotonic():  # failed with quota / auth a moment ago: don't wait on it again
        return Answer(engine, question, "", [], 0.0, False, "unavailable")
    t0 = time.perf_counter()
    where = {"type": "approximate", "country": "IN", **({"city": city} if city else {})}
    try:
        if model.startswith("openai/"):
            r = await litellm.aresponses(model=model, input=question, timeout=90,
                                         tools=[{"type": "web_search", "search_context_size": "low", "user_location": where}])
            msgs = [o for o in r.output if getattr(o, "type", "") == "message"]
            parts = msgs[-1].content if msgs else []
            txt = "\n".join(getattr(p, "text", "") or "" for p in parts)
            cites = [a.url for p in parts for a in (getattr(p, "annotations", None) or []) if getattr(a, "url", None)]
            usage = getattr(r, "usage", None)
            tin, tout = getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0
        else:
            r = await litellm.acompletion(model=model, messages=[{"role": "user", "content": question}], timeout=90,
                                          web_search_options={"search_context_size": "low",
                                                              "user_location": {"type": "approximate", "approximate": {k: v for k, v in where.items() if k != "type"}}})
            txt = r.choices[0].message.content or ""
            cites = list(getattr(r, "citations", None) or [])
            hidden = getattr(r, "_hidden_params", None) or {}
            for g in (getattr(r, "vertex_ai_grounding_metadata", None) or hidden.get("vertex_ai_grounding_metadata") or []):
                for c in (g or {}).get("groundingChunks", []) if isinstance(g, dict) else []:
                    if u := (c.get("web") or {}).get("uri"):
                        cites.append(u)
            usage = getattr(r, "usage", None)
            tin, tout = getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
        try:
            cost = float(litellm.completion_cost(completion_response=r)) or settings.ai_search_cost_usd
        except Exception:  # noqa: BLE001 - a price lookup never fails a finished call
            cost = settings.ai_search_cost_usd
    except Exception as e:  # noqa: BLE001 - one engine failing never stops the others
        _cool(model, e)
        err = f"{type(e).__name__}: {e}"[:500]
        await _record(org_id, "search", model, prompt_key, "v1", 0, 0, 0.0, int((time.perf_counter() - t0) * 1000), "error", err)
        return Answer(engine, question, "", [], 0.0, False, type(e).__name__)
    await _record(org_id, "search", model, prompt_key, "v1", tin, tout, cost, int((time.perf_counter() - t0) * 1000), "ok", None)
    cites += URL.findall(txt)
    return Answer(engine, question, txt, list(dict.fromkeys(_clean(u) for u in cites)), cost)


def _clean(url: str) -> str:
    return re.sub(r"[?&]utm_source=openai$", "", url.rstrip(".,;"))


BOLD = re.compile(r"\*\*([^*\n]{2,80})\*\*")
EXTRACT = """Below is an answer an AI assistant gave to: "{question}".
List the businesses (clinics, shops, firms, service providers) it names or recommends, in the order they first appear.
Skip websites that are only sources or directories (Practo, Justdial, Google Maps, Sulekha) unless recommended as the business itself.
Return JSON: {{"named": [{{"name": "...", "said": "the short phrase about it, max 20 words"}}]}}

Answer:
{answer}"""


def bold_names(txt: str) -> list[dict]:
    seen, out = set(), []
    for m in BOLD.finditer(txt):
        n = m.group(1).strip(" :.-")
        if n.lower() not in seen and not n.lower().startswith(("note", "tip", "how ", "why ", "what ")):
            seen.add(n.lower())
            out.append({"name": n, "said": ""})
    return out


async def extract(a: Answer, *, org_id: str | None = None, prompt_key: str = "ai_search_extract") -> list[dict]:
    if not a.text:
        return []
    fallback = bold_names(a.text)
    try:
        r = await complete("fast", [{"role": "user", "content": EXTRACT.format(question=a.question, answer=a.text[:6000])}],
                           org_id=org_id, prompt_key=prompt_key, prompt_version="v1", json_output=True,
                           mock_response=json.dumps({"named": fallback}))
        named = (r.data or {}).get("named") if isinstance(r.data, dict) else None
    except AllModelsFailed:
        named = None
    named = [n for n in (named if isinstance(named, list) else fallback) if isinstance(n, dict) and str(n.get("name") or "").strip()]
    return [{"name": str(n["name"]).strip()[:120], "position": i, "said": str(n.get("said") or "")[:200]} for i, n in enumerate(named[:12], 1)]


# ---------- matching ----------

SUFFIX = re.compile(r"\b(the|pvt|private|ltd|limited|llp|inc|co|company|india)\b")


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()))).strip()


def domain_root(url: str | None) -> str:
    host = (urlparse(url if "//" in (url or "") else f"//{url}").hostname or "").removeprefix("www.")
    return host.split(".")[0] if host else ""


def is_same(named: str, target: dict) -> bool:
    """target = {"name", "aliases": [...], "website"}"""
    n = norm(named)
    if not n:
        return False
    flat = n.replace(" ", "")
    for cand in [target.get("name") or "", *(target.get("aliases") or [])]:
        c = norm(cand)
        if c and (c == n or re.search(rf"\b{re.escape(c)}\b", n) or (len(n.split()) >= 2 and re.search(rf"\b{re.escape(n)}\b", c))):
            return True
    root = domain_root(target.get("website"))
    return bool(root) and len(root) >= 5 and (root == flat or root in flat)


def mark(named: list[dict], me: dict, competitors: list[dict]) -> list[dict]:
    """Label each named business: "me", a competitor's name, or None (someone else)."""
    out = []
    for n in named:
        who = "me" if is_same(n["name"], me) else next((c["name"] for c in competitors if is_same(n["name"], c)), None)
        out.append({**n, "who": who})
    return out


def score(answers: list[dict], competitors: list[dict]) -> dict:
    """answers: [{"engine", "question", "named": marked list, "citations": [...], "error"}]"""
    ok = [a for a in answers if not a.get("error")]
    hit = [a for a in ok if any(n["who"] == "me" for n in a["named"])]
    pos = [next(n["position"] for n in a["named"] if n["who"] == "me") for a in hit]
    per_engine = {}
    for e in sorted({a["engine"] for a in ok}):
        mine = [a for a in ok if a["engine"] == e]
        per_engine[e] = {"asked": len(mine), "named": sum(1 for a in mine if a in hit),
                         "rate": round(100 * sum(1 for a in mine if a in hit) / len(mine)) if mine else 0}
    voice = Counter()
    for a in ok:
        for who in {n["who"] for n in a["named"] if n["who"]}:
            voice[who] += 1
    total = sum(voice.values()) or 1
    others = Counter(n["name"] for a in ok for n in a["named"] if not n["who"])
    sources = Counter(urlparse(u).hostname.removeprefix("www.") for a in ok for u in set(a.get("citations") or []) if urlparse(u).hostname)
    return {
        "asked": len(ok), "failed": len(answers) - len(ok), "named": len(hit),
        "rate": round(100 * len(hit) / len(ok)) if ok else 0,
        "avg_position": round(sum(pos) / len(pos), 1) if pos else None,
        "engines": per_engine,
        "share": [{"name": "You" if k == "me" else k, "me": k == "me", "mentions": v, "pct": round(100 * v / total)}
                  for k, v in sorted(voice.items(), key=lambda kv: (-kv[1], kv[0]))] +
                 [{"name": c["name"], "me": False, "mentions": 0, "pct": 0} for c in competitors if c["name"] not in voice],
        "named_instead": [{"name": k, "mentions": v} for k, v in others.most_common(8)],
        "sources": [{"site": k, "times": v} for k, v in sources.most_common(10)],
    }


def questions_for(service: str, city: str, area: str | None = None, n: int = 15) -> list[str]:
    """Questions a customer would type, from the service and place (no model needed; editable by the owner)."""
    s, where = service.strip(), (f"{area}, {city}" if area else city).strip()
    q = [f"What is the best {s} in {where}?", f"Can you recommend a good {s} in {where}?",
         f"Which {s} in {city} has the best reviews?", f"Affordable {s} in {where}: who should I go to?",
         f"I need a {s} near {where}. Which ones are trusted?", f"Top rated {s} in {city}",
         f"{s.capitalize()} in {where} open on Sunday", f"Who is the most experienced {s} in {city}?",
         f"Best {s} in {city} for families", f"Which {s} in {where} do locals recommend?",
         f"{s.capitalize()} in {city} with transparent prices", f"Is there a reliable {s} in {where} that answers on WhatsApp?",
         f"Where should I go for {s} in {city}?", f"List the best {s} options in {where}", f"Highly recommended {s} {city}"]
    return q[:n]
