# Agentry

**Agentry**: an agency-operated SaaS for selling AI agents to small businesses (India first), one by one or as packs, each client seeing only the agents they bought.

**Status (2026-11-09):** 38 agents built, tested with every login and **live** at https://app.agentry.duckdns.org
(portal), https://agentry.duckdns.org (website) and https://api.agentry.duckdns.org, on an Oracle VM
([docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md)). Where things stand and what's next: [docs/HANDOFF.md](docs/HANDOFF.md).

**Every agent, with its flow:** [docs/flows/README.md](docs/flows/README.md). Who can open what, per role:
[docs/flows/roles-matrix.md](docs/flows/roles-matrix.md).

| Group | Agents |
|---|---|
| Talk to customers | Website chat, WhatsApp assistant, Telegram assistant, AI receptionist (voice), Appointment concierge, Support desk, Catalogue & quotes |
| Leads and sales | Speed-to-lead, Lead reactivation, Lead research, Personal cold email, Renewals & repeat business |
| Back office | Inbox triage, Invoice follow-up, Bookkeeping, Hiring, Stock shelf scanner, Ops dispatcher, SOP & proposal drafter |
| Marketing | Content repurposing (+ engagement loop), AI video studio (+ topic → script), Local SEO, Festival campaigns, Reviews, Competitor watch |
| CA firm pack (13) | Filing tracker, Document chaser, Tax documents reader, Compliance calendar, ITR prep, Capital gains, Bank classifier, GST reconciliation, TDS returns, Tax audit (3CD), Notice handler, Recurring books, Excel desk |
| Everyone | Ask your business + Business copilot (plans actions, runs on **Do it**), Business Pulse, Notification Center, MCP server, prompt-injection guard |
| Agentry HQ | Clients, packs, Demo Studio, proposals, billing and margin, client health |

The table below is the platform as first built (Phases 0–4); the agents above sit on top of it.

## What runs today

