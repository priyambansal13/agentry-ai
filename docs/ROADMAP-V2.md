# Agentry v2 — roadmap

> **Where we are (31 Oct 2026):** all 9 v1 agents are built, plus Telegram (customer bot + team bot). Inbox triage,
> website chat, WhatsApp, invoices, reactivation and speed-to-lead are ready to sell. The receptionist, cold email and
> content agents work in test mode until their accounts are connected.
> **This plan:** what to build next, and in what order. It is split into a platform layer every agent benefits from, the
> content agent's v2, notifications for any event, and 14 new agents. It draws on your other projects, the cloned apps
> and the `awesome-llm-apps` catalogue (§9 lists exact references).
> **Status:** plan, with **7.1 Notification Center, 7.5 run traces and 9.1 Business Pulse (brief) built 2026-10-31, plus 7.2 governance** (flows: [governance](flows/governance.md), [notifications](flows/notifications.md), [business pulse](flows/agents/business-pulse.md)). Decisions in §10 are yours.

## 0. The plan at a glance

| Phase | What | Why first / why then | Needs from you |
|---|---|---|---|
| **7. Platform for many agents** | Notification Center (any event → WhatsApp / Telegram / email / in-app), agent governance (autonomy levels, policies), always-on Watchers, Document AI, run traces & cost, Agentry MCP server | Every new agent needs these; building them once keeps 14 agents consistent and safe | A WhatsApp utility template approved by Meta (for WhatsApp alerts) |
| **8. Content v2** | Real posting, vertical clips with captions, newsletter + SEO blog from the same recording, topic → script mode, Hindi/regional languages, engagement loop | Content is a retainer product; v2 roughly doubles the output per recording | LinkedIn app, Instagram business account; later Sarvam key |
| **9. New agents, wave 1** (fast wins, reuse what exists) | Business Pulse, Review & Reputation, Appointment Concierge, Lead Research & Meeting Prep, Bookkeeping Assistant | Small builds, clear money value, each sells to a niche we already target | Google Business Profile access; Tally/Sheets for bookkeeping |
| **10. New agents, wave 2** (watchers + content family) | Competitor & Price Watch, Local SEO & Blog, Support Desk with tickets, Business Copilot (chat/Telegram with tools) | Built on Watchers + Document AI + MCP from phase 7 | Firecrawl (or similar) key |
| **11. New agents, wave 3** (vertical packs) | Hiring Assistant, Returns & Refunds (D2C), Stock Shelf Scanner, Ops Dispatcher (home services), SOP & Proposal Drafter | Deeper per-niche value; unlock new niches | Per pack (Shopify/WooCommerce, Calendar…) |

## 1. Principles (kept from v1, tightened)

1. **Agents propose, deterministic code disposes.** Models draft, classify and extract. Anything with consequences
   (money, messages to customers, deleting) goes through code that checks rules, then a person or a trusted auto rule.
   This is the agentic-commerce principle (`agentic-commerce/platform/docs/03-agentic-ai.md`).
2. **Autonomy is earned per business, per action.** Every action starts in *recommend* (a Needs-you card). It moves to
   *auto* only after a track record (as inbox triage auto-send does today: 10 approvals unchanged). See §2.2.
3. **Facts only from sources we can show.** Cold email cites the website and content cites the transcript; v2 agents
   cite reviews, receipts, competitor pages and the business's own data. A deterministic check comes first, then a model check.
4. **One brain, many channels.** Portal, WhatsApp, Telegram, email and voice all reach the same agent and the same
   approvals.
5. **Mock first, keys later.** Every outside service sits behind an interface with a mock, so a whole agent is built
   and tested before anyone buys an account.
6. **Port designs, not code.** The reference projects use other stacks (NestJS, Streamlit, Convex, Inngest). We take
   their flows and prompts and rebuild them on FastAPI + DBOS + LangGraph + LiteLLM.

## 2. Phase 7 — Platform for many agents

### 2.1 Notification Center: any event, to the right person, on the right channel

Today alerts are a fixed set of kinds (urgent, escalation, digest, weekly, billing, reports, cards). People choose
email, WhatsApp or Telegram for each. v2 makes **every event** notifiable, with rules a business can set without us.

