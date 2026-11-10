# Market check and what to add next (2026-11-10)

What is selling in AI agents for small businesses (India first), where Agentry already stands, and what we can add that is
both unique and effective. Sources are at the end.

## What the market looks like

| What | Who / numbers | What it means for us |
|---|---|---|
| WhatsApp tools (self-serve) | Wati from $39–49/mo, AiSensy from ₹1,500/mo, Interakt ₹3,499/quarter + ~₹10,000/mo for AI | Cheap tools for broadcasts and simple bots. The business still has to set them up and run them. We don't compete on price; we compete on "done for you, measured in money". |
| WhatsApp AI built by agencies | ₹15,000–60,000 setup + ₹3,000–25,000/mo; agents that *take actions* (book, refund, payment link) quoted at ₹10–25 lakh to build | Our agents already take actions (booking, payment links, reminders). That is the expensive tier for others and standard for us. Say so on the site. |
| Voice agents in India | ₹4–9 per minute with telephony; Bolna ~200,000 calls/day in 10+ Indian languages; Hindi/Tamil/Telugu with code-switching now works | English-only voice fails in most Indian businesses. Our receptionist needs Indian languages (Sarvam) before go-live. |
| What agencies sell best in 2026 | Voice agents for **missed calls** and after-hours, speed-to-lead, support automation, and **GEO/AEO (being recommended by ChatGPT/Gemini)**; sold with demos, not promises | We have speed-to-lead, support and demos. Missing: missed-call recovery and AI search visibility. |
| What buyers want | Half of SMBs have seen AI projects fail; buyers want proof | Our billing already records outcomes with evidence (recovered ₹, bookings). Lead with it. |
| Indian MSME pain | ₹8.1 lakh crore of delayed payments (RBI); GST is due on invoices not yet paid; 1,400+ compliance tasks a year | Cash collection is the #1 pain. Invoice follow-up is our strongest wedge; make it stronger (see 2). |
| Meta WhatsApp rates (from 1 Oct 2026) | Utility and service messages to Indian numbers ₹0.115 each | Reminders and replies are cheap; keep using utility templates. |