| Piece | Where | What it does |
|---|---|---|
| Landing page | `apps/web` → http://localhost:3200 | Hero with "build my free demo", Boring Machine sketch, 8 agents, niches, ROI calculator, pricing, FAQ, demo request form |
| Client portal + Agentry HQ | `apps/dashboard` → http://localhost:3201 | Sign in (password or magic link), org switcher, Home (KPI tiles, trend chart, agents, onboarding progress), Team (invite with roles), Audit log, HQ (all clients, onboarding blockers, demo requests) |
| API | `backend` → http://localhost:8801 (docs at `/docs`) | JWT-verified, per-org row-level security, roles from `config/roles.json`, audit log, public demo-request endpoint |
| Worker | `backend` (DBOS) | Outbox → durable event handlers: inbox triage per email, demo request emails, daily inbox digest, metric rollups |
| Inbox triage | `backend/src/agentry/automations/inbox_triage` | Rules → model classification → labels → urgent alerts → reply drafts in "Needs you" → leads/invoice events |
| Website chat agent | `backend/src/agentry/agents` + `apps/widget` | LangGraph agent (knowledge search, availability, booking, lead capture, handoff), embeddable 9 KB widget, public widget API |
| Booking | `backend/src/agentry/booking.py` | Availability from staff hours/holidays; double-booking impossible (Postgres exclusion constraint) |
| Demo Studio | Agentry HQ → Demo Studio, `apps/web/demo/[slug]` | Prospect URL → crawled knowledge + brand → demo page with their live chat agent (expires in 14 days) |
| Lead engine | `backend/src/agentry/leads.py` | One contact per person (E.164 phones, emails, merging), consent + suppression checked before every message, opt-out words, one-automation-owns-a-lead rule, pipeline stages |
| Sequence engine | `backend/src/agentry/sequences.py` | Durable workflow per enrollment: step N on day X, sleeps for days, woken by payments/replies/opt-outs, catch-up sends only the latest due step, approval mode, watchdog repairs missed starts |
| Invoice follow-up | `automations/invoice_follow_up`, `invoices.py`, portal → Invoices | Import CSV/Excel (Sheets, Tally, QuickBooks formats), reminders 7/14/21/28 with facts from the database, Razorpay/Stripe webhooks (signed, strong/weak matching), reply actions (promise → pause, dispute → stop, opt-out) |
| Reactivation + speed-to-lead | `automations/lead_reactivation`, `automations/speed_to_lead`, portal → Campaigns, Leads | Old-lead import with consent, eligibility preview, paced campaigns, lead-form webhooks with instant first touch, inbound replies take over |
| Gmail | `backend/src/agentry/connectors/gmail.py`, portal → Connections | OAuth (gmail.modify), sync every minute, Agentry labels, threaded reply drafts, send on approval. Setup: [docs/setup/gmail.md](docs/setup/gmail.md) |
| WhatsApp | `connectors/whatsapp.py`, `automations/whatsapp_assistant` | Cloud API: signed webhooks, AI assistant replies (approval or automatic), 24-hour window rule, delivery statuses, templates. Setup: [docs/setup/whatsapp.md](docs/setup/whatsapp.md) |
| Billing | `billing.py`, `worker/billing_jobs.py`, portal → Billing, Reports | Pricing plans per client (setup, retainer, pilot, included usage + overage, fee per booked appointment, capped share of overdue money recovered, GST), outcomes recorded with evidence and attribution rules, monthly draft statements (1st, 06:30 IST), issue → email + Razorpay/Stripe payment link + 7-day dispute window, finalise, paid via webhook; results report with ROI ×; CSV exports; notification preferences |
| Client onboarding | HQ → + New client, `features.py`, `clients.py`, [docs/CLIENT-ONBOARDING.md](docs/CLIENT-ONBOARDING.md) | Create a client with the automations they bought, owner invitation (magic link, no password) and plan; only those automations' sections, steps and connections are visible (enforced by the API); upsell switches; staff "open their portal" (audited) |
| Agentry HQ | portal → All clients, Revenue & margin, Proposal builder | Client page (plan editor, statements, disputes, margin last month, automations, team), margin across clients, ROI proposal → printable PDF → apply as the client's plan |
| Client experience | portal → Account & notifications, Knowledge | Installable portal (PWA), set/change password, monthly results email, onboarding reminders, knowledge from pasted text and PDF/Word/text/CSV uploads |
| Ops | `ops.py`, `infra/`, [docs/DEPLOY.md](docs/DEPLOY.md) | Docker images, `docker-compose.prod.yml`, k3s manifests for Oracle (Traefik, TLS, probes), nightly verified backups, `agentry alerts` every 10 min |
| Agentry's own sales | `backend/src/agentry/sales.py`, `worker/sales_jobs.py`, HQ → Demo requests | Website demo request → alert + personal confirmation + lead in Agentry's own account → HQ request page: build demo (Demo Studio, prefilled), preview and send the demo email with the video, follow-ups on days 2/5/10 until they reply, convert to client (prefilled). Proposals sent from the builder (private link on the website, opened-alert). Replies detected in the Agentry Gmail (IMAP, read-only, every 2 min): reply → in talks + alert; out-of-office recorded; bounces flagged |
| Voice / AI receptionist (Phase 4.1–4.2 + callbacks, minutes, retention) | `backend/src/agentry/voice`, portal → Talk to your agent | `agentry voice` worker (LiveKit Agents + OpenAI speech) answering with the same agent brain as chat; browser test calls with live transcript; calls saved as conversations with recording, AI summary (outcome, follow-up) and an audio player; "Call back" cards; call minutes on plans; recording retention; receptionist switchable in HQ (go-live waits for phone numbers) |
| LLM gateway | `backend/src/agentry/llm` | Model tiers via LiteLLM (mock mode when unset), cost tracking per org, prompt registry, `agentry eval` test-set runner |
| Postgres + Mailpit | `docker-compose.yml` | Postgres 16 + pgvector on :55432; all dev emails caught at http://localhost:58025 |

## First-time setup

Needs Docker, Node 24 + pnpm, and uv.

```bash
cp .env.example .env                     # then set BETTER_AUTH_SECRET (openssl rand -base64 32)
docker compose up -d                     # Postgres + Mailpit
pnpm install
pnpm --filter @agentry/dashboard auth:migrate    # Better Auth tables (schema auth)
cd backend && uv sync && uv run alembic upgrade head && cd ..
pnpm --filter @agentry/dashboard seed:auth       # demo users + 4 client organisations
cd backend && uv run agentry seed && cd ..       # mock clients + packs (persona, services, staff, FAQs), 65 days of events
cd backend && uv run python -c "import asyncio; from agentry.agents.runtime import setup_checkpointer; asyncio.run(setup_checkpointer())" && cd ..
```

## Run (four terminals, plus one for voice)

```bash
cd backend && uv run agentry api         # :8801
cd backend && uv run agentry worker      # outbox + rollups
cd backend && uv run agentry voice       # optional: voice calls (needs `docker compose up -d livekit`)
pnpm --filter @agentry/dashboard dev     # :3201
pnpm --filter @agentry/web dev           # :3200
```

**Demo logins** (password `agentry-demo-123`; also one-click buttons on the sign-in page in development):