**Events (the catalogue).** About 30 events are already emitted (`app.events`). v2 adds the new agents' events and
gives each one a name, a sentence template and a default audience:

| Area | Events (✓ exists today) |
|---|---|
| Leads & bookings | ✓ lead.created · ✓ booking.created · booking.cancelled · booking.no_show · ✓ cold_email.interested · ✓ demo_request.created |
| Conversations | ✓ email.triaged (urgent) · ✓ whatsapp.received · ✓ telegram.received · conversation.handed_off · conversation.unanswered (SLA) |
| Money | ✓ payment.received · invoice.overdue (N days) · invoice.disputed · ✓ statement.issued · budget.threshold (bookkeeping) · receipt.needs_review |
| Work queue | ✓ approval.created · approval.waiting_long (e.g. 4 h) · ✓ approval.decided |
| Voice | ✓ call.completed · call.missed · callback.requested |
| Content & marketing | ✓ content.ready · ✓ content.published · post.performed (top post) · review.received (★1–5) · competitor.changed · seo.rank_changed |
| Platform | ✓ org.went_live · connection.broken (Gmail/WhatsApp token expired) · agent.paused · usage.limit_near |

**Rules.** Each rule says *when* an event happens, *if* some conditions hold, *tell* certain people *on* certain
channels, *how* often. Examples, written the way an owner would see them:
- "When a payment over ₹10,000 arrives → tell me on WhatsApp, now."
- "When a 1- or 2-star review arrives → tell the manager on Telegram and email, now."
- "When a Needs-you card has waited 4 hours → tell the owner on Telegram."
- "Every lead → a digest at 6 pm on email."

Defaults ship per agent, so nothing has to be configured on day one. Owners and managers set business-wide rules;
everyone sets their own channels and quiet hours.

**Channels and their rules.**

| Channel | Constraint | How we handle it |
|---|---|---|
| **Telegram** (team bot) | Free text, buttons, no cost | Default for the team; action buttons where the event has an action (approve, call back, open) |
| **WhatsApp** | Business-initiated messages need a **Meta-approved template** outside the 24-hour window; per-message cost | One generic *utility* template (`agentry_update`: title, details, link) plus 3–4 specific ones (payment received, new lead, review alert). Inside the 24-hour window, send free text with buttons |
| **Email** | Always works | Fallback for everything; digests |
| **In-app** | Only when the portal is open | A bell with unread count in the portal, and browser push for the installed PWA |
| **SMS** (later) | Paid, DLT registration in India | Critical-only fallback once telephony exists |

**Delivery engine** (one DBOS workflow per notification):
- match rules;
- **dedupe** (the same event never notifies twice);
- **throttle** (per person per hour, e.g. at most 10; the rest roll into a digest);
- **quiet hours** (held until morning unless marked critical);
- try the channel; on failure, **fall back** (Telegram → WhatsApp → email);
- write a **delivery log**: what went where, delivered or failed, read if known.

The owner can see "why did I get this?", and Agentry staff can see failures in HQ.

**Customer-facing notifications** (separate from team ones, with stricter rules): appointment confirmations and
reminders, payment receipts, "your order/job is on the way". Same engine, but only on channels the customer consented
to, with templates the business approves, and always with an opt-out.

**Data:** `notification_rules` (event, conditions, audience, channels, cadence, scope: business/person),
`notifications` (event → person → channel, status, attempts, read_at), `notification_templates` (per event and
channel, versioned). The current `notification_preferences` becomes each person's channel and quiet-hours settings.

**Built when:** a rules page (Settings → Notifications) with templates of common rules, a per-person page, a bell in
the portal, a delivery log in HQ, and tests for rules, dedupe, throttle, quiet hours and fallback.

### 2.2 Governance: autonomy levels, policies, audit

Taken from agentic-commerce (`backend/services/agents/src/governance/`, OPA policies, evals) and
`awesome-llm-apps/.../ai_agent_governance`.

