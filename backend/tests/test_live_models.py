"""Optional live smoke test against the configured providers (AGENTRY_LIVE_TESTS=1). Catches provider/library
breakage that scripted tests can't, e.g. LiteLLM needing the `mcp` package for tool calls."""
import os

import pytest

from agentry.agents.tools import TOOL_DEFS

pytestmark = pytest.mark.skipif(os.environ.get("AGENTRY_LIVE_TESTS") != "1", reason="set AGENTRY_LIVE_TESTS=1 to run")


@pytest.mark.parametrize("model_env", ["first", "second"])
async def test_tool_calling_works_on_each_configured_provider(model_env, monkeypatch):
    from agentry.config import Settings
    from agentry.llm import gateway

    chain = gateway._split(Settings().model_conversation)
    idx = 0 if model_env == "first" else 1
    if len(chain) <= idx:
        pytest.skip("no model configured at that position")
    monkeypatch.setattr(gateway.settings, "model_conversation", chain[idx])
    try:
        r = await gateway.complete("conversation", [
        {"role": "system", "content": "Always use the search_knowledge tool before answering."},
        {"role": "user", "content": "What are your opening hours?"}], tools=TOOL_DEFS, record=False)
    except gateway.AllModelsFailed as e:
        if "RateLimitError" in str(e) or "quota" in str(e).lower():
            pytest.skip(f"{chain[idx]}: provider quota exhausted (not a code failure)")
        raise
    assert r.tool_calls and r.tool_calls[0]["name"] == "search_knowledge", r.text
