# ADR 0003 — OpenAI and Gemini together: tier chains, per-client overrides, no embedding fallback

Date: 2026-10-24 · Status: accepted (implemented in Phase 1)

## Decision

- Each model tier (`fast`, `writer`, `conversation`, `vision`, `embed`) is an **ordered chain** of LiteLLM model strings in
  `AGENTRY_MODEL_<TIER>`, e.g. `gemini/gemini-3.5-flash,openai/gpt-5.4-mini`. The gateway tries them in order; any provider
  error (rate limit, quota, outage, bad key, unknown model) moves on to the next. Every attempt is logged in `app.llm_calls`.
- Models whose provider key is missing are skipped, so either key alone is enough to run.
- A client can override any tier (`app.org_settings.llm_models`), e.g. pin a premium client's writer to a stronger model.
- **Embeddings never fall back.** Vectors from different models are not comparable; a silent fallback would corrupt knowledge
  search. The embed tier uses its first model only; changing it requires `agentry reindex`.
- Model names are taken from the accounts themselves (`agentry models`), not from memory.
- Gemini 3+ models don't receive `temperature` (Google is retiring sampling parameters for them).

## Development configuration (2026-10-24)

| Tier | Chain |
|---|---|
| fast | `gemini/gemini-3.5-flash-lite` → `openai/gpt-5.4-mini` |
| writer | `gemini/gemini-3.5-flash` → `openai/gpt-5.4-mini` |
| conversation | `gemini/gemini-3.5-flash` → `openai/gpt-5.4-mini` |
| vision | `gemini/gemini-3.5-flash` → `openai/gpt-5.4-mini` |
| embed | `gemini/gemini-embedding-001` (768 dims, no fallback) |

## Findings

- **Gemini's free tier is very small**: the API reported a limit of **20 generate requests per day** for the flash model in use.
  During testing, Gemini hit that limit and the OpenAI fallback served the remaining calls transparently. For production, either
  enable Gemini billing or make OpenAI the primary for high-volume tiers.
- LiteLLM's tool-calling path imports the optional `mcp` package; without it every tool call failed on both providers. It is
  now a declared dependency, and `tests/test_live_models.py` (`AGENTRY_LIVE_TESTS=1`) catches this class of breakage.

## Quality on the test sets (real models)

| Test set | Fields | Result |
|---|---|---|
| Inbox triage, in-sample (`sharma-inbox.jsonl`, 16) | category + urgent | 16/16 |
| Inbox triage, **held-out** (`heldout.jsonl`, 20, written separately and never tuned on) | category + urgent | **19/20 (95%)**, urgent 20/20 |
| Invoice replies (`replies.jsonl`, 20) | label | 19/20 (95%) |
| Keyword fallback alone (no model), held-out | category + urgent | 12/20 (60%) |

## Update 2026-10-25: embeddings moved to OpenAI

Gemini's free tier ran out of embedding quota most days, which made knowledge search fail. Embeddings have no fallback by design (vectors from different models can't be mixed), so knowledge uploads failed and drafts lost their knowledge.
- **Embed tier is now `openai/text-embedding-3-small`**, at 768 dimensions (same column size), and all knowledge was re-indexed with `agentry reindex`.
- **Chat tiers are unchanged:** Gemini first, OpenAI fallback.
- **Rule for future changes:** changing the embed model always means running `agentry reindex`.