- **Autonomy levels per business, per action:**
  - *shadow*: logged only, nothing shown;
  - *recommend*: a Needs-you card (the default);
  - *auto with limits*: e.g. reply to FAQ emails, or refund under ₹500, max 20 a day;
  - *auto*.

  Promotion is suggested by the data (approvals without edits) and needs an owner's OK.
- **Policies before side effects:** every tool that sends, pays or deletes calls `policy.check(action, context)`. Rules
  live as data (JSON/YAML per agent), with no new service: amount caps, quiet hours, consent, suppression, per-day limits.
- **Audit with integrity:** the existing audit log gains a hash chain (each row hashes the previous one), so it can't be
  quietly edited. This matters for refunds and payments.
- **Evals as a gate:** each agent keeps a small labelled set (we have this for triage and invoice replies). A prompt or
  model change must keep scores before it ships, enforced in CI.

### 2.3 Watchers: always-on agents

✅ Built 2026-10-31 (`backend/src/agentry/watchers.py`).

Several new agents follow the same loop: check something on a schedule, notice a change, explain it, and notify or
act. Examples are reviews, competitor pages, prices, search rankings and budgets. References: the price tracker's
`pg_cron` + scrape + diff + email (`Cloned projects/smart-product-price-tracker`), the finance app's six-hourly budget
check with a "once a month" limit (`ai-finance-platform/lib/inngest/function.js`), `always_on_agents/*`.

A **Watcher** is configuration, not code:
- a source (URL, API or query);
- an extractor (schema-based, via Firecrawl or our crawler plus the `fast` model);
- a schedule;
- a diff rule ("price changed by more than 5%", "a new review");
- a summariser;
- an event.

Notifications come from §2.1. Cost is bounded: a page is fetched again only if its content hash changed, and the model
runs only on changes.

### 2.4 Document AI: photos and PDFs into typed data

✅ Built 2026-10-31 for receipts and bills (`backend/src/agentry/documents.py`, `docs/flows/agents/bookkeeping.md`).

One shared service: an image or PDF goes in, typed JSON comes out, with **a confidence for every field** and the
evidence (the crop and the page). Below a threshold, a person checks it. References: receipt scanning (finance app
`scanReceipt`), the pantry scan with confidence filtering (recipe app), and `rag_tutorials/vision_rag`.

Used by: Bookkeeping (receipts, bills, GSTIN), Hiring (CVs), Stock Scanner (shelves), Support Desk (attachments), and
today's invoice import (photographed invoices).

### 2.5 Runs: traces, cost and a live view

- Every agent run has a **trace**: steps, tool calls, model, tokens, cost and duration. Today `llm_calls` has cost per
  call; v2 groups calls into runs (the pr-reviewer pattern: cost and tokens per run).
- **Cost per agent per client** in HQ, next to revenue, so pricing is grounded.
- A **live run view** in the portal ("Drafting your reply… checking the invoice… done"). This streams step events like
  the travel planner's AG-UI streaming, and builds trust when a client watches an agent work.

### 2.6 Agentry MCP server, and MCP tools for agents

- **Server:** a business (or Agentry staff) can connect Claude Desktop or ChatGPT to their Agentry, read-only first:
  "what's overdue?", "summarise this week's leads". Per-person tokens, the same permissions as the portal. SwarmAI's
  StoryForge MCP server (`swarm-ai/brain/src/studio/mcp.controller.ts`) is the reference.
- **Client:** agents call outside tools through MCP where an official server exists (Google Calendar and Sheets,
  Notion), instead of a custom connector for each. Reference: `mcp_ai_agents/multi_mcp_agent`, `notion_mcp_agent`.

## 3. Phase 8 — Content v2