**Where we are already ahead:** 38 agents in one portal with roles, outcome-based billing, Demo Studio (a live demo built from
the prospect's own website), the 13-agent CA pack, and real actions instead of FAQ bots.

**Where we are behind:** no Indian languages, the voice receptionist isn't live on a phone number, no missed-call recovery, no
answer to "does ChatGPT recommend my business?", and nothing a stranger can try on the website without talking to us.

## What to add: ranked by effect ÷ effort

### 1. Missed-call recovery (build first; no new account needed for the test version)
Indian customers call; when nobody picks up, the lead is gone. Most cloud phone providers (Exotel, MyOperator, Knowlarity) can call a
webhook on every missed call.
- Missed call → WhatsApp within 30 seconds: "Sorry we missed you. Want to book / get a price / a call back?" → the WhatsApp
  assistant takes over (booking, quote, callback card).
- Daily count: missed calls, recovered, bookings made, ₹ value. Bill per recovered booking (fits our pricing).
- **Why it works:** easy to explain in one sentence, measurable in money in the first week, and it's the cheapest step before a full voice
  receptionist. Clinics, home services and coaching all have this problem.
- **Needs:** a cloud phone number with a missed-call webhook for live use; we can build and test with a fake webhook now.

### 2. "Get paid under the MSME law" (invoice follow-up, India upgrade)
Under the MSMED Act, a buyer must pay a registered MSME (Udyam) within 45 days, or owe interest at 3× the RBI bank rate. Disputes go to
MSME Samadhaan. Almost no tool uses this.
- Invoice follow-up knows the client's Udyam number and each buyer's due date. After day 45 it calculates the legal interest owed and
  offers a polite reminder that mentions it.
- One click drafts the MSME Samadhaan application with the invoice facts (the owner reviews and files it themselves).
- A cash view: money owed to you, GST already paid on unpaid invoices, and what is coming in the next 30 days.
- **Why it works:** it addresses the biggest MSME pain, with real legal leverage. It's unique and fits our "% of recovered money" price.
- **Needs:** nothing outside; legal text to be checked by a CA (we have CA firm clients).

### 3. AI search visibility: "Does ChatGPT recommend you?" (extend Local SEO)
Customers now ask ChatGPT, Gemini and Perplexity for "best dentist in Indiranagar". Most local businesses are never named.
- Monthly check: ask the AI engines 10–20 questions a customer would ask for that business and city, and record who gets named.
  Show the score against competitors (we already have Competitor watch).
- Fixes it can do itself: FAQ and schema on the website, answers built from the knowledge base, and review requests (we have Reviews).
- **Why it works:** it's a new fear owners already have, agencies sell it on its own at high prices, and the report is a great sales
  opener.
- **Needs:** API keys for the engines we check (OpenAI and Gemini we have; Perplexity optional).

### 4. Free self-serve audit on the website (traffic magnet for SEO and ads)
Today a visitor can only "request a demo". Give them something instantly:
- Enter your website → in 60 seconds: does your site answer questions after hours (we chat with it), are you named by ChatGPT
  for your service in your city (item 3), your Google rating and review replies, and an estimate of money lost per month.
- The email arrives with the full report, plus "want us to fix it?" → Demo Studio builds their live demo.
- **Why it works:** it gives ads and SEO a page to send people to, it collects leads at scale, and it reuses Demo Studio and
  the crawler we already have.
- **Needs:** nothing outside; rate limiting and a captcha.

### 5. Hindi and other Indian languages (already planned; this raises its priority)
Chat and WhatsApp in Hindi/Hinglish work today with the current models. Voice needs Sarvam (or similar) for good Indian
speech. Without it the receptionist can't sell outside English-speaking clinics.
- **Needs:** a Sarvam API key.

### 6. Click-to-WhatsApp ads → sale tracking
Indian SMBs run Meta ads that open WhatsApp. Nobody tells them which ad produced a paying customer.
- Read the ad referral on the first WhatsApp message, tag the lead, and follow it to a booking or payment. Report ₹ earned per ad.
- Later: the Ad-spend watchdog pauses ads that bring chats but no sales.
- **Needs:** works with the WhatsApp Cloud API we have; the ad stats need Meta Ads API access.

### 7. Owner on WhatsApp (copilot by voice note)
The owner sends a WhatsApp voice note in Hindi or English: "How much is overdue? Remind the top 3." The Business copilot answers and
asks before acting. Busy owners live in WhatsApp, not in portals.
- **Needs:** WhatsApp number (have), speech-to-text (have for English; Sarvam for Hindi).

### Worth watching, not now
- **ONDC seller agent** (catalogue + orders): 5 lakh+ sellers, but order volumes are still low for most SMBs.
- **TReDS** (selling invoices for early cash): useful for B2B suppliers to big buyers; needs a partner platform.

## Positioning changes (website and ads)
- Say it plainly: "Others sell you a chatbot. We run agents that book, collect and follow up, and we bill on results."
- Put proof on the site: one real (or pilot) number per industry page, e.g. "₹2.4 L overdue recovered in 30 days".
- Lead every industry page with the missed-call and payment pains; those are what owners search and click on.

## Suggested order
1. Missed-call recovery (test version now; live with a phone number).
2. MSME 45-day law in invoice follow-up + cash view.
3. Free website audit page (+ AI visibility check inside it).
4. AI search visibility as a monthly agent.
5. Indian languages, once you have a Sarvam key.
6. Click-to-WhatsApp ad tracking.
7. Owner copilot on WhatsApp.

## Sources
- [Best AI chat agents in India 2026 (MyOperator)](https://myoperator.com/blog/best-ai-chat-agents-india-2026)
- [Best AI agents for WhatsApp 2026 (Rework)](https://resources.rework.com/tools/ai-agents/best-ai-agents-for-whatsapp-2026)
- [WhatsApp AI agent: costs, build vs buy (Unico Connect)](https://unicoconnect.com/blogs/whatsapp-ai-agents-for-business)
- [WhatsApp AI agent pricing for Indian MSMEs](https://sktiwari.com/whatsapp-ai-agent-pricing-india-2026)
- [WhatsApp chatbot pricing India, Meta rates](https://www.mnbresearch.com/whatsapp-chatbot-pricing-india)
- [Top voice AI agents in India 2026 (MyOperator)](https://myoperator.com/blog/top-10-voice-ai-agents-india-2026)
- [AI voice agents in India: 2026 guide](https://rapidxai.com/blog/ai-voice-agents-india-guide/)
- [Voice AI for MSMEs in India](https://caller.digital/blog/voice-ai-small-business-msme-india-2026)
- [State of AI automation agencies 2026 (Ciela)](https://ciela.ai/blogs/state-of-ai-automation-agencies-2026)
- [Is the AI automation agency market saturated? (Ciela)](https://ciela.ai/blogs/is-ai-automation-agency-saturated-2026)
- [AEO and GEO for SMBs, 2026 playbook](https://www.3l3c.ai/us/blog/ai-marketing-tools-for-small-business/aeo-geo-2026)
- [How AI search engines recommend local businesses](https://voxelphase-com.pages.dev/blog/how-ai-search-engines-recommend-local-businesses)
- [Union Budget 2026: MSMEs ask for faster payments (YourStory)](https://yourstory.com/smbstory/union-budget-2026-msmes-expectations)
- [MSMEs in a tax trap: GST and delayed payments (Deccan Herald)](https://www.deccanherald.com/opinion/msmes-in-a-tax-trap-gst-rules-delayed-payments-squeeze-indias-small-firms-hard-4064355)
- [Delayed payments to MSMEs (Telangana Today)](https://telanganatoday.com/indian-msmes-face-mounting-delayed-payments-recordent-report-reveals)
