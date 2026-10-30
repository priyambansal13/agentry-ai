# Handoff: where Agentry stands (2026-10-30)

Code: https://github.com/priyambansal13/agentry-ai (`main`). Everything below is built and tested unless marked open.

## Running it locally

| What | Port | Start |
|---|---|---|
| Postgres, Mailpit, LiveKit (dev) | 55432, 58025 | `docker compose up -d` |
| API | 8801 | `cd backend && uv run agentry api --no-reload` (logs: `var/log/api.log`) |
| Worker (DBOS jobs) | – | `cd backend && uv run agentry worker` (logs: `var/log/worker.log`) |
| Dashboard (portal + HQ) | 3201 | `cd apps/dashboard && pnpm dev --port 3201` |
| Website | 3200 | `cd apps/web && pnpm dev --port 3200` |

- Database: `postgresql://postgres:postgres@localhost:55432/agentry` (superuser, sees every company).
- Tests: `cd backend && uv run pytest -q` → 177 passed, 2 skipped. Stop the dev worker first if tests get flaky.
- The API and worker don't auto-reload: restart them after backend changes.

## Built this session (latest first)

- **Cold email 5.4–5.5 in test mode** (2026-10-30) — sending mailboxes (HQ), start/pause, 4-step sequence with office hours, ramp-up caps, one-click unsubscribe (`/unsubscribe/<token>` on the website), auto-pause on bounces/complaints; replies classified into lead engine / nurture / do-not-contact / cards (migration 0018, `automations/cold_email/sending.py`, `replies.py`). Agentry's sample campaign is running in test mode with a mock mailbox; its postal address is a **placeholder** to replace in the cold email settings.
- **Auto-assign rules** (2026-10-30) — client rule (Invoices → Who handles each client) and agent rule (agent page → Who handles its cards); applied by a DB trigger on new cards (migration 0017, `app.card_routing`), waiting cards re-decided on change, hand-assigned cards untouched. See `docs/flows/README.md`.
0. **Cold email 5.1–5.3** (2026-10-30) — prospect lists (search or CSV), decision maker, verified email, fact-checked first line from their own site, review/approve/export in the portal (`/cold-email`), migration 0016. Mock providers (`mock-data/cold-email/`). Switched on for Agentry's own company; sample list "Pune dental clinics (sample)" built with the real AI: 50 → 49 → 8, all lines passed. Flow: `docs/flows/agents/cold-email.md`.
1. **Forgot password + show-password eye** — `/forgot-password`, `/reset-password` (Better Auth `sendResetPassword`, 1-hour single-use link, works for link-only users, signs out other devices); `PasswordInput` in `packages/ui` used on every password field.
2. **Unsendable reminder cards** — `outbound.channel_problem()`: no WhatsApp card when WhatsApp isn't connected / no template; old cards show a warning and can't be approved (409).
3. **Invoice follow-up audit** — 20 fixes (`tests/test_invoice_e2e.py`, migration 0015), live-verified.
4. **Inbox triage** — 20 improvements + urgent escalation; Outlook; Gmail push.
5. **Sales pipeline** — demo requests, proposals with private links, IMAP reply detection; one-click invitations.
6. **Voice (Phase 4)** — LiveKit Cloud receptionist, recordings, call summaries, callback cards, phone number +1 484 336 2025 (SmileCraft).

Flow docs for every role: `docs/flows/`.

## Test companies

- **Content gneration** (org `e7affc4c-f300-41e5-9eb7-1228ef443155`): owner pooja, finance "Anil" (shown as Priyam). Gmail + Razorpay (test) connected, **no WhatsApp**. Invoices MSR-1014 (email reminder card pending), MSR-1015 (card assigned to pooja).
- **Kaveri** (invoice-only), **Mehta & Co** (inbox-only, demo logins `*@mehtaco.example`), **SmileCraft** (voice), **Swarm-ai**. Demo password `agentry-demo-123`.

## Open items

| Item | Waiting on | Next step |
|---|---|---|
| Razorpay webhook (connection `fa7cb590-41c5-45ea-be9f-eefe7535c028`) | User | Run `cloudflared tunnel --no-autoupdate --url http://localhost:8801` in own Terminal; in Razorpay set `https://<tunnel>/webhooks/razorpay/fa7cb590-41c5-45ea-be9f-eefe7535c028`, events `payment.captured` + `payment_link.paid`, same secret; then set `AGENTRY_API_PUBLIC_URL`, restart API, check a bad signature gets 401. Until then: **Confirm paid** by hand |
| Production deploy (Oracle k3s, `docs/DEPLOY.md`) | User | Offered next to SwarmAI on the same VM with its own DuckDNS names; postponed |
| Cold email going live | User: accounts in `PHASE-5-COLD-EMAIL.md` §6 | Instantly account + 2 sending domains (2–3 weeks warm-up) → I add the Instantly sender and reply webhook; Google Places / Hunter / MillionVerifier keys → real lists (5.6); real postal address in Agentry's cold email settings |
| Real phone call test | Parked | US number can't be dialled from India |
| Outbound calls / SMS | User | Twilio or Plivo account (Plivo needs Indian business KYC) |
| Optional setup | User | Outlook (`AGENTRY_MICROSOFT_*`), Gmail Pub/Sub (`AGENTRY_GMAIL_PUBSUB_TOPIC`, `AGENTRY_GMAIL_PUSH_TOKEN`), WhatsApp alert template, rename "swarm-ai" → Agentry on the Google OAuth consent screen |
