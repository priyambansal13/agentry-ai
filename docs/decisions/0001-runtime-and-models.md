# ADR 0001 — Runtimes, agent framework and models

Date: 2026-10-24 · Status: accepted (pending first implementation)

## Context

The platform runs many automations for many clients. They behave in three different ways:
- **Waiting** for days or weeks (invoice follow-up, sequences, scheduled publishing).
- **Conversations and agent loops** (chat, WhatsApp threads, content draft → critique → rewrite).
- **Real-time voice** (receptionist, speed-to-lead), which needs under a second per turn.

The reference automation was an n8n workflow (Google Sheet + Stripe + day 7/14/21/28 reminders).

## Options considered

### No-code builders: n8n, Activepieces, Windmill, Make, Zapier
- n8n's Sustainable Use Licence doesn't allow hosting it as a service for paying customers without the commercial Embed licence.
- None of them provide tenant isolation, outcome billing, an approval inbox or client dashboards. We would build all of that around them anyway.
- **Rejected** for the product. n8n remains the reference for what the first flow does.

### Durable workflow engines
| Engine | Verdict |
|---|---|
| Temporal | Strongest guarantees, but needs its own server cluster and database. Kept as an escape hatch (the Python SDK has a similar programming model) |
| Inngest | Excellent developer experience (`sleepUntil`, `waitForEvent`). TypeScript-first; server under SSPL |
| Trigger.dev | Apache 2.0, TypeScript-first |
| Postgres + pg-boss / cron | Simplest, but you hand-build retries, idempotency and waiting for events |
| **DBOS Transact (Python)** | **Chosen**: durable `sleep`, `recv` with timeout, `send`, queues, cron, steps that run once; state lives in the Postgres we already have; MIT |

### Agent frameworks
- **LangGraph** has a checkpointer, interrupts for approvals, and graphs with loops and branches. But it has no durable timers or scheduling, so it can't be the workflow engine by itself.
- **Chosen**: use LangGraph *inside* DBOS steps or the chat and voice runtimes, only where an agent loops through tools or multiple steps. Single-shot tasks (classify, extract, draft) call the LLM gateway directly.

### Voice
- Hosted voice platforms (Vapi, Retell, Bland): fastest to start, but there is a per-minute platform fee on top of model costs, less control, and lock-in.
- Open source: **LiveKit Agents** (Python, Apache 2.0) or **Pipecat**.
- **Chosen**: LiveKit Agents, which has a SIP integration, turn detection, and pluggable speech-to-text, LLM and text-to-speech. Start on LiveKit Cloud and self-host later. Hosted platforms can be used only for quick prototypes.

### Models
- No dependency on a single provider or a consumer subscription. All calls go through **LiteLLM**, using **model tiers**:
  - `fast`: classify and extract
  - `writer`: client-facing text
  - `conversation`: chat and voice turns
  - `vision`: receipts and screenshots
  - `embed`: knowledge base
- Each tier maps to a concrete model per environment and optionally per tenant.
- Development uses Ollama locally plus free tiers. In production, each tier gets the cheapest model that passes that tier's test set.

## Decision

Python backend (FastAPI) + **DBOS** (workflows) + **LangGraph** (agents, only where needed) + **LiveKit Agents** (voice) + **LiteLLM** (models) + Postgres (data, vectors, workflow state). Next.js for the dashboard and operator console.

## Consequences

- One database to operate. No separate Temporal, Kafka or vector database.
- Workflow code must be deterministic (read the clock, network and LLMs only inside steps). In-flight workflows need care when code changes: keep step names stable, add rather than rename.
- Voice is a separate deployable with its own latency and scaling profile.
- Smaller community for DBOS than for Temporal. Mitigated by keeping workflows behind thin platform interfaces (`sequences`, `channels`, `agents`).
