# Plan: "try it now" on the website + AI search visibility agent (2026-11-10)

> **Status: ✅ steps 1–6 built 2026-11-10** (not yet deployed). How it works now: [flows/agents/ai-visibility.md](flows/agents/ai-visibility.md),
> [flows/website-try-it.md](flows/website-try-it.md). Differences from this plan: the instant demo is a 24-hour preview answering from
> the crawled pages (visitors can't create portal accounts, so no Demo Studio org); playgrounds are "try it" boxes plus the
> invoice-reminder preview (no sample-clinic chat or content samples yet).

Two things from [MARKET-2026.md](MARKET-2026.md):
- **A. Something a visitor can try on the website straight away.** Today they can only request a demo and wait.
- **B. A monthly AI visibility check.** Does ChatGPT / Gemini / Perplexity name the business when customers ask, compared with
  competitors, plus the fixes.

They share one engine (asking AI assistants the questions customers ask and reading who gets named), so B's engine is built
first and A's audit uses a small version of it.

## What we already have to reuse

| Piece | Where | Reused for |
|---|---|---|
| Safe crawler (blocks private addresses) | `knowledge.crawl`, `_check_public` | reading the visitor's website |
| Website checks (titles, schema, phone, Maps, WhatsApp, HTTPS, sitemap, speed, broken links) | `automations/local_seo.issues` | the audit's "website" section |
| Name and brand from a website | `demo_studio.business_name`, `brand` | audit header, instant demo |
| Demo builder (crawl 8 pages → knowledge → chat; expires in 14 days) | `demo_studio.build_demo`, `/public/demos/{slug}`, `apps/web/demo/[slug]` | instant demo |
| Public chat without login (rate-limited per IP) | `api/widget.py` | instant demo chat, playgrounds |
| Demo request → alert, confirmation, lead, follow-ups | `public.create_demo_request`, `worker/sales_jobs.py`, `sales.py` | every audit becomes a lead in Agentry's own account |
| Competitors per business | `watchers.py`, `app.watchers` | the competitor list for B |
| SEO article writer (only from the business's own facts) | `local_seo.write_article` | B's "write the answer page" fix |
| Model gateway with cost per call | `llm/gateway.complete` (passes `tools=` through) | the AI checks |

**Missing:** no model calls with web search yet, no captcha (only per-IP limits held in memory), no Google rating (Reviews is still
on sample data, and there is no Places key).

---

## B. AI search visibility agent

### What the owner sees (portal → AI visibility)
- **Score this month:** "Named in 6 of 15 questions (40%), up from 27%". Shown for each assistant: ChatGPT, Gemini, Perplexity.
- **You vs competitors:** share of mentions for each competitor, as a bar chart and a 6-month trend.
- **Each question:** "best dentist in Indiranagar for kids" → who was named, in what order, whether you were named, and the
  sentence about you.
- **Where the AI got its answer:** the sites it cited most (e.g. Practo, Justdial, Google Maps, a news article). Those are the places
  to be listed on.
- **Fixes**, each as a card in Needs you to approve:
  1. Website: add LocalBusiness + FAQ schema, an FAQ page answering the exact questions, `llms.txt`, and consistent name,
     address and phone. Drafted from the knowledge base; the owner approves, and we send the code/page to their web person
     or publish it if we run the site.
  2. Listings: "You are missing on Practo / Justdial, which the assistants cite 9 times". A checklist with links.
  3. Reviews: when competitors are named "for their reviews", the Reviews agent asks happy customers for reviews.
  4. Content: one article per question where you're missing, using the existing writer (from your own facts only).

### How it works
1. **Setup (once, editable):** business name and other names, website, city and area, services, competitors (taken from Competitor watch).
   The agent suggests 10–20 customer questions from the knowledge base ("best X in Y", "X near Y open Sunday", "X in Y price");
   the owner can edit them.
2. **Monthly run (1st of the month, plus "Check now" up to twice a month):** each question goes to each assistant through its API
   **with web search on**:
   - OpenAI with its web search tool;
   - Gemini with Google Search grounding;
   - Perplexity Sonar (optional key).

   Each question is asked **3 times**, because answers vary.
3. **Reading the answers:** a cheap model pulls out, as JSON, the businesses named, their order, the cited URLs, and the
   sentence about each one. We match the client and competitors by name, other names and domain.
4. **Scores:** how often the business is named, its average position, share of voice compared with competitors, and the top cited
   sources. All are saved so the trend shows.
5. **Fixes** are created only for real gaps (e.g. no FAQ schema, missing from a site cited 5+ times).
6. **Monthly results email:** the score and trend are added to the existing results email.

### Honest limits (shown in the portal)
- API answers come close to what people see in the apps, but they are not identical. Results depend on location and on the
  person asking, so this is an **estimate measured the same way every month**, not a guarantee.
- We can't make an assistant name you. The fixes raise the chances, and the trend shows whether they worked.

### Cost and price
- 15 questions × 3 assistants × 3 repeats = 135 searches + extraction ≈ **$1.5–4 per business per month**.
- Sell it as an add-on to Local SEO, or on its own at about **₹4,999–9,999/month** (agencies charge more). The first report is free:
  it's the sales hook.

### Build pieces
- Gateway: a new tier `search` (OpenAI web search / Gemini grounding / Perplexity), with mock answers in tests.
- Module `automations/ai_visibility/`: questions, run, extract, score, fixes; registered with its `FEATURES` entry (page
  `ai-visibility`).
- Migration: `ai_vis_queries`, `ai_vis_runs`, `ai_vis_answers` (named businesses, position, cited URLs), all with row-level security.
- API `api/routes/ai_visibility.py`: get/edit questions, runs, check now (Editor), and fixes → approvals.
- Cron on the 1st (as `seo_monthly`), plus a cap of 2 manual runs a month.
- Portal page, nav item, results email section; tests and flow doc; role matrix test picks it up automatically.

---

## A. What a visitor can try on the website

Three things, in this order.

### A1. Free "Is your business losing customers?" audit (`/audit`), the main one
The visitor types their **website, city and main service** (e.g. "dental clinic"). In about 60 seconds:

| Check | How | Example result |
|---|---|---|
| Do AI assistants name you? | small version of B: 5 questions, ChatGPT + Gemini, once each | "Named in 1 of 10 answers. Named instead: SmileCare, Dr. Rao's" |
| Can customers reach you after hours? | crawl: chat widget, WhatsApp link, online booking, phone shown | "No chat or WhatsApp on your site: night-time visitors can't ask anything" |
| Website basics for Google | `local_seo.issues` | "No LocalBusiness schema, no sitemap, home page takes 4.1 s" |
| Money at risk | the existing ROI calculator's numbers + what we found | "≈ ₹60,000–90,000 a month lost to unanswered visitors" |

- **Shown at once:** an overall score out of 100, the 3 biggest problems, and the competitors the AI named.
- **Full report** (every question and answer, every website fix, what to do first) is sent by email when they enter name, email and
  phone. That becomes a demo request in HQ with the report attached, and the normal follow-ups start.
- **Next button:** "See your own AI assistant answer your customers →" goes to A2 with the URL filled in.
- **Shareable result page** `/audit/r/{id}` (noindex, expires in 30 days), so the owner can send it to a partner.
- **Ads and SEO:** this is the landing page for ads ("Does ChatGPT recommend your clinic? Free check in 60 s"), and the
  industry pages link to it.

### A2. Instant demo: your own AI assistant, trained on your website
Today only Agentry staff can build a demo. Self-serve version:
- The visitor enters their website → we crawl 5 pages (not 8) → a **24-hour** demo opens at `/demo/{slug}` with chat on their own
  content, plus "Book a call to switch it on".
- Uses `build_demo` with a light mode: no sample inbox, kind `instant`, expires in 24 hours, deleted by a nightly cleanup.
- Every instant demo shows up in HQ → Demo requests, so you can see who tried it.

### A3. Playgrounds on agent pages (nothing to type but a click)
Small things on `/agents/[slug]`, using sample businesses, no crawl:
- **Website chat / WhatsApp assistant:** chat with SmileCraft Dental (a sample client) in a phone frame. Uses the widget API.
- **Invoice follow-up:** enter an amount and days overdue → see the WhatsApp reminders for days 7/14/21/28 (and, later, the MSME 45-day
  interest).
- **Content repurposing:** pick a sample podcast → see the 10 posts and quote cards it made (pre-made, no cost).
- The voice receptionist test call is left out for now (costly per minute, needs LiveKit in public).

### Abuse and cost controls (needed before going public)
- **Captcha:** Cloudflare Turnstile (free; needs a site key from you). Without it, we only use the per-IP limits.
- **Limits:**
  - 3 audits and 2 instant demos per IP per day;
  - the same website can't be re-audited for 24 hours (the cached report is shown instead);
  - a **global daily budget** (e.g. $5/day). When it's reached: "We're busy, we'll email your report within a day", and the audit is
    queued.
- **Rate limiter moved to Postgres** (today it's in memory per process).
- Only public websites are crawled (the crawler already blocks private addresses), there's a page cap and a timeout, and the AI only
  reads public pages.
- **Cost per audit:** about 10 searches + extraction ≈ **$0.05–0.15**. 100 audits a day ≈ $5–15.
- **Privacy:** the audit stores the URL, city and service, plus the contact details only if they ask for the full report. Add one
  line to the privacy page.

### Website changes
- Hero: a second button, "Free 60-second audit" (next to "Build my free demo").
- Each industry page gets a short audit form at the top, with the service filled in.
- `/audit` in the sitemap; an ads section in `docs/ADS.md` pointing campaigns at `/audit?utm_…`.

---

## Build order

| Step | What | Depends on | Size |
|---|---|---|---|
| 1 | `search` tier in the gateway + extraction + scoring (with mocks and tests) | an OpenAI key (have); Gemini key optional | M |
| 2 | **B** AI visibility agent: tables, API, monthly run, fixes, portal page, email | 1 | L |
| 3 | **A1** audit: public API (queue, cache, limits, budget), `/audit` page, result page, email report, HQ lead | 1; Turnstile key for public launch | L |
| 4 | **A2** instant demo (light `build_demo`, 24 h, cleanup) | 3's limits | M |
| 5 | **A3** playgrounds on agent pages | none | S–M |
| 6 | Docs (flows, SEO, ADS), role matrix, crawl, deploy | all | S |

Steps 1–3 deliver both things you asked for. Steps 4–5 make the site more interactive.

## Needed from you
1. **Cloudflare Turnstile site key + secret** (free at dash.cloudflare.com → Turnstile; add `agentry.duckdns.org`). Needed before
   the audit is public; I can build and test without it.
2. **Daily budget** for public audits (I suggest $5/day to start).
3. **Optional:** a Perplexity API key (adds a third assistant); a Google Places API key (adds the Google rating and review count to the
   audit; Google gives monthly free credit).
4. Confirm the **price** for the AI visibility agent (suggested ₹4,999–9,999/month, or included in Local SEO).

## Sources
See [MARKET-2026.md](MARKET-2026.md#sources). OpenAI web search and Gemini Google Search grounding are standard API features; to be
checked against LiteLLM's current support while building step 1.
