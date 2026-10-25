"""A model that just hit its quota (or a bad key / unknown model) is skipped for a while: calls go straight to the
fallback instead of paying the failed attempt every time."""
from types import SimpleNamespace

from agentry.config import settings
from agentry.llm import gateway


class RateLimitError(Exception):  # same name as LiteLLM's: the breaker keys on the error type's name
    pass


def ok_response(text: str):
    msg = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


async def test_failed_model_is_skipped_until_cooldown_ends(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(settings, "model_fast", "gemini/quota-gone,openai/backup")
    monkeypatch.setattr(gateway, "_cooling", {})
    tried = []

    async def fake_completion(model, messages, **kw):
        tried.append(model)
        if model.startswith("gemini"):
            raise RateLimitError("quota exceeded")
        return ok_response("hello")
    monkeypatch.setattr(gateway.litellm, "acompletion", fake_completion)

    r1 = await gateway.complete("fast", [{"role": "user", "content": "hi"}], record=False)
    r2 = await gateway.complete("fast", [{"role": "user", "content": "hi"}], record=False)
    assert r1.text == r2.text == "hello"
    assert tried == ["gemini/quota-gone", "openai/backup", "openai/backup"]  # second call skips the failed model
    gateway._cooling["gemini/quota-gone"] = 0  # cooldown over: it is tried again
    await gateway.complete("fast", [{"role": "user", "content": "hi"}], record=False)
    assert tried[-2:] == ["gemini/quota-gone", "openai/backup"]