| # | Milestone | Done when |
|---|---|---|
| 8.1 | **Real publishing** (was 6.5): LinkedIn (company page) and Instagram (business account through the existing Meta app) behind the publisher interface; posting retries; a link back to the live post | A scheduled post appears on both platforms; failures retry, then show in the portal and notify (§2.1) |
| 8.2 | **Vertical clips** (9:16 Reels/Shorts): cut each moment from the video with ffmpeg; burn in captions from the transcript's word timestamps; frame the speaker (centre crop first, face tracking later); add a brand intro and outro | A 45-min video gives 10 clips of 20–60 s, captioned, in the brand style; for video sources only |
| 8.3 | **Newsletter + SEO blog** from the same moments: a 600–900 word article (headings, quotes, FAQ, meta description) and an email newsletter (Mailchimp/Brevo export, or our SMTP) | One recording yields posts, clips, a blog article and a newsletter; quote checks apply to all |
| 8.4 | **Topic → script mode** (StoryForge): no recording? Give a topic; it researches and writes a timed Shorts script for the owner to record, in 8 languages. Ported from `swarm-ai/docs/STUDIO.md` | A clinic owner gets 4 scripts a week to film on their phone; the recordings come back through the normal flow |
| 8.5 | **Languages:** Hindi and regional transcription (Sarvam), posts in the language spoken or chosen, Hinglish | A Hindi podcast gives Hindi posts with exact Hindi quotes |
| 8.6 | **Engagement loop:** fetch likes, comments and reach at +24 h and +7 d; learn which hooks and topics work for this business; feed that into moment ranking; a "top post" event | Ranking weights change per business based on results; the monthly report shows the best posts |
| 8.7 | **AI images (opt-in):** a generated background behind the quote card, or an illustration, with cost per image shown | Off by default; per-business switch; never shows people |

## 4. Phase 9–11 — New agents

Each agent below lists what it does, who buys it, the v1 and v2 pieces it reuses, the reference to port from, effort
(S under 1 week, M 1–2 weeks, L 3+ weeks) and its pricing model. Every agent starts in *recommend* mode.

### Wave 1 — quick wins (Phase 9)

**9.1 Business Pulse (S → M).**
- *What:* a morning brief and a Monday week-in-review for the owner, on Telegram or WhatsApp: money in and overdue,
  new leads, bookings, calls missed, reviews, what needs them. Ranked, with one suggested action each.
