# Agentry: brand, UI and landing page

> Agentry is an **agency-operated SaaS**: you (Agentry) set up and run AI agents for clients, and clients log in to a polished portal to watch them work, approve things and see results. Both the marketing site and the app need to look excellent, because the UI *is* the sales pitch.

## 1. Surfaces

| Surface | Who | Purpose | App |
|---|---|---|---|
| **Marketing site** (agentry.…) | Prospects | Explain, impress, capture: "get a demo built with your business name" | `apps/web` (Next.js, static/SSG for SEO) |
| **Client portal** | Client owners & staff | Results first: what the agents did, money won back, items to approve, conversations | `apps/dashboard` |
| **Agentry HQ** (operator console) | You | Clients, onboarding, Demo Studio, industry packs, prompts and tests, margins | `apps/dashboard` (role-gated) |
| **Demo pages** | One prospect | Their personalised demo (chat on a mock of their homepage, demo phone line, sample inbox) | `apps/web/demo/[slug]` |
| **Chat widget** | Client's website visitors | The website chat agent | `apps/widget` |

## 2. Brand direction

- **Name:** Agentry (agents + foundry: a workshop that builds and runs AI agents for you).
- **Tagline options:** *"Your AI workforce, done for you."* · *"AI agents that do the boring work. You keep the results."* · *"Missed call = missed customer. Not anymore."*
- **Visual signature:** take the reference's look (**hand-drawn sketch diagrams + lime highlighter**) and make it the brand.
  - Every agent is explained with an animated sketch flow (rough.js-style strokes that draw themselves on scroll).
  - It's friendly, instantly understandable, and stands out from the usual purple-gradient AI sites.
- **Palette (tokens, light and dark):**

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ink` | #111111 | #F4F4F0 | Text, sketch strokes |
| `--paper` | #FAFAF7 | #0E0F0C | Background |
| `--lime` | #C9F24B | #C9F24B | Highlighter accent, primary CTA, "result" moments |
| `--muted` | #6B6B66 | #9A9A92 | Secondary text |
| `--card` | #FFFFFF | #171812 | Surfaces |
| `--success` / `--warning` / `--danger` | standard, AA-contrast checked | | Status |

- **Type:** a characterful display font for headings (e.g. *Space Grotesk* or *Bricolage Grotesque*), *Inter* for UI text, and a hand-written font (e.g. *Caveat*) only for sketch annotations.
- **Motion:** purposeful only (drawing strokes, numbers counting up, live activity ticking in). Respect `prefers-reduced-motion`.

## 3. Landing page

```
┌───────────────────────────────────────────────────────────────┐
│ HERO   "Your AI workforce, done for you."                     │
│        AI agents that answer calls, chase invoices and fill   │
│        your calendar while you sleep.                         │
│        [ your-website.com          ] [Build my free demo →]   │  ← triggers Demo Studio
│        sketch animation: lead → agent → calendar fills lime   │
├───────────────────────────────────────────────────────────────┤
│ PROBLEM  "100 leads → 20 missed → $2,000/month lost"          │  ← from "What is it worth?"
├───────────────────────────────────────────────────────────────┤
│ THE AGENTS  9 cards, each with its sketch flow + outcome      │
│   Receptionist · Speed-to-lead · Website chat · Reactivation  │
│   Cold email · Inbox triage · Invoice follow-up · Content     │
│   + The Boring Machine (all lead agents → one calendar)       │
├───────────────────────────────────────────────────────────────┤
│ FOR YOUR BUSINESS  tabs: Agencies & firms | Clinics &         │
│   appointments | Home services → each tab shows its ladder    │
├───────────────────────────────────────────────────────────────┤
│ HOW IT WORKS  1 Demo with your name → 2 Live in 7 days →      │
│               3 You approve, agents work → 4 Pay for results  │
├───────────────────────────────────────────────────────────────┤
│ ROI CALCULATOR  sliders: leads/mo, % missed, close rate,      │
│   customer value → money lost/mo → suggested plan             │
├───────────────────────────────────────────────────────────────┤
│ PRICING MODELS  Retainer | Pay per result | Start small       │
├───────────────────────────────────────────────────────────────┤
│ LIVE PROOF  "Call our receptionist now: +91 …" · chat widget  │
│ FAQ · Footer                                                  │
└───────────────────────────────────────────────────────────────┘
```

- **Dogfooding:** the Agentry chat agent (bottom right) answers questions and books discovery calls; a demo phone number lets visitors talk to the receptionist live.
- **Pages:**
  - `/` (home)
  - `/for/agencies`, `/for/clinics`, `/for/home-services`: niche pages, each led by its entry agent
  - `/agents/<agent>`: one page per automation, with the sketch flow, a demo and outcomes
  - `/pricing`, `/roi-calculator`, `/demo/[slug]`, `/case-studies` (MDX), `/blog` (MDX)
- **Targets:** Lighthouse ≥ 95, mobile-first, structured data for SEO, English first with Hindi pages later.

## 4. Client portal

> Functional spec (logins, roles, onboarding, every page and metric): [CLIENT-PORTAL.md](CLIENT-PORTAL.md). This section covers the look and feel.

Results first, then work queue, then settings. Owners mostly check it **on their phone**, so it's mobile-first and installable as an app (PWA) with push notifications.

| Screen | Highlights |
|---|---|
| **Home** | Big numbers for this month: appointments booked, ₹ won back, calls answered, **ROI ×** vs your fee. **Live activity feed**: "Asha booked Meera, Sat 11:00", "Invoice SDA-2042 paid ₹18,500" |
| **Needs you** | Swipe-style approval cards (approve / edit / reject), urgent escalations, disputes |
| **Conversations** | Unified timeline per contact: email, chat, WhatsApp, calls with **audio player + live transcript + AI summary** |
| **Agents** | One card per agent: status toggle, today's stats, persona, "talk to it" test button (chat or call) |
| **Calendar** | Booked appointments by source (which agent booked it), no-shows, fill rate |
| **Reports** | Funnels per agent, monthly results report (PDF), opportunity report |
| **Billing** | Plan, usage, results statement with evidence links |

## 5. Agentry HQ (operator console)

Client list with health, margin and alerts · onboarding checklist per client · **Demo Studio** · industry pack editor · prompt and persona editor with **test-set runs before publishing** · live calls monitor · cost and margin dashboards · audited "view as client".

## 6. UI stack

| Need | Choice |
|---|---|
| Framework | Next.js 15 (App Router) + TypeScript, `apps/web` (marketing, SSG) and `apps/dashboard` (app) |
| Styling | Tailwind CSS v4 with design tokens above; dark mode from day one |
| Components | **shadcn/ui** (Radix) for the app; hand-built sections for marketing |
| Motion | **Motion** (Framer Motion) + **rough.js** for sketch diagrams |
| Charts | Recharts (follows the dataviz guidelines: same palette and theming in light and dark) |
| Icons | Lucide |
| Content | MDX for case studies and blog |
| Realtime | Server-Sent Events for the live activity feed and live call transcripts |
| Shared | `packages/ui` (tokens, components) used by web, dashboard and widget |

## 7. Delivery
- **Phase 0:** design tokens + `packages/ui` + **landing page v1** (hero, agents, niches, ROI calculator, demo-request form). It can start bringing in prospects before the product is finished.
- **Phase 1:** client portal shell (Home, Needs you, Conversations) + the hero's "Build my free demo" wired to Demo Studio.
- **Phase 3:** full portal polish + Agentry HQ, ahead of the first paying clients.
