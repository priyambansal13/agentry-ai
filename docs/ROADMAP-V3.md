# Agentry v3: the next agents (planned 2026-11-02)

## Sources

1. **What's left of [ROADMAP-V2](ROADMAP-V2.md):**
   - 8.4 topic-to-script
   - 8.5 languages
   - 8.6 engagement loop
   - 8.7 AI images
   - 10.2 Local SEO
   - 10.3 Support Desk
   - 10.4 Business Copilot
   - 11.1 Hiring
   - 11.2 Returns
   - 11.3 Stock scanner
   - 11.4 Ops dispatcher
   - 11.5 SOP / proposal drafter
2. **Ideas from earlier sessions:**
   - renewals and repeat business
   - quote writer
   - client health monitor
   - festival campaigns
   - Google Business Profile
   - ad-spend watchdog
   - mystery shopper
   - a law-firm pack
3. **Research.** MyOperator's 200+ Indian SMB deployments list six use cases with the strongest results: inbound calls, lead qualification, FAQ, **product inquiry and sales (catalogue, prices)**, **order status and support with escalation tickets**, and bookings. Agentry already covers four of them. The two in bold are the gaps.
4. **Patterns from the cloned projects:** prompt-injection guard, progress steps, usage limits.

## Wave A: build now, in this order (✅ all built 2026-11-02: [flows/agents/v3-agents.md](flows/agents/v3-agents.md))

| # | Agent | What it does | Reuses | Size |
|---|---|---|---|---|
| A1 ✅ | **Prompt-injection guard** (platform) | Everything a stranger types (chat, WhatsApp, Telegram, email, reviews) is checked for "ignore your instructions / reveal your prompt / give me a discount" attacks before an agent acts on it. Suspicious messages go to a person; nothing is sent automatically. | the chat agent, inbox triage, governance | S |
| A2 ✅ | **Support desk** (10.3) | Customer issues from WhatsApp, chat and email become **tickets** with category, priority, SLA, assignee and status. "Where's my order?" is answered from an uploaded order sheet. SLA breaches alert the owner. Customers rate the answer when a ticket closes. | conversations, notifications, card routing | M |
| A3 ✅ | **Catalogue & quote agent** | Answers product questions from the business's catalogue (CSV / Excel upload): price, stock, sizes. Builds a **quote** (items, GST, total, validity) as a PDF the customer gets on WhatsApp or email, follows it up, and marks it won or lost. | knowledge, outbound, sequences | M |
| A4 ✅ | **Renewals & repeat business** | Tracks renewal dates (AMC, insurance, memberships, subscriptions, service due). Reminds customers 30, 7 and 1 days before, with a payment link when there's an amount. Wins back lapsed customers and sends birthday wishes. | outbound, invoices (payment links), campaigns | M |
| A5 ✅ | **Hiring assistant** (11.1) | A job post, then CVs from upload, email or WhatsApp are read and scored against the job with reasons. Builds a shortlist, books interviews on the calendar, and sends polite regrets. | Document AI, booking, outbound | M |
| A6 ✅ | **Topic → script** (8.4) | No recording? Give a topic and get a timed 30–60 s script (hook, beats, on-screen text, call to action) to film on a phone, in the business's voice. 4 a week on a schedule. It can also go straight to the AI video studio. | content brand and voice, video studio | S |
| A7 ✅ | **Client health monitor** (HQ, for Agentry) | For every client: usage trend, unapproved cards, failed connections, last login, billing state. Gives a health score with reasons and a weekly "at risk" list for the agency. | metrics, audit, billing | S |

## Wave B: next (✅ all built 2026-11-02: [flows/agents/v3-agents.md](flows/agents/v3-agents.md))

| Agent | Why it waits |
|---|---|
| Local SEO audit + articles (10.2) | Big; ranking checks need a search API key |
| Engagement loop (8.6) | Reads views and likes from YouTube, LinkedIn and Instagram once those connections are used for real |
| Stock shelf scanner (11.3) | Vision reading like the bookkeeping agent; for shops and cafés |
| Festival & seasonal campaigns | The Indian calendar plus offers, posts and WhatsApp broadcasts (needs approved broadcast templates) |
| SOP & proposal drafter (11.5) | Builds on the proposal builder |

## Wave C: needs outside access or a decision (✅ copilot + dispatcher built 2026-11-02: [flows/agents/v3-agents.md](flows/agents/v3-agents.md#wave-c-2026-11-02))

| Agent | Needs |
|---|---|
| Google Business Profile manager | Google Business Profile API approval |
| Returns & refunds (11.2) | A Shopify / WooCommerce connection |
| Ops dispatcher (11.4) ✅ | Large; for home-services clients |
| Business copilot (10.4) ✅ | Large; the premium tier |
| Hindi / regional languages (8.5) | A Sarvam key |
| Ad-spend watchdog | Meta / Google Ads API access |
| Law-firm pack | eCourts data access |
| Mystery shopper | A test phone line |

Each agent follows the usual pattern:
- feature + template + settings;
- data and migration;
- API with role checks;
- portal page;
- tests (with mocks for outside services);
- a real-model check;
- a flow doc;
- a commit.
