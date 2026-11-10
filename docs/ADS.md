# Ads: ready-to-run campaigns

Every ad points at an audience page built for it, carries UTM tags, and the demo form passes those tags (and `gclid` / `fbclid`) to HQ inside the request's message as `[source: …]` (the demo-request API has no tracking fields, so nothing in the backend changed). Copy uses only facts from the docs; headlines are ≤ 30 characters and descriptions ≤ 90 (checked by script).

## Setup (needs you)

1. **Google Ads account** → create a conversion action *Demo request* (category: Submit lead form). Copy the tag ID (`AW-…`) and the conversion label.
2. **Google Analytics 4** (optional) → a web data stream for https://agentry.duckdns.org → the measurement ID (`G-…`). Mark `generate_lead` as a key event.
3. **Meta Business** → Events Manager → a Pixel → its ID. The site fires `PageView` and, on a demo request, `Lead`.
4. Put the IDs in `infra/.env.server` (they're baked in at build time) and redeploy the website:

```
NEXT_PUBLIC_GOOGLE_ADS_ID=AW-XXXXXXXXX
NEXT_PUBLIC_GOOGLE_ADS_LABEL=XXXXXXXXXXXX
NEXT_PUBLIC_GA_ID=G-XXXXXXXXXX
NEXT_PUBLIC_META_PIXEL_ID=XXXXXXXXXXXXXXX
NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=xxxxxxxx   # Search Console (docs/SEO.md)
```

   On the live server, put them in `infra/.env.server` (the deploy build reads it) and redeploy: they are already passed
   to the website build (`docker-compose.prod.yml` → web `args`, `infra/docker/next.Dockerfile` `ARG`).

   Nothing loads until an ID is set, so there is no tracking today. Before turning any on, add a cookie / tracking line to the privacy page.
5. **Final URL format**: `https://agentry.duckdns.org/for/<page>?utm_source=google&utm_medium=cpc&utm_campaign=<page>` (Meta: `utm_source=meta&utm_medium=paid_social`). Turn on auto-tagging in Google Ads (adds `gclid`).
6. A custom domain (e.g. agentry.in) will lift click-through and ad quality noticeably compared with a duckdns.org subdomain; worth doing before spending much.

## The free audit as a landing page (new, 2026-11-10)

`/audit` gives a visitor something in 60 seconds (does ChatGPT name you, can visitors reach you at night, website basics), and
leaving name + email for the full report creates a demo request. It usually converts better than "request a demo".
See [flows/website-try-it.md](flows/website-try-it.md).

| Ad | Final URL | Headlines (≤ 30) | Description (≤ 90) |
|---|---|---|---|
| Google Search, clinics | `/audit?service=dental%20clinic&utm_source=google&utm_medium=cpc&utm_campaign=audit-clinics` | Does ChatGPT Recommend You? · Free 60-Second Clinic Audit · See Who AI Recommends | Find out if ChatGPT names your clinic or a competitor, and what to fix. Free, no call. |
| Google Search, CA firms | `/audit?service=CA%20firm&utm_source=google&utm_medium=cpc&utm_campaign=audit-ca` | Is AI Sending Clients Elsewhere? · Free CA Firm Visibility Check | We ask ChatGPT who to hire for CA services in your city. See if it names your firm. |
| Meta, any business | `/audit?utm_source=meta&utm_medium=paid_social&utm_campaign=audit` | Ask ChatGPT for the best in your city. Does it name you? | A free 60-second check of your business on AI assistants and your website. |
| Meta, instant demo | `/try?utm_source=meta&utm_medium=paid_social&utm_campaign=try` | Meet your own AI assistant in 30 seconds | Type your website, then chat with an assistant that answers your customers from it. |

Conversions: count `audit_report_unlocked` (fires the same Lead / generate_lead / Ads conversion as a demo request) as the main one, and
`audit_start` and `instant_demo_chat` as secondary. The audit has a daily spend cap (`AGENTRY_AUDIT_DAILY_BUDGET_USD`, default $5, about 60 audits);
raise it when ads run (each audit costs about $0.08–0.15).

## Budget (suggested starting point)

| Campaign | Daily | Why |
|---|---|---|
| CA firms → `/for/ca-firms` | ₹500–800/day | Highest intent in tax season (June–September); raise then |
| Clinics → `/for/clinics` | ₹500–1,000/day (city-targeted) | Target 2–3 cities first; one city per ad group |
| Home services → `/for/home-services` | ₹400–700/day | Strong in summer (AC) and before monsoon (pest control) |
| Agencies & firms → `/for/agencies` | ₹400–700/day | Broad terms: keep phrase/exact match only |

Start with **₹2,000–3,000 a day in total** for 2–3 weeks, Search only, *Maximise conversions* once 15+ demo requests are recorded (manual CPC or *Maximise clicks* with a ₹40–80 cap before that). These are starting guesses, not benchmarks: judge by cost per demo request in HQ → Demo requests.

## Google Search: CA firms

**Final URL:** `https://agentry.duckdns.org/for/ca-firms?utm_source=google&utm_medium=cpc&utm_campaign=ca_firms`

**Keywords** (phrase `"…"` and exact `[…]` match): "ITR filing software for CA", "CA practice management software", [GST reconciliation software], "GSTR 2B reconciliation tool", "document collection for CA firms", "tax practice automation", "AIS Form 16 mismatch", "income tax notice reply software"

**Negative keywords:** free download, crack, course, jobs, salary, exam, ICAI result, login, e-filing portal, income tax refund status

**Responsive search ad 1**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| ITR Season on Autopilot | Clients get polite WhatsApp reminders until every document is in. You just review. |
| AI Agents for CA Firms | Form 16, AIS and 26AS read and compared. Mismatches flagged before you file. |
| Documents Chase Themselves | 13 agents for CA firms: filings board, ITR, GST, TDS, notices and Excel work. |
| Form 16 vs AIS, Flagged | Get a free demo built with your firm's name. No call needed. |
| Old vs New Regime, Done |  |
| GSTR-2B Reconciled Fast |  |
| Free Demo With Your Firm Name |  |
| You Check. You File. |  |

**Responsive search ad 2**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Stop Chasing Form 16 | A card for every client, each with its own checklist, and reminders that send themselves. |
| WhatsApp Reminders for CAs | Clients asking if their ITR is filed get the answer on WhatsApp, with the ack number. |
| One Board for Every Return | 143(1) and 148 notices explained in plain words with a reply drafted before the deadline. |
| "Is My ITR Filed?" Answered | Approval mode first: nothing goes to a client until you say so. |
| Built and Run for You |  |
| Live in About 7 Days |  |
| Notices Explained, Drafted |  |
| GST and TDS Checks Built In |  |

**Responsive search ad 3**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| CA Firm Pack by Agentry | Any PDF to Excel in your firm's layout. Books vs bank and debtors reconciled. |
| Tax Season Without Midnights | Zerodha, Groww and CAMS statements to STCG and LTCG with grandfathering. |
| PDF to Excel in Your Layout | Untick what you don't need or buy any agent on its own. We set it up for you. |
| Bank Statements Classified | See it working with your own firm's name before you decide. |
| Capital Gains From Broker P&L |  |
| Pick Only the Agents You Need |  |
| Try a Free Demo |  |
| Made for Indian CA Firms |  |

## Google Search: Clinics

**Final URL:** `https://agentry.duckdns.org/for/clinics?utm_source=google&utm_medium=cpc&utm_campaign=clinics`

**Keywords** (phrase `"…"` and exact `[…]` match): "AI receptionist for clinic", "clinic WhatsApp appointment booking", "dental clinic chatbot", "reduce no shows clinic", "appointment reminder WhatsApp", [virtual receptionist for doctors], "clinic front desk automation"

**Negative keywords:** jobs, receptionist job, vacancy, salary, course, training, free, hospital management software

**Responsive search ad 1**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Never Miss a Patient Call | Missed and busy calls answered from your clinic's own timings, treatments and prices. |
| AI Receptionist for Clinics | WhatsApp enquiries answered in a minute and booked straight into your diary. |
| WhatsApp Answered in 1 Min | Every appointment confirmed and reminded. Freed slots offered to your waitlist. |
| Fewer No-Shows | Get a free demo with your clinic's name. No call needed. |
| Every Slot Filled |  |
| Free Demo With Your Clinic |  |
| Live in About 7 Days |  |
| Front Desk in a Box |  |

**Responsive search ad 2**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Your Clinic, Answered 24/7 | A busy Saturday no longer means 14 missed calls. Every caller gets an answer. |
| Stop Losing Busy-Hour Calls | Happy patients asked for a Google review. Unhappy ones reach you first. |
| Appointments Booked for You | No medical advice: it answers from your own facts and hands the rest to your team. |
| Reminders That Cut No-Shows | Approval mode first. You see every draft until you trust it. |
| More Google Reviews |  |
| Built and Run for You |  |
| Patients Know It's an AI |  |
| See It With Your Clinic Name |  |

**Responsive search ad 3**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Dental Clinic AI Assistant | WhatsApp assistant, website chat, appointment concierge and reviews in one setup. |
| Skin and Physio Clinics Too | Messages come from your own WhatsApp number and email, not ours. |
| WhatsApp + Website + Calls | One portal shows every enquiry, booking and rupee next to what you pay. |
| One Inbox for Every Patient | Most clinics are live within about a week. We do the setup. |
| Pay Per Result Available |  |
| Try a Free Demo |  |
| From Your Own WhatsApp |  |
| Fuller Diary, Less Admin |  |

## Google Search: Home services

**Final URL:** `https://agentry.duckdns.org/for/home-services?utm_source=google&utm_medium=cpc&utm_campaign=home_services`

**Keywords** (phrase `"…"` and exact `[…]` match): "field service management software India", "AC repair booking software", "technician dispatch app", "service booking WhatsApp", "AMC renewal reminder software", "pest control software", [plumbing business software]

**Negative keywords:** jobs, technician job, salary, repair near me, service center, course, free app

**Responsive search ad 1**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Every Service Call, One Board | The WhatsApp assistant books the visit: service, day and address. You see it on one board. |
| Bookings From WhatsApp | Jobs go to the technician with the right skill, in that area, who isn't full today. |
| Right Technician, Every Job | Customers hear "on the way" and "done". Finished jobs become invoices that chase up. |
| Customers Told On the Way | Get a free demo with your business name. No call needed. |
| Finished Jobs Auto-Invoiced |  |
| Free Demo for Your Business |  |
| No Technician App Needed |  |
| AMC Renewals Reminded |  |

**Responsive search ad 2**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| For AC Repair and Plumbing | Technicians get each job on WhatsApp in one tap: address, problem and customer phone. |
| Pest Control and Cleaning | AMC customers reminded 30, 7 and 1 days before, with a payment link. |
| Stop Assigning Jobs by Phone | No new app to learn. The office sees every job and its status on one board. |
| Invoices Out the Same Day | Approval mode first: nothing goes to customers until you say so. |
| Built and Run for You |  |
| Live in About 7 Days |  |
| WhatsApp Booking Assistant |  |
| Try a Free Demo |  |

**Responsive search ad 3**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Home Services AI Agents | Bookings that arrive at midnight are answered and booked, not left till morning. |
| Fewer Missed Bookings | A job marked done with an amount becomes an invoice that follows up by itself. |
| Paid Faster After Every Job | Messages come from your own WhatsApp number. Customers see your name. |
| One Board for Every Visit | Most businesses are live within about a week. We do the setup. |
| From Your Own WhatsApp |  |
| Pay Per Result Available |  |
| See It With Your Name |  |
| Made for Indian Businesses |  |

## Google Search: Agencies & firms

**Final URL:** `https://agentry.duckdns.org/for/agencies?utm_source=google&utm_medium=cpc&utm_campaign=agencies`

**Keywords** (phrase `"…"` and exact `[…]` match): "AI email assistant for business", "invoice payment reminder software", "overdue invoice follow up", "content repurposing service", "AI automation agency India", [Gmail AI assistant for teams], "payment reminder WhatsApp"

**Negative keywords:** free, template, jobs, course, open source, download, excel template

**Responsive search ad 1**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Your Inbox, Sorted for You | Every email labelled in your own Gmail. Urgent ones ping you on WhatsApp. |
| Get Paid Without Chasing | A ready reply under every email that needs one, in your tone, with your real prices. |
| AI Agents for Agencies | Overdue invoices reminded on day 7, 14, 21 and 28, with a payment link. Stops when paid. |
| Urgent Emails on WhatsApp | Get a free demo with your business name. No call needed. |
| Replies Drafted in Your Tone |  |
| Free Demo, No Call Needed |  |
| Invoices Chased Politely |  |
| Built and Run for You |  |

**Responsive search ad 2**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Money In Faster | Changed bank details and lookalike domains get a red warning before anyone pays. |
| Inbox Triage in a Day | Snap a bill on WhatsApp: it's read, checked and exported to Tally. |
| Bills Straight Into Tally | One recording becomes about 30 posts for LinkedIn, Instagram and X. You approve. |
| A Month of Posts, 1 Video | Start with one agent. Add the next when it pays for itself. |
| Fraud Warnings on Emails |  |
| Approval Mode First |  |
| Try a Free Demo |  |
| Made for Indian Firms |  |

**Responsive search ad 3**

| Headlines (≤ 30) | Descriptions (≤ 90) |
|---|---|
| Get Paid Bundle | Inbox triage, invoice follow-up and bookkeeping, set up and run for you. |
| Inbox + Invoices + Bills | Works with Gmail, Outlook, WhatsApp, Sheets, Tally, Zoho, QuickBooks, Razorpay. |
| Works With Gmail and Tally | One portal shows every result next to what you pay us. |
| Razorpay Payment Links | See it with your own business name before you decide. |
| Live in About 7 Days |  |
| See Every Rupee Won Back |  |
| Pay Per Result Available |  |
| AI Agents, Done for You |  |

**Extensions for every campaign:** sitelinks to `/agents`, `/#pricing`, `/#calculator`, `/#demo`; callouts *Live in about 7 days*, *Approval mode first*, *Your own WhatsApp number*, *Pay per result available*.

## Meta (Facebook + Instagram)

One campaign, objective **Leads** (website conversions on the `Lead` event), Advantage+ placements, ₹500–800/day per ad set to start. Creative: the site's share image (`/opengraph-image`) or a 15-second screen recording of the portal; never stock photos of fake customers.

### CA firms

- **Audience:** CA firm owners and partners, India; interests: chartered accountancy, taxation, Tally; job titles: Chartered Accountant, Partner
- **Headline:** Your ITR season, on autopilot
- **Primary text:** July. Half your clients haven't sent Form 16 and the phone won't stop. Agentry's CA firm pack chases documents on WhatsApp, flags Form 16 vs AIS mismatches and keeps every return on one board. You check and file.
- **Description:** Free demo with your business name. No call needed.
- **Button:** Get quote
- **URL:** `https://agentry.duckdns.org/for/ca-firms?utm_source=meta&utm_medium=paid_social&utm_campaign=ca_firms`

### Clinics

- **Audience:** Clinic owners, dentists, dermatologists, physiotherapists in your city; interests: dentistry, clinic management
- **Headline:** Never miss a patient call again
- **Primary text:** Missed calls on a busy Saturday are patients calling the next clinic. Agentry answers calls and WhatsApp from your own timings and prices, books the diary and reminds every appointment.
- **Description:** Free demo with your business name. No call needed.
- **Button:** Get quote
- **URL:** `https://agentry.duckdns.org/for/clinics?utm_source=meta&utm_medium=paid_social&utm_campaign=clinics`

### Home services

- **Audience:** Owners of AC repair, plumbing, pest control and cleaning businesses; interests: small business, home services
- **Headline:** Every service call, on one board
- **Primary text:** Bookings on WhatsApp at midnight, technicians assigned by phone, invoices a week late? Agentry books the visit, sends it to the right technician, tells the customer and invoices the job.
- **Description:** Free demo with your business name. No call needed.
- **Button:** Get quote
- **URL:** `https://agentry.duckdns.org/for/home-services?utm_source=meta&utm_medium=paid_social&utm_campaign=home_services`

### Agencies & firms

- **Audience:** Agency founders, consultants, B2B business owners; interests: digital marketing, entrepreneurship
- **Headline:** Money in faster, inbox under control
- **Primary text:** 140 unread emails and clients who pay late. Agentry sorts your Gmail, pings you on WhatsApp for urgent ones, drafts replies in your tone and chases invoices politely until they're paid.
- **Description:** Free demo with your business name. No call needed.
- **Button:** Get quote
- **URL:** `https://agentry.duckdns.org/for/agencies?utm_source=meta&utm_medium=paid_social&utm_campaign=agencies`

## Rules for any new ad

- Only claims the product does today (see each agent's *Good to know* on its page and *Before you promise* in docs/SALES-STORIES.md). No invented customers, ratings, numbers or logos.
- Indian phone numbers for the AI receptionist need a KYC'd provider: don't promise an Indian number in ads yet.
- Every ad goes to a page about that exact problem, never the home page.
