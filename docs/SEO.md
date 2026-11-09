# SEO: the public website (agentry.duckdns.org)

Code: `apps/web`. One data file drives the agent and industry pages, the sitemap and the structured data:
`apps/web/src/lib/catalog.ts`. Ads: [ADS.md](ADS.md).

## Audit (before, 2026-11-09)

| Area | Found |
|---|---|
| Pages | One page (`/`) plus privacy and terms. Nothing for search to rank on except the home page |
| Titles and descriptions | One title and description for the whole site; legal pages repeated "· Agentry" by hand |
| Open Graph / Twitter | None: shared links had no image or summary |
| Canonical URLs | None |
| sitemap.xml / robots.txt | Missing (404) |
| Structured data | None |
| Agents shown | 8 of 38, with two flows that no longer matched the product (speed-to-lead "AI voice call", cold email "Google Maps list") |
| Audience | US example ($2,000/month lost) on an India-first site |
| Internal links | Footer had only Privacy and Terms; every nav link was a same-page anchor |
| Headings | One `h1`; sections used `h2`. Fine |
| Images | None (all SVG with labels), so no alt-text gaps |
| Fonts | `next/font` (self-hosted) but no `display: swap` |
| Private pages | `/demo/*`, `/proposal/*`, `/unsubscribe/*` already `noindex`, but not blocked in robots |
| Mobile | Fine at 390 px |

## What was fixed

- **Metadata on every page**: unique title (template `%s · Agentry`), description, keywords, canonical, Open Graph and
  Twitter large-image cards (`pageMeta()` in `catalog.ts`; a page's own `openGraph` replaces the root one, so the helper
  rebuilds the full set). `metadataBase` = `NEXT_PUBLIC_WEB_URL`. Locale `en_IN`, `<html lang="en-IN">`.
- **Share image**: `app/opengraph-image.tsx` draws the brand card (ink on paper, lime highlighter) for every page.
- **`/sitemap.xml`**: home, `/agents`, 4 industry pages, 38 agent pages, legal pages (46 URLs).
- **`/robots.txt`**: allows everything, blocks the private per-prospect pages, points to the sitemap.
- **Structured data (JSON-LD)**: Organization + WebSite on every page; Service with an OfferCatalog of all 38 agents
  and FAQPage on the home page; ItemList on `/agents`; Service + BreadcrumbList on each agent page; FAQPage +
  BreadcrumbList on each industry page.
- **New pages to rank on** (all static, built at deploy):
  - `/agents`: all 38 agents in 5 groups, each linking to its own page.
  - `/agents/<slug>` × 38: what it does, honest limits ("Good to know"), related agents, the industries it's set up for.
  - `/for/ca-firms`, `/for/clinics`, `/for/home-services`, `/for/agencies`: pain → example of what changes → the
    agents → questions → demo form (with the business type pre-filled). These are also the ad landing pages.
- **Home page**: hero with the agent count and four proof points, a ticker of every agent, the clinic example in ₹,
  all 38 agents grouped, industry cards, the eight favourite flows (copy corrected), "In every plan", packs under pricing.
- **Internal links**: header (Agents, CA firms, Clinics, Industries, Pricing), a full footer (industries, agent
  groups, company), breadcrumbs, related agents.
- **Speed and accessibility**: fonts `display: swap`; entrance motion moves only (the headline is never invisible, which
  protects LCP) and is off with `prefers-reduced-motion`; skip-to-content link.
- **Ads**: see [ADS.md](ADS.md) (UTM / gclid / fbclid passed with demo requests; GA4, Google Ads and Meta Pixel load
  only when their IDs are set).

## Target keywords per page

| Page | Main searches |
|---|---|
| `/` | AI agents for business India, AI automation agency India, WhatsApp AI assistant, AI receptionist |
| `/for/ca-firms` | ITR filing automation for CA firms, CA practice management software India, GST reconciliation software, document collection for CA |
| `/for/clinics` | AI receptionist for clinics India, WhatsApp appointment booking for clinics, dental clinic chatbot, reduce no-shows clinic |
| `/for/home-services` | field service management India, AC repair booking software, technician dispatch app, home services WhatsApp booking |
| `/for/agencies` | AI email assistant for agencies, invoice follow up automation India, content repurposing service |
| `/agents/<slug>` | 2–3 each, in `keywords` in `catalog.ts` (e.g. *GSTR 2B reconciliation tool*, *AI resume screening India*, *Diwali marketing ideas small business*) |

## Next steps (need you)

1. **Google Search Console**: add the property `https://agentry.duckdns.org`, choose *HTML tag*, put the code in
   `NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION` (infra/.env.server; also add it as a web build arg, see ADS.md step 4), redeploy, verify, then **submit
   `https://agentry.duckdns.org/sitemap.xml`**. Do the same in Bing Webmaster Tools (it can import from Search Console).
2. **A real domain** (e.g. agentry.in or getagentry.com). A duckdns.org subdomain ranks and converts worse; when it
   changes, set `NEXT_PUBLIC_WEB_URL` and every canonical, sitemap and share URL follows.
3. **Google Business Profile** for Agentry itself (category: Software company / Marketing agency), linking to the site.
4. **Content**: one article a month per audience (e.g. "ITR document checklist for clients, AY 2026-27"; "How clinics
   cut no-shows with WhatsApp reminders"). The Local SEO agent can draft them from Agentry's own facts.
5. **Proof**: once real clients agree, add their results (with permission) to the industry pages. None are shown today
   on purpose.
6. **Page weight**: the hand-drawn sketches (Boring Machine and the eight flows) are about 180 KB of SVG paths on the home
   page. If PageSpeed flags it, draw them with `disableMultiStroke` in `components/sketch.tsx` (roughly halves it) or
   load the eight flows lazily.
