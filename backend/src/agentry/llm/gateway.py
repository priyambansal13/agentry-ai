"""LLM gateway: every model call in Agentry goes through here.

- Callers ask for a *tier* (fast / writer / conversation / vision / embed), never a model.
- A tier maps to an ordered list of LiteLLM model strings (AGENTRY_MODEL_<TIER>, comma-separated), so OpenAI and
  Gemini (or any provider) can be mixed: the first is primary, the rest are fallbacks used when a call fails
  (rate limit, outage, bad key, unknown model). A client can override any tier (app.org_settings.llm_models).
- Models whose provider key is missing are skipped, so one provider's key is enough to run.
- No model available -> mock mode: no network, no cost, deterministic output (development and CI).
- Every attempt is recorded in app.llm_calls (org, tier, model, prompt version, tokens, cost, latency, error),
  which the operator console uses for cost and margin per client.
"""
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import litellm
from sqlalchemy import text

from agentry.config import settings
from agentry.db import system_session
from agentry.runs import current_run

Tier = Literal["fast", "writer", "conversation", "voice", "vision", "embed"]
TIERS: tuple[Tier, ...] = ("fast", "writer", "conversation", "voice", "vision", "embed")
litellm.drop_params = True  # ignore params a provider doesn't support (e.g. response_format on some models)
litellm.suppress_debug_info = True

# Provider prefix -> environment variable holding its key. Providers not listed need no key (e.g. ollama).
PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


# Circuit breaker: a model that just failed with a quota, auth or "no such model" error is skipped for a while, so calls
# go straight to the next model instead of paying the failed attempt's latency every time (matters most on voice calls).
COOLDOWN_SECONDS = 600
_cooling: dict[str, float] = {}  # model -> monotonic time it may be tried again (per process)
_COOLDOWN_ERRORS = ("RateLimitError", "AuthenticationError", "NotFoundError", "PermissionDeniedError")


def _cool(model: str, error: Exception) -> None:
    if type(error).__name__ in _COOLDOWN_ERRORS:
        _cooling[model] = time.monotonic() + COOLDOWN_SECONDS


def _usable(chain: list[str]) -> list[str]:
    """Drop models that are cooling down, unless that would leave nothing to try."""
    now = time.monotonic()
    ready = [m for m in chain if _cooling.get(m, 0) <= now]
    return ready or chain


class AllModelsFailed(RuntimeError):
    def __init__(self, tier: str, errors: list[str]):
        super().__init__(f"all models failed for tier {tier}: " + " | ".join(errors))
        self.errors = errors


@dataclass
class LLMResult:
    text: str
    data: Any | None
    model: str
    mock: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    tool_calls: list[dict] = field(default_factory=list)  # [{"id", "name", "arguments": dict}]
    attempts: list[str] = field(default_factory=list)  # models tried before this one succeeded