- *Then:* **"Ask your business"** in the portal and on Telegram: plain-English questions over their own data ("which
  clients paid late twice this quarter?"), answered with a chart. Read-only SQL through a guarded view layer; the
  query and data behind each answer are shown.
- *Buyers:* every client (included in all plans; it drives retention).
- *Reuses:* the metrics registry, reports, the Telegram Tools, notifications.
- *References:* `always_on_agents/always_on_hn_briefing_agent`, `devpulse_ai`; the finance app's monthly AI insights;
  `starter_ai_agents/ai_data_analysis_agent` and `generative_ui_agents/ai-dashboard-canvas-agent` for charts;
  cold-chain's read-only SQL guard (`cold-chain-dispatch/coldchain/db.py`).

**9.2 Review & Reputation (M).** ✅ Built 2026-10-31 with sample reviews until Google Business Profile access (`docs/flows/agents/reviews-and-watchers.md`).
- *What:*
  - Reads new Google reviews (Google Business Profile API).
  - Classifies sentiment, topic and urgency.
  - Drafts a reply in the business's voice, approved before it's posted.
  - Alerts at once on 1–2 stars.
  - Asks happy customers for a review after a booking is marked "showed" or an invoice is paid, by WhatsApp or email,
    with consent.
  - A monthly reputation report: rating trend and themes such as "waiting time" (as Dr. Neha's reviews were).
- *Buyers:* clinics, salons, restaurants, home services.
- *Reuses:* inbox-style drafting, the trust gate for auto-replies to 5-star reviews, Watchers, notifications.
- *References:* `2_2_product_review_agent` (typed review analysis), the hospital CRM's safety-first replies.
- *Pricing:* retainer; optional per review request sent.

**9.3 Appointment Concierge (S–M).** ✅ Built 2026-10-31 (`docs/flows/agents/appointment-concierge.md`); the review request waits for 9.2.
- *What:*
  - Confirmations, and a WhatsApp reminder the evening before ("reply 1 to confirm, 2 to reschedule": the 22% → 8%
    no-show story from the sample podcast).
  - Rebooking in one tap, and waitlist filling when someone cancels.
  - Recalls ("6 months since your cleaning").
  - Post-visit care messages, and the review request (9.2).
- *Buyers:* clinics, salons, physio, coaching.
- *Reuses:* the booking service, the sequence engine, the WhatsApp/Telegram assistant, templates.
- *References:* hospital-crm Care Concierge (`backend/services/ai-assistant-service/src/`, `platform/docs/AI-AGENTS.md`),
  and its emergency rules before any model call.
- *Pricing:* per active patient or a flat retainer, plus a per-saved-no-show outcome option.

**9.4 Lead Research & Meeting Prep (S).** ✅ Built 2026-10-31 (`docs/flows/agents/lead-research.md`).
- *What:* each new inbound lead is enriched within minutes (company, size, website summary, decision maker, likely
  need) before speed-to-lead or a sales call. A one-page brief arrives 30 minutes before any meeting on the calendar.
- *Buyers:* agencies, CA firms, B2B services.
- *Reuses:* the cold email research pipeline (crawl, people, snippets), Calendar, notifications.
- *References:* `ai_email_gtm_outreach_agent`, `ai_meeting_agent`.
- *Pricing:* included with the lead engine; per brief beyond a quota.

**9.5 Bookkeeping Assistant (M).** ✅ Built 2026-10-31 except email intake, Sheets push and the CA-firm view (`docs/flows/agents/bookkeeping.md`).
- *What:*
  - Clients send photos or PDFs of receipts and bills on WhatsApp, Telegram or email.
  - Agentry extracts vendor, date, amounts, GSTIN, tax split and category, with confidence; low confidence becomes a card.
  - Checks for duplicates and GSTIN validity.
  - Exports to Tally (XML) or Google Sheets.
  - Monthly AI insights, plus budget alerts (at 80%, once a month).
  - The CA firm sees all of its clients in one place.
- *Buyers:* CA and accounting firms (selling to their clients), shops, clinics.
- *Reuses:* Document AI (§2.4), the WhatsApp/Telegram inbound, notifications, invoice import.
- *References:* the finance app's `scanReceipt`, budget alerts and monthly insights (`Cloned projects/ai-finance-platform`).
- *Pricing:* per document processed, plus a retainer for the firm.

### Wave 2 — watchers and the content family (Phase 10)

**10.1 Competitor & Price Watch (M).**
- *What:* watches competitor websites, price pages and marketplace listings daily: new offers, price changes, new
  services. A weekly brief with a "what to do about it" suggestion, and instant alerts above a threshold.
- *Buyers:* shops and D2C, agencies, home services.
- *Reuses:* Watchers (§2.3), notifications.
- *References:* `Cloned projects/smart-product-price-tracker` (Firecrawl schema extraction, daily cron, drop alerts),
  `ai_competitor_intelligence_agent_team`, `product_launch_intelligence_agent`.
- *Pricing:* per competitor or page watched.

**10.2 Local SEO & Blog (M).**
- *What:*
  - Audits the website (titles, speed basics, schema, Google Business Profile completeness) against the top local results.
  - A prioritised fix list.
  - Two location-targeted articles a month in the business's voice, with FAQ schema.
  - Tracks rankings for 10–20 keywords; alerts on big moves.
- *Buyers:* clinics, home services, local shops.
- *Reuses:* the crawler, the content writer and quote/fact checks, Watchers.
- *References:* `ai_seo_audit_team`, `ai_journalist_agent`, `Cloned projects/ai-creator-platform` (generate/improve modes).
- *Pricing:* retainer.

**10.3 Support Desk (M).**
- *What:* upgrades website chat and WhatsApp/Telegram into a desk.
  - Answers with citations from the knowledge base, using corrective RAG: it grades its retrieval and retries, and says
    "I don't know" when the evidence is weak.
  - Turns issues into **typed tickets** with priority, SLA, assignee and status.
  - SLA breach events (§2.1); customer satisfaction after resolution.
- *Buyers:* D2C, SaaS-like services, agencies.
- *Reuses:* the knowledge base, conversations, auto-assign rules, notifications.
- *References:* `swarm-ai/brain/src/desk` (desk and handoff to staff), `rag_tutorials/corrective_rag`,
  `agentic_typed_rag_pydanticai`, `2_1_support_ticket_agent`.
- *Pricing:* per resolved ticket, or a retainer.

**10.4 Business Copilot (M–L).**
- *What:* the team bot and the portal become a real agent. "Send Rohan a reminder about E-1 and move his callback to
  Monday" runs as a plan with tool calls: each step is shown and approved by policy (§2.2), and voice notes work on
  Telegram/WhatsApp.
- *Buyers:* every owner (premium tier).
- *Reuses:* all agents' tools, MCP (§2.6), governance (§2.2), the Telegram team bot.
- *References:* SwarmAI's master agent and specialists with approval before side effects (`swarm-ai/brain/`),
  `mcp_ai_agents/multi_mcp_agent_router`.
- *Pricing:* premium add-on.

### Wave 3 — vertical packs (Phase 11)

**11.1 Hiring Assistant (M).**
- *What:* a job post goes to the careers page and job boards (export). Incoming CVs (email, upload, WhatsApp) are
  parsed, scored against the job description with reasons, the top candidates are shortlisted for the owner, and
  interviews are scheduled on the calendar.
- *Buyers:* clinics, agencies, home services hiring technicians.
- *References:* `ai_recruitment_agent_team`, `advanced_llm_apps/resume_job_matcher`.
- *Pricing:* per role, or per CV.

**11.2 Returns & Refunds (M)** for D2C shops.
- *What:* a return request is checked against policy (window, condition, amount caps); refund or exchange is proposed
  and auto-executed within limits; fraud signals are flagged.
- *References:* the agentic-commerce refund agent, `policies/refunds/policy-v1.json`, `evals/refund`.
- *Needs:* Shopify / WooCommerce connectors.

**11.3 Stock Shelf Scanner (S–M)** for shops and cafes.
- *What:* a photo of a shelf or storeroom becomes a stock list with confidence. It's compared with last time,
  reorders are suggested, and a supplier message is drafted.
- *References:* the recipe app's pantry scan (`ai-recipe-platform/frontend/actions/pantry.actions.js`).

**11.4 Ops Dispatcher (L)** for home services.
- *What:* job requests (WhatsApp, calls, forms) become jobs. Each is assigned by skill, area and workload; the
  customer gets "technician on the way" updates; a photo of the finished job closes it and triggers the invoice.
- *References:* the jira-clone data model (jobs, assignees, status), cold-chain's tool-using copilot with approved
  actions and weather/routing tools, the ticketing-system's idempotency and outbox patterns.

**11.5 SOP & Proposal Drafter (M)** for agencies and clinics.
- *What:* one prompt produces a process flowchart plus the written SOP, a client proposal or an onboarding checklist.
  It's an agent that edits two surfaces (diagram + document) with tools.
- *Reuses:* the existing proposal builder.
- *References:* `Cloned projects/agentic-workspace-saas/lib/agent-tools.ts` (canvas and document tools).

**Not planned (and why).**
- *AI app/site builder* (`ai-app-builder`): an internal agency tool more than something a client buys. Revisit for
  landing pages later.
- *Travel planner* and *ticketing*: niche or unrelated. Their patterns (AG-UI streaming, idempotency) are borrowed in
  §2.5 and 11.4.

## 5. Packs: how it's sold

| Pack | Agents |
|---|---|
| **Clinic** | Receptionist · Appointment Concierge · Review & Reputation · WhatsApp/Telegram assistant · Content · Business Pulse |
| **Home services** | Speed-to-lead · Receptionist · Ops Dispatcher · Review & Reputation · Local SEO · Invoices |
| **Agency / B2B** | Inbox triage · Cold email · Lead Research · SOP & Proposal Drafter · Content · Invoices |
| **CA / accounting firm** | Bookkeeping Assistant · Invoices · Inbox triage · Business Pulse (for each client) |
| **Shop / D2C** | Support Desk · Returns & Refunds · Competitor & Price Watch · Stock Scanner · Reviews |

Business Pulse and notifications come with every pack. Pricing follows `docs/PRICING.md`: setup plus retainer, plus
outcome or usage meters per agent. Meters needed: documents, reviews, watchers, tickets, CVs and clips.

## 6. Build order and milestones

| Order | Milestone | Size | Unblocks |
|---|---|---|---|
| 1 ✅ | 7.1 Notification Center (rules, engine, channels, bell, delivery log) | M | Everything below (all agents emit events) |
| 2 ✅ | 7.5 Run traces + cost per run | S | Pricing and debugging for every new agent |
| 3 ✅ | 9.1 Business Pulse (brief first; "ask your business" next) | S | A daily habit for owners; shows value |
| 4 ✅ | 7.2 Governance (autonomy levels, policy checks, hash-chained audit, eval gate) | M | Safe auto-actions for reviews, refunds and the copilot |
| 5 | 9.3 Appointment Concierge · 9.4 Lead Research | S + S | Clinic and agency packs |
| 6 | 7.4 Document AI → 9.5 Bookkeeping | M + M | CA firm pack |
| 7 | 7.3 Watchers → 9.2 Reviews · 10.1 Competitor Watch | M + M + S | Local business and shop packs |
| 8 | 8.1 Real publishing · 8.3 Blog + newsletter · 8.2 Clips | S + M + M | Content retainer v2 |
| 9 | 10.2 Local SEO · 10.3 Support Desk | M + M | |
| 10 | 7.6 MCP server · 10.4 Business Copilot | M + L | Premium tier |
| 11 | Wave 3 packs as clients ask | — | New niches |

Each milestone follows the v1 pattern:
- a plan section with roles;
- mocks for outside services;
- tests for every role;
- a live check with the real models;
- a flow doc in `docs/flows/agents/`;
- a handoff update.

## 7. What changes in the data model (summary)

New tables:
- notifications: `notification_rules`, `notifications`, `notification_templates`;
- governance: `autonomy_settings` (per business, agent and action), `policies`;
- runs: `agent_runs` (with `llm_calls.run_id`);
- watchers: `watchers`, `watch_snapshots`;
- Document AI: `documents` (file, type, extracted JSON, confidence, review state);
- per agent: `reviews`, `tickets`, `candidates`, `jobs`, `stock_counts`.

Row-level security and the existing role permissions apply to all of them. New permissions: `review:act`,
`ticket:act`, `hiring:act`, `bookkeeping:act`, with roles extended in `config/roles.json`.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Notification fatigue (owners mute everything) | Sensible defaults, digests, throttling, a "you got 40 alerts this week — tune?" nudge, and most events off by default except money, urgent and cards |
| WhatsApp template rejection and cost | Generic utility template first; Telegram as the free default for teams; cost per message shown in HQ |
| Scraping fragility (competitor watch, SEO) | Schema extraction (Firecrawl or LLM), content-hash change detection, "couldn't read" states rather than wrong data |
| Platform API access (Google Business Profile, LinkedIn, Instagram) needs reviews | Apply early; mock first; export/copy always works |
| Document extraction errors in bookkeeping | Confidence per field, human check below a threshold, never auto-export unchecked low-confidence items |
| Too many agents, too little depth | Packs, not a menu: build wave 1 fully (live-verified) before wave 2 |

## 9. References used (for the builder)

| Idea | Where to look |
|---|---|
| Customer desk, handoff, knowledge, industry packs | `swarm-ai/brain/src/desk`, `brain/src/knowledge`, `brain/packs/*.json`, `swarm-ai/docs/PLATFORM.md`, `docs/EXPANSION-PLAN.md` |
| Topic → script, multilingual, MCP server | `swarm-ai/docs/STUDIO.md`, `swarm-ai/brain/src/studio/` (incl. `mcp.controller.ts`) |
| Governance: autonomy levels, OPA policies, hash-chained audit, evals | `agentic-commerce/backend/services/agents/src/governance/`, `backend/policies/`, `backend/evals/refund`, `platform/docs/03-agentic-ai.md` |
| Safety-first clinic AI, metered AI per plan | `hospital-crm/backend/services/ai-assistant-service/src/` (safety, kb, evals), `backend/modules/ai.module.yaml`, `platform/docs/AI-AGENTS.md` |
| Webhook intake, parallel agents, cost per run | `pr-reviewer/services/gateway/signature.py`, `services/webhook/`, `services/orchestrator/graph`, `common/metrics.py` |
| Read-only SQL over business data, approved actions | `cold-chain-dispatch/coldchain/db.py`, `agent.py`, `tools.py` |
| Live agent traces in the UI | `travel-planner/backend/src/agents/` (AG-UI over SSE) |
| Receipt scan, monthly AI insights, budget alerts | `Cloned projects/ai-finance-platform/actions/transaction.js` (`scanReceipt`), `lib/inngest/function.js` |
| Price/page watching with alerts | `Cloned projects/smart-product-price-tracker/lib/firecrawl.js`, `app/api/cron/check-prices/route.js` |
| Photo → inventory with confidence | `Cloned projects/ai-recipe-platform/frontend/actions/pantry.actions.js` |
| Blog generate/improve | `Cloned projects/ai-creator-platform/app/actions/gemini.js` |
| Two-surface agent (diagram + document tools) | `Cloned projects/agentic-workspace-saas/lib/agent-tools.ts` |
| Always-on briefs | `awesome-llm-apps/always_on_agents/always_on_hn_briefing_agent`, `advanced_ai_agents/multi_agent_apps/devpulse_ai` |
| Reviews, tickets (typed output) | `awesome-llm-apps/ai_agent_framework_crash_course/openai_sdk_crash_course/2_structured_output_agent/2_1_support_ticket_agent`, `2_2_product_review_agent` |
| SEO audit, articles | `awesome-llm-apps/advanced_ai_agents/multi_agent_apps/agent_teams/ai_seo_audit_team`, `advanced_ai_agents/single_agent_apps/ai_journalist_agent` |
| Competitor intelligence | `awesome-llm-apps/advanced_ai_agents/multi_agent_apps/agent_teams/ai_competitor_intelligence_agent_team`, `product_launch_intelligence_agent` |
| Recruitment | `awesome-llm-apps/advanced_ai_agents/multi_agent_apps/agent_teams/ai_recruitment_agent_team`, `advanced_llm_apps/resume_job_matcher` |
| Lead research, meeting prep | `awesome-llm-apps/advanced_ai_agents/multi_agent_apps/ai_email_gtm_outreach_agent`, `advanced_ai_agents/single_agent_apps/ai_meeting_agent` |
| Corrective / cited RAG | `awesome-llm-apps/rag_tutorials/corrective_rag`, `agentic_typed_rag_pydanticai`, `hybrid_search_rag` |
| Document vision | `awesome-llm-apps/rag_tutorials/vision_rag`, `multimodal_agentic_rag` |
| Data questions with charts | `awesome-llm-apps/starter_ai_agents/ai_data_analysis_agent`, `generative_ui_agents/ai-dashboard-canvas-agent` |
| MCP agents | `awesome-llm-apps/mcp_ai_agents/multi_mcp_agent`, `multi_mcp_agent_router`, `notion_mcp_agent` |
| Governance examples | `awesome-llm-apps/advanced_ai_agents/single_agent_apps/ai_agent_governance`, `advanced_ai_agents/multi_agent_apps/trust_gated_agent_team` |

## 10. Decisions needed from you

| # | Decision | Options | My recommendation |
|---|---|---|---|
| 1 | Order | As in §6 · agents first, platform later | **§6 order**: the Notification Center first, because every new agent emits events and owners asked for WhatsApp/Telegram alerts |
| 2 | WhatsApp for team alerts | Generic utility template only · plus 3–4 specific templates | **Start generic** (one Meta approval), add specific ones for payments, leads and reviews |
| 3 | First new agent | Business Pulse · Reviews · Bookkeeping | **Business Pulse** (small, every client benefits), then **Appointment Concierge** + **Reviews** for the clinic pack |
| 4 | Scraping provider for watchers and SEO | Firecrawl · our own crawler + model | **Our crawler first** (exists, free), Firecrawl when sites resist |
| 5 | Content v2 first step | Real publishing · clips · blog | **Real publishing** (finishes v1), then **blog + newsletter** (cheap, high value), then clips |
| 6 | Copilot autonomy | Approve every step · auto within policy | **Approve every step** until governance (7.2) has run for a month |
