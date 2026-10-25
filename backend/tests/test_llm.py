from sqlalchemy import text

from agentry.db import system_session
from agentry.llm.gateway import complete
from agentry.llm.prompts import load


def test_prompt_registry_renders_latest_version():
    p = load("invoice_reply_classifier")
    assert p.version == "v1" and p.tier == "fast" and p.json_output
    msgs = p.render(invoice="SDA-2042", channel="email", text="Will pay on 30th")
    assert "SDA-2042" in msgs[1]["content"] and "{{" not in msgs[1]["content"]


async def test_mock_call_is_recorded_with_prompt_version(orgs):
    p = load("invoice_reply_classifier")
    res = await complete("fast", p.render(text="hi"), org_id=orgs["sharma-digital"], prompt_key=p.key,
                         prompt_version=p.version, json_output=True, mock_response='{"label": "other"}')
    assert res.mock and res.data == {"label": "other"} and res.cost_usd == 0
    async with system_session() as conn:
        row = (await conn.execute(text("select * from app.llm_calls order by id desc limit 1"))).mappings().one()
    assert row["prompt_key"] == "invoice_reply_classifier" and row["model"] == "mock/fast"


class _Resp:
    """Minimal stand-in for a LiteLLM response."""
    def __init__(self, content: str):
        msg = type("M", (), {"content": content, "tool_calls": None})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = type("U", (), {"prompt_tokens": 5, "completion_tokens": 2})()


async def test_falls_back_from_gemini_to_openai(monkeypatch):
    from agentry.config import settings
    from agentry.llm import gateway
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(settings, "model_fast", "gemini/primary-model, openai/backup-model")
    calls = []

    async def fake(model, messages, **kw):
        calls.append(model)
        if model.startswith("gemini/"):
            raise RuntimeError("429 rate limited")
        return _Resp('{"label": "ok"}')

    monkeypatch.setattr(gateway.litellm, "acompletion", fake)
    res = await gateway.complete("fast", [{"role": "user", "content": "x"}], json_output=True, record=False)
    assert calls == ["gemini/primary-model", "openai/backup-model"]
    assert res.model == "openai/backup-model" and res.attempts == ["gemini/primary-model"] and res.data == {"label": "ok"}


async def test_models_without_a_key_are_skipped(monkeypatch):
    from agentry.config import settings
    from agentry.llm import gateway
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(settings, "model_writer", "openai/a,gemini/b")
    assert await gateway.models_for("writer") == ["gemini/b"]


async def test_all_models_failing_raises(monkeypatch):
    import pytest

    from agentry.config import settings
    from agentry.llm import gateway
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(settings, "model_fast", "openai/a")

    async def fail(model, messages, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(gateway.litellm, "acompletion", fail)
    with pytest.raises(gateway.AllModelsFailed):
        await gateway.complete("fast", [{"role": "user", "content": "x"}], record=False)


async def test_client_override_beats_environment_default(monkeypatch, orgs):
    from agentry.config import settings
    from agentry.db import system_session
    from agentry.llm import gateway
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(settings, "model_writer", "gemini/default")
    org = orgs["brightpath"]
    async with system_session() as conn:
        await conn.execute(text("""update app.org_settings set llm_models = '{"writer": ["openai/premium"]}' where org_id = :o"""), {"o": org})
    try:
        assert await gateway.models_for("writer", org) == ["openai/premium"]
        assert await gateway.models_for("writer", orgs["smilecraft"]) == ["gemini/default"]
    finally:
        async with system_session() as conn:
            await conn.execute(text("update app.org_settings set llm_models = '{}' where org_id = :o"), {"o": org})


async def test_mock_embeddings_retrieve_by_keyword(monkeypatch):
    from agentry.config import settings
    from agentry.llm.gateway import embed
    monkeypatch.setattr(settings, "model_embed", None)
    (q, a, b), mock = await embed(["parking at the clinic", "Is parking available? Free basement parking.",
                                   "We accept Star Health insurance"], record=False)
    cos = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert mock and cos(q, a) > cos(q, b)