def provider_of(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else "openai"


def has_key(model: str) -> bool:
    env = PROVIDER_KEYS.get(provider_of(model))
    return env is None or bool(os.environ.get(env))


def _split(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, list) else value.split(",")
    return [m.strip() for m in items if m and m.strip()]


async def models_for(tier: Tier, org_id: str | None = None) -> list[str]:
    """Ordered candidate models for a tier: the client's override if set, else the environment default.
    Models without a configured provider key are dropped."""
    chain: list[str] = []
    if org_id:
        async with system_session() as conn:
            override = (await conn.execute(
                text("select llm_models -> :tier from app.org_settings where org_id = :org"), {"tier": tier, "org": org_id},
            )).scalar_one_or_none()
        chain = _split(override)
    if not chain:
        chain = _split(getattr(settings, f"model_{tier}"))
    if not chain and tier == "voice":  # no voice-specific models: calls use the conversation tier
        return await models_for("conversation", org_id)
    chain = _usable([m for m in chain if has_key(m)])
    # Embeddings never fall back to another model: vectors from different models are not comparable, so a
    # silent fallback would corrupt knowledge search. Changing the embed model requires `agentry reindex`.
    return chain[:1] if tier == "embed" else chain


async def complete(
    tier: Tier,
    messages: list[dict],
    *,
    org_id: str | None = None,
    prompt_key: str | None = None,
    prompt_version: str | None = None,
    json_output: bool = False,
    tools: list[dict] | None = None,
    mock_response: str | None = None,
    temperature: float = 0.2,
    record: bool = True,
) -> LLMResult:
    chain = await models_for(tier, org_id)
    if not chain:
        return await _mock(tier, json_output, mock_response, org_id, prompt_key, prompt_version, record)

    kwargs: dict[str, Any] = {"temperature": temperature, "timeout": 60}
    if json_output and not tools:
        kwargs["response_format"] = {"type": "json_object"}
    if tools:
        kwargs["tools"] = tools
    errors: list[str] = []
    for model in chain:
        started = time.perf_counter()
        # Gemini 3+ is retiring sampling parameters (guidance belongs in the system prompt): don't send them.
        call_kwargs = {k: v for k, v in kwargs.items() if not (k == "temperature" and "gemini-3" in model)}
        try:
            resp = await litellm.acompletion(model=model, messages=messages, **call_kwargs)
        except Exception as e:  # noqa: BLE001 - any provider failure moves on to the next model
            _cool(model, e)
            err = f"{type(e).__name__}: {e}"[:500]
            errors.append(f"{model}: {err}")
            if record:
                await _record(org_id, tier, model, prompt_key, prompt_version, 0, 0, 0.0,
                              int((time.perf_counter() - started) * 1000), "error", err)
            continue
        latency = int((time.perf_counter() - started) * 1000)
        msg = resp.choices[0].message
        content = msg.content or ""
        usage = getattr(resp, "usage", None)
        in_tok, out_tok = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        try:
            cost = float(litellm.completion_cost(completion_response=resp))
        except Exception:  # noqa: BLE001 - price lookup must never fail a completed call
            cost = 0.0  # model not in LiteLLM's price map: tracked as 0 ("unpriced")
        calls = [{"id": c.id, "name": c.function.name, "arguments": _loads(c.function.arguments) or {}}
                 for c in (getattr(msg, "tool_calls", None) or [])]
        data, status = None, "ok"
        if json_output and not calls:
            data = _loads(content)
            status = "ok" if data is not None else "bad_json"
        if record:
            await _record(org_id, tier, model, prompt_key, prompt_version, in_tok, out_tok, cost, latency, status, None)
        return LLMResult(content, data, model, False, in_tok, out_tok, cost, latency, calls,
                         [e.split(":", 1)[0] for e in errors])
    raise AllModelsFailed(tier, errors)


async def _mock(tier, json_output, mock_response, org_id, prompt_key, prompt_version, record) -> LLMResult:
    content = mock_response if mock_response is not None else ("{}" if json_output else "")
    if record:
        await _record(org_id, tier, f"mock/{tier}", prompt_key, prompt_version, 0, 0, 0.0, 0, "ok", None)
    return LLMResult(content, _loads(content) if json_output else None, f"mock/{tier}", True, 0, 0, 0.0, 0)


async def embed(texts: list[str], *, org_id: str | None = None, record: bool = True) -> tuple[list[list[float]], bool]:
    """Embeddings for the knowledge base. Returns (vectors, mock). Mock mode uses hashed bag-of-words vectors:
    not semantic, but keyword retrieval works offline, so the knowledge base is testable without a model."""
    dims = settings.embed_dimensions
    errors: list[str] = []
    for model in await models_for("embed", org_id):
        started = time.perf_counter()
        try:
            resp = await litellm.aembedding(model=model, input=texts, dimensions=dims, timeout=60)
        except Exception as e:  # noqa: BLE001 - fall back to the next embedding model
            _cool(model, e)
            errors.append(f"{model}: {type(e).__name__}: {e}"[:300])
            if record:  # visible to ops alerts (agentry alerts) like any failed model call
                await _record(org_id, "embed", model, None, None, 0, 0, 0.0, int((time.perf_counter() - started) * 1000),
                              "error", f"{type(e).__name__}: {e}"[:500])
            continue
        vectors = [d["embedding"] for d in resp.data]
        if record:
            usage = getattr(resp, "usage", None)
            await _record(org_id, "embed", model, None, None, getattr(usage, "prompt_tokens", 0) or 0, 0, 0.0,
                          int((time.perf_counter() - started) * 1000), "ok", None)
        return [_normalise(v[:dims]) for v in vectors], False
    if errors:
        raise AllModelsFailed("embed", errors)
    return [_hash_embed(t, dims) for t in texts], True


_WORD = re.compile(r"[a-z0-9ऀ-෿]+")


def _hash_embed(t: str, dims: int) -> list[float]:
    v = [0.0] * dims
    for w in _WORD.findall(t.lower()):
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        v[h % dims] += 1.0 if (h >> 32) & 1 else -1.0
    return _normalise(v)


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _loads(s: str | None) -> Any:
    if not s:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        return None


async def _record(org_id, tier, model, prompt_key, prompt_version, in_tok, out_tok, cost, latency, status, error) -> None:
    async with system_session() as conn:
        await conn.execute(
            text("""insert into app.llm_calls (org_id, tier, model, prompt_key, prompt_version, input_tokens,
                      output_tokens, cost_usd, latency_ms, status, error, run_id)
                    values (:org, :tier, :model, :pk, :pv, :it, :ot, :cost, :lat, :status, :err, cast(:run as uuid))"""),
            {"org": org_id, "tier": tier, "model": model, "pk": prompt_key, "pv": prompt_version, "it": in_tok,
             "ot": out_tok, "cost": cost, "lat": latency, "status": status, "err": error, "run": current_run.get()},
        )