| Email | Who |
|---|---|
| riya@sharmadigital.example | Owner, Sharma Digital Agency (inbox triage + invoices, INR) |
| neha@smilecraft.example | Owner, SmileCraft Dental (receptionist, chat, reactivation) |
| frontdesk@smilecraft.example | Front desk at SmileCraft (limited role: no audit, no billing) |
| natarajan@kaverisupplies.example | Owner, Kaveri Industrial (still onboarding, one blocker) |
| jordan@brightpath.example | Owner, Brightpath Consulting (USD) |
| multi@agentry.dev | Belongs to two businesses (org switcher) |
| accounts@sharmadigital.example | Finance at Sharma Digital |
| owner@ / manager@ / frontdesk@ / finance@ / viewer@everyagent.example | **Every Agent Co**: all 38 agents live, one login per role, for testing (`uv run agentry seed-every-agent` after `seed:auth`) |
| admin@agentry.dev | Agentry staff → Agentry HQ |

## Checks

```bash
cd backend && uv run pytest -q          # ~390 tests (2 live-model tests skip without keys): every agent, RLS, roles, billing, voice
cd backend && uv run pytest tests/test_role_matrix.py   # every portal endpoint x every role x every agent
AGENTRY_ROLE_MATRIX=../docs/flows/roles-matrix.md uv run pytest tests/test_role_matrix.py   # ...and regenerate the role table
uv run --project backend python infra/smoke/crawl_portal.py   # sign in as every demo login, open every portal page (dashboard on :3201)
cd backend && uv run ruff check src tests migrations
pnpm typecheck && pnpm build
cd backend && uv run agentry eval invoice_reply_classifier ../mock-data/replies.jsonl --min-accuracy 0.9
cd backend && uv run agentry alerts --dry-run   # the production health check, against your dev database
pnpm --filter @agentry/widget build     # rebuild the chat widget into apps/web/public and apps/dashboard/public
```

**Stop `agentry worker` before running the tests.** Tests share the dev database. A running worker processes the test organisations' events while the tests delete them, which causes flaky failures and "failed workflow" noise in `agentry alerts`.

### Models (OpenAI + Gemini)

Put `GEMINI_API_KEY` and/or `OPENAI_API_KEY` in `.env`. Each tier is a fallback chain (`AGENTRY_MODEL_FAST=gemini/…,openai/…`); see [ADR 0003](docs/decisions/0003-models-openai-and-gemini.md).

```bash
cd backend && uv run agentry models --ping      # models your keys can use + a test call per tier
uv run agentry reindex                          # after changing AGENTRY_MODEL_EMBED
uv run agentry eval inbox_triage_classifier ../mock-data/inbox-triage/heldout.jsonl --field category,urgent
uv run agentry load-inbox sharma-digital        # feed the mock inbox through the live worker
AGENTRY_LIVE_TESTS=1 uv run pytest tests/test_live_models.py   # real tool-calling smoke test
```

Without keys everything runs in mock mode (rules and knowledge-base answers, clearly labelled as demo mode).

## Docs

- [Platform plan](docs/PLAN.md): architecture, stack, pricing, phases
- [Client portal: logins, onboarding, dashboard](docs/CLIENT-PORTAL.md)
- [Design: brand, landing page, portal](docs/DESIGN.md)
- [Pricing playbook](docs/PRICING.md) · [Go-to-market](docs/GO-TO-MARKET.md)
- Decisions: [0001 runtimes and models](docs/decisions/0001-runtime-and-models.md) · [0002 Better Auth](docs/decisions/0002-auth-better-auth.md) · [0003 OpenAI + Gemini](docs/decisions/0003-models-openai-and-gemini.md)
- Flagship: [The Boring Machine](docs/automations/boring-machine.md)
- Specs: [inbox triage](docs/automations/inbox-triage.md) · [AI receptionist](docs/automations/ai-receptionist.md) · [lead reactivation](docs/automations/lead-reactivation.md) · [invoice follow-up](docs/automations/invoice-follow-up.md) · [content repurposing](docs/automations/content-repurposing.md) · [cold email](docs/automations/cold-email.md)
- Setup guides: [connect Gmail](docs/setup/gmail.md) · [connect WhatsApp](docs/setup/whatsapp.md)
- [Onboarding a client (roles, steps, what each automation shows)](docs/CLIENT-ONBOARDING.md)
- [Deploying to Oracle Cloud (k3s)](docs/DEPLOY.md)
- [Phase 4 plan: voice (receptionist, speed-to-lead calls)](docs/PHASE-4-VOICE.md)
- [Phase 5 plan: personal cold email](docs/PHASE-5-COLD-EMAIL.md)
- **[Flows: sales, onboarding, billing and every agent, with diagrams](docs/flows/README.md)** · [who can open what](docs/flows/roles-matrix.md)
- Roadmaps: [v2](docs/ROADMAP-V2.md) · [v3](docs/ROADMAP-V3.md) · [packs](docs/PACKS.md) · [sales stories](docs/SALES-STORIES.md)
- [Deploying to the Oracle VM (live)](docs/DEPLOY-ORACLE.md) · [Handoff: current state](docs/HANDOFF.md)
- [Mock clients and test sets](mock-data/README.md)
