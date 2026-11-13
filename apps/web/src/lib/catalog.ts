/**
 * Every agent, grouped as in the README, plus the audience pages used by ads. One source for the home page, /agents,
 * /agents/[slug], /for/[slug], the sitemap and the JSON-LD. Facts come from docs/flows, docs/SALES-STORIES.md and
 * docs/PACKS.md; "note" carries the honest limits from each story's "Before you promise".
 */

export const SITE_URL = (process.env.NEXT_PUBLIC_WEB_URL ?? "https://agentry.duckdns.org").replace(/\/$/, "");
export const SITE_NAME = "Agentry";
export const TAGLINE = "AI agents for Indian businesses, built and run for you";

export type GroupKey = "talk" | "leads" | "back-office" | "marketing" | "ca";

export const groups: { key: GroupKey; name: string; hand: string; blurb: string }[] = [
  { key: "talk", name: "Talk to customers", hand: "every enquiry answered", blurb: "Chat, WhatsApp, Telegram and phone, answered from your own facts, day and night." },
  { key: "leads", name: "Leads & sales", hand: "no lead left cold", blurb: "New leads answered in a minute, old leads revived, renewals collected." },
  { key: "back-office", name: "Back office", hand: "the boring admin, gone", blurb: "Inbox, invoices, bills, hiring, stock and field jobs handled for you." },
  { key: "marketing", name: "Marketing", hand: "show up everywhere", blurb: "Posts, Shorts, local SEO, festival campaigns and reviews from one place." },
  { key: "ca", name: "CA firm pack", hand: "13 agents for tax season", blurb: "Filings, documents, ITR, GST, TDS, notices and Excel work for CA firms." },
];

export type AgentInfo = {
  slug: string;
  name: string;
  group: GroupKey;
  line: string; // the one-sentence promise
  does: string[]; // what it does, plain words
  keywords: string[]; // what people search for
  note?: string; // honest limit, shown on its page
};

export const catalog: AgentInfo[] = [
  // ---------- talk to customers ----------
  { slug: "website-chat-agent", name: "Website chat agent", group: "talk", line: "A salesperson on your website who never sleeps.",
    does: ["Answers visitors from your services, prices and FAQs", "Qualifies them: need, budget, timeline", "Books the call or appointment in your calendar", "Hands over to a person when it should"],
    keywords: ["AI chatbot for website", "website chat agent India", "lead qualification chatbot"] },
  { slug: "whatsapp-ai-assistant", name: "WhatsApp assistant", group: "talk", line: "Every WhatsApp answered in a minute, even at midnight.",
    does: ["Replies on your own WhatsApp Business number", "Answers, books appointments and takes details", "Follows WhatsApp's 24-hour rules and templates", "Starts in approval mode: you see drafts first"],
    keywords: ["WhatsApp AI assistant for business", "WhatsApp chatbot India", "WhatsApp auto reply AI"] },
  { slug: "telegram-assistant", name: "Telegram assistant", group: "talk", line: "Your business on Telegram, and your team's control room.",
    does: ["Customers chat with your own Telegram bot", "Your team gets cards, alerts and approvals on Telegram", "Ask questions or send voice notes to the team bot"],
    keywords: ["Telegram bot for business", "Telegram AI assistant"] },
  { slug: "ai-receptionist", name: "AI receptionist", group: "talk", line: "Never miss a call again.",
    does: ["Answers forwarded or busy calls in a natural voice", "Books appointments and takes messages from your knowledge", "Every call summarised, recorded (caller told) and searchable", "A Call back card for anyone who needs a person"],
    keywords: ["AI receptionist for clinics India", "AI phone answering service", "virtual receptionist AI"],
    note: "Indian phone numbers need a provider with business KYC; until yours is ready, try it in the browser." },
  { slug: "missed-call-recovery", name: "Missed-call recovery", group: "talk", line: "Every missed call gets a WhatsApp in a minute.",
    does: ["Your phone system tells us the moment a call is missed", "The caller gets a WhatsApp: sorry we missed you, how can we help?",
           "Your WhatsApp assistant answers and books; you see who was won back", "Once a day per caller, never to your own staff or anyone who opted out"],
    keywords: ["missed call WhatsApp message", "missed call recovery India", "auto reply missed call business", "Exotel missed call WhatsApp"],
    note: "Works with Exotel, MyOperator, Knowlarity, TATA Tele, Airtel IQ and any phone system that can call a web address." },
  { slug: "appointment-concierge", name: "Appointment concierge", group: "talk", line: "Fewer no-shows, fuller diary.",
    does: ["Confirms and reminds every appointment, whoever booked it", "Customers reply to confirm, reschedule or cancel", "No-shows followed up, freed slots offered to the waitlist"],
    keywords: ["appointment reminder WhatsApp", "reduce no-shows clinic", "appointment confirmation automation"] },
  { slug: "support-desk", name: "Support desk", group: "talk", line: "No complaint falls through the cracks.",
    does: ["Issues from chat, WhatsApp and email become tickets", "Priority, owner and a reply-by time on every ticket", "\"Where's my order?\" answered from your order sheet", "Late tickets alert you; customers rate the answer"],
    keywords: ["customer support ticketing WhatsApp", "helpdesk for small business India"] },
  { slug: "catalogue-and-quotes", name: "Catalogue & quotes", group: "talk", line: "Quote in a minute, follow-up for free.",
    does: ["Answers product questions from your catalogue: price, GST, stock", "Builds a numbered PDF quote, priced from the catalogue only", "Sends it on WhatsApp or email and follows up on day 2 and 5", "Won and lost tracked"],
    keywords: ["quotation software WhatsApp", "automatic quote generator GST", "product catalogue chatbot"] },

  // ---------- leads & sales ----------
  { slug: "speed-to-lead", name: "Speed-to-lead", group: "leads", line: "Reply to every new lead in about a minute.",
    does: ["Form and ad leads get a personal message within a minute", "Replies are answered and booked by the assistant", "Consent and opt-outs respected"],
    keywords: ["lead follow up automation", "instant lead response India", "Facebook lead ads WhatsApp follow up"] },
  { slug: "lead-reactivation", name: "Lead reactivation", group: "leads", line: "Money hiding in your old leads list.",
    does: ["Old leads messaged again, one by one, at a gentle pace", "Keen ones re-qualified and booked", "Only people with consent; opt-outs honoured"],
    keywords: ["old leads reactivation", "database reactivation campaign", "win back customers WhatsApp"] },
  { slug: "lead-research", name: "Lead research & meeting prep", group: "leads", line: "Walk into every meeting already knowing them.",
    does: ["A short research note on every new lead within a minute", "A one-page brief before each meeting"],
    keywords: ["lead research AI", "meeting prep brief"] },
  { slug: "personal-cold-email", name: "Personal cold email", group: "leads", line: "New meetings, written one person at a time.",
    does: ["Prospect lists researched from public sources", "A fact-checked personal first line for each", "You review before anything is sent", "Replies sorted and handed to you"],
    keywords: ["personalised cold email India", "B2B lead generation agency"],
    note: "Sending is opened client by client after domain warm-up; ask us about timing." },
  { slug: "renewals", name: "Renewals & repeat business", group: "leads", line: "Money you're already owed, collected on time.",
    does: ["AMCs, memberships, policies and services due: reminded 30, 7 and 1 days before", "A Razorpay payment link when there's an amount", "Lapsed customers get one win-back message", "Birthday wishes, once a year"],
    keywords: ["AMC renewal reminder", "membership renewal automation", "renewal reminder WhatsApp"] },

  // ---------- back office ----------
  { slug: "inbox-triage", name: "Inbox triage", group: "back-office", line: "Your inbox, sorted before you've had your chai.",
    does: ["Every Gmail or Outlook email labelled within a minute", "Urgent ones ping the right person on WhatsApp or Telegram", "Ready replies in your tone, from your real prices", "Fraud warnings on changed bank details and lookalike domains"],
    keywords: ["AI email assistant Gmail", "email management for small business", "inbox automation India"] },
  { slug: "invoice-follow-up", name: "Invoice follow-up", group: "back-office", line: "Get paid without the awkward phone calls.",
    does: ["Imports invoices from Sheets, Tally, Zoho or QuickBooks exports", "Polite, then firm reminders on day 7, 14, 21 and 28", "Payment links (Razorpay, Stripe); stops the moment it's paid", "Replies understood: promise to pay, dispute, already paid", "MSME suppliers: the 45-day rule, interest at 3× the RBI bank rate, a Samadhaan claim draft"],
    keywords: ["payment reminder software India", "invoice follow up automation", "overdue invoice reminder WhatsApp"] },
  { slug: "bookkeeping-assistant", name: "Bookkeeping assistant", group: "back-office", line: "Snap the bill. It's in Tally.",
    does: ["Bills and receipts from WhatsApp, Telegram or email read by AI", "Checked by code: totals, GST, duplicates", "Confident ones filed, the rest asked about", "Export to Tally or a spreadsheet"],
    keywords: ["bill scanning to Tally", "receipt OCR GST", "bookkeeping automation India"] },
  { slug: "hiring-assistant", name: "Hiring assistant", group: "back-office", line: "200 CVs, shortlisted by lunch.",
    does: ["Writes the job post and a public apply link", "Scores every CV 0-100 with quoted reasons", "Personal details like age and religion hidden from the AI", "Books interviews and sends polite regrets"],
    keywords: ["AI resume screening India", "CV shortlisting tool", "hiring automation small business"] },
  { slug: "stock-shelf-scanner", name: "Stock shelf scanner", group: "back-office", line: "Snap the shelf. Know what to reorder.",
    does: ["A shelf photo becomes counts per item", "Doubtful counts highlighted for a person to check", "Reorder lists grouped by supplier, ready for WhatsApp"],
    keywords: ["stock counting app photo", "inventory reorder WhatsApp", "shop stock management AI"] },
  { slug: "ops-dispatcher", name: "Ops dispatcher", group: "back-office", line: "Every service call, on one board.",
    does: ["Visits booked by your WhatsApp assistant or the team", "Assigned to the technician with the skill, the area and room in the day", "Customers told \"on the way\" and \"done\"", "Finished jobs become invoices that chase themselves"],
    keywords: ["field service management India", "technician dispatch software", "AC repair booking software"],
    note: "No technician app or live GPS: technicians get WhatsApp messages and the office updates the status." },
  { slug: "sop-and-proposal-drafter", name: "SOP & proposal drafter", group: "back-office", line: "Write it down once, run it forever.",
    does: ["SOPs with a flowchart", "Proposals priced only from your brief or services", "Checklists with who and when", "Edit, finalise and download"],
    keywords: ["SOP writer AI", "proposal generator small business"] },

  // ---------- marketing ----------
  { slug: "content-repurposing", name: "Content repurposing", group: "marketing", line: "One video a week. A month of content.",
    does: ["One recording becomes about 30 posts for LinkedIn, Instagram and X", "Quotes checked word for word against the recording", "Branded quote cards and vertical clips with captions", "You approve; it posts on schedule and learns what works"],
    keywords: ["content repurposing service India", "video to social media posts", "podcast to LinkedIn posts"] },
  { slug: "ai-video-studio", name: "AI video studio", group: "marketing", line: "Shorts every week, without filming.",
    does: ["Picks a topic from your services and writes the script", "Checked for invented prices and promises before it costs anything", "Google Veo makes the scenes; your captions and end card are added", "Approve from your phone or let it post to YouTube"],
    keywords: ["AI YouTube Shorts maker", "AI video for business India", "faceless YouTube automation"] },
  { slug: "local-seo", name: "Local SEO", group: "marketing", line: "Be the one they find when they search nearby.",
    does: ["Audits your site: titles, speed, broken links, local business data", "Fixes listed in order of impact", "Local articles written from your own facts only", "A fresh audit and drafts every month"],
    keywords: ["local SEO for small business India", "SEO audit tool", "local SEO articles"] },
  { slug: "ai-visibility", name: "AI visibility", group: "marketing", line: "Be the name ChatGPT gives when customers ask.",
    does: ["Asks ChatGPT, Gemini and Perplexity the questions your customers ask, every month", "Shows who they name: you or your competitors", "Finds the sites the assistants trust, and gets you listed there", "Fixes: business details, FAQ answers and answer pages for your website"],
    keywords: ["does ChatGPT recommend my business", "AI search visibility India", "GEO for small business", "generative engine optimization agency"],
    note: "Assistants answer differently for each person and place; the score is an estimate measured the same way each month." },
  { slug: "festival-campaigns", name: "Festival campaigns", group: "marketing", line: "Never miss Diwali again.",
    does: ["Indian festival calendar for 2026-27", "Weeks ahead: a theme, posts, a WhatsApp message and a greeting", "Only your own offers; anything else is flagged", "Nothing is broadcast by itself"],
    keywords: ["Diwali marketing ideas small business", "festival offer WhatsApp message", "festival social media posts"] },
  { slug: "review-management", name: "Review management", group: "marketing", line: "Every review answered, every unhappy customer caught.",
    does: ["Replies drafted in your voice", "Unhappy reviews alert you straight away", "Happy customers asked for a review"],
    keywords: ["Google review management India", "reply to Google reviews AI"] },
  { slug: "competitor-watch", name: "Competitor & price watch", group: "marketing", line: "Know when your competitor moves, before your customers do.",
    does: ["Watches competitor pages, prices and reviews", "A short summary of what changed", "Alerts when something matters"],
    keywords: ["competitor price monitoring", "competitor tracking tool India"] },

  // ---------- CA firm pack ----------
  { slug: "ca-filing-tracker", name: "Filing tracker", group: "ca", line: "Every return on one board, from documents pending to verified.",
    does: ["A board per period: ITR, GST, TDS", "Owner and due date on every card", "Clients asking \"is my ITR filed?\" answered on WhatsApp"],
    keywords: ["ITR filing tracker for CA", "CA practice management software"] },
  { slug: "ca-document-chaser", name: "Document chaser", group: "ca", line: "Documents chase themselves.",
    does: ["A checklist per client per filing", "Polite WhatsApp reminders every few days", "Photos and PDFs matched to the right item and filed"],
    keywords: ["document collection for CA firms", "client document reminder WhatsApp"] },
  { slug: "ca-tax-documents-reader", name: "Tax documents reader", group: "ca", line: "Form 16, AIS and 26AS read and compared.",
    does: ["Form 16, AIS, TIS and 26AS read into one sheet per client", "Mismatches flagged: income in AIS not declared, TDS not matching"],
    keywords: ["AIS Form 16 mismatch", "26AS reconciliation tool"] },
  { slug: "ca-compliance-calendar", name: "Compliance calendar", group: "ca", line: "No due date missed, for any client.",
    does: ["GST, TDS, advance tax, ROC and PF/ESI dates per client", "Clients and staff reminded 7 and 2 days before"],
    keywords: ["compliance calendar CA India", "GST due date reminder"] },
  { slug: "ca-itr-preparation", name: "ITR preparation", group: "ca", line: "Old vs new regime, worked out for every client.",
    does: ["Tax computed under both regimes", "Shows which saves money and which ITR form fits", "The CA checks and files"],
    keywords: ["ITR filing automation for CA firms", "old vs new tax regime calculator"],
    note: "The CA files; nothing is uploaded to the portal by Agentry." },
  { slug: "ca-capital-gains", name: "Capital gains", group: "ca", line: "Broker statements to Schedule CG.",
    does: ["Zerodha, Groww, Upstox and CAMS/KFintech statements read", "STCG and LTCG worked out, with grandfathering"],
    keywords: ["capital gains calculator for CA", "Schedule CG from broker statement"] },
  { slug: "ca-bank-classifier", name: "Bank statement classifier", group: "ca", line: "Statement lines tagged, learning from corrections.",
    does: ["Income, expense, drawings and transfers tagged", "Trial balance and 44AD/44ADA working"],
    keywords: ["bank statement analysis for CA", "bank statement to Excel classification"],
    note: "Bank statements must be Excel or CSV for now." },
  { slug: "ca-gst-reconciliation", name: "GST reconciliation", group: "ca", line: "GSTR-2B vs your purchase register, in minutes.",
    does: ["Missing invoices, wrong GSTINs and amount differences found", "A message drafted for every supplier who hasn't filed"],
    keywords: ["GSTR 2B reconciliation tool", "GST reconciliation software India"] },
  { slug: "ca-tds-returns", name: "TDS returns", group: "ca", line: "24Q/26Q data checked before you file.",
    does: ["PAN checks and late-deduction interest", "Form 16/16A for employees and vendors"],
    keywords: ["TDS return preparation", "TDS interest calculator"] },
  { slug: "ca-tax-audit-3cd", name: "Tax audit (3CD)", group: "ca", line: "Clause tests from the books, exceptions flagged.",
    does: ["40A(3), 43B, 43B(h) MSME and more checked", "Exceptions listed for the auditor"],
    keywords: ["3CD tax audit automation", "43B(h) MSME check"] },
  { slug: "ca-notice-handler", name: "Notice handler", group: "ca", line: "Income tax notices explained, replies drafted.",
    does: ["143(1), 139(9) and 148 notices explained in plain words", "The difference computed and a reply drafted", "A card due before the deadline"],
    keywords: ["income tax notice reply", "143(1) notice response"] },
  { slug: "recurring-books", name: "Recurring entries & budgets", group: "ca", line: "Rent, retainers and EMIs booked on their dates.",
    does: ["Recurring entries posted automatically", "An alert at 80% of a budget"],
    keywords: ["recurring journal entries", "budget alert accounting"] },
  { slug: "ca-financial-statements", name: "Financial statements", group: "ca", line: "Trial balance in, Schedule III statements out.",
    does: ["Balance sheet and profit & loss in the Schedule III format, with last year", "Ratios, with the changes over 25% to explain",
      "Questions for the client wherever a figure moved a lot; ledgers you fix once are learned"],
    keywords: ["Schedule III financial statements from trial balance", "Tally trial balance to balance sheet", "final accounts preparation software India"] },
  { slug: "ca-gstr1", name: "GSTR-1 preparation", group: "ca", line: "The month's sales register, ready for GSTR-1.",
    does: ["B2B, B2CL, B2CS, exports, credit / debit notes, HSN and documents issued", "Checked first: GSTINs, IGST vs CGST + SGST, rates, values, invoice numbers, dates",
      "The GST offline tool's Excel workbook, ready to import"],
    keywords: ["GSTR-1 preparation software", "sales register to GSTR-1 Excel", "GSTR-1 offline tool Excel"] },
  { slug: "ca-upload-hub", name: "Upload hub", group: "ca", line: "A client's pile of files, sorted and started in one drop.",
    does: ["Many files or a zip, from your team or the client's own portal", "Each recognised, filed on the client and ticked off the checklist",
      "The right agent run on each: GST reconciliation, bank, capital gains, TDS, anomalies, Form 16 / AIS, notices"],
    keywords: ["client document collection for CA", "bulk upload documents accounting firm", "CA document management India"] },
  { slug: "ca-anomaly-finder", name: "Anomaly finder", group: "ca", line: "A ledger checked like a reviewer would, in seconds.",
    does: ["Duplicates, repeated and missing voucher numbers", "Cash over the 40A(3) / 269ST limits, split entries added up",
      "Wrong IGST vs CGST + SGST, odd GST rates, invalid GSTINs, dates outside the year, outliers, Benford test"],
    keywords: ["ledger scrutiny tool for CA", "audit anomaly detection India", "duplicate entries in Tally"] },
  { slug: "ca-excel-cleaner", name: "Excel cleaner", group: "ca", line: "The messy sheet a client sends, clean in one click.",
    does: ["Title lines, totals and repeated headers removed", "Dr / Cr, brackets and ₹ amounts made numbers; dates in one format",
      "GSTIN and PAN checked, duplicates removed, same party spelt differently grouped"],
    keywords: ["clean Excel data for accountants", "sales register cleanup", "Tally import data cleaning"] },
  { slug: "excel-desk", name: "Excel desk", group: "ca", line: "Any PDF to Excel, in your firm's layout.",
    does: ["PDFs converted to your Excel layout", "Reconciliations: books vs bank, debtors", "Ask questions of your spreadsheet"],
    keywords: ["PDF to Excel for CA", "Excel automation for accountants"] },
];

/** Included with every plan (docs/SALES-STORIES.md "Included with every plan"). */
export const included = [
  { name: "Ask your business", line: "Ask \"what's overdue?\" in plain words, on the portal or Telegram. The copilot can also plan the work and do it when you tap Do it." },
  { name: "Business Pulse", line: "Every morning, one message: what needs you, who's coming in, the money that came in." },
  { name: "Needs you", line: "One queue for everything a person must decide, with assign and snooze." },
  { name: "Roles", line: "Owner, manager, front desk, finance, viewer: front desk never sees money, finance never sees chats." },
  { name: "Monthly results report", line: "Results, money won back and the fee you paid, every result with its proof." },
  { name: "Safe by design", line: "Approval mode first, quiet hours at night, a guard against prompt tricks, and an audit log of every action." },
];

export type Audience = {
  slug: string;
  name: string;
  title: string; // <title>
  description: string;
  h1: string;
  hand: string;
  pains: string[];
  agents: string[]; // catalog slugs
  story: { title: string; before: string; after: string[] };
  bundle?: string;
  keywords: string[];
  faqs: [string, string][];
};

export const audiences: Audience[] = [
  {
    slug: "ca-firms", name: "CA firms",
    title: "AI agents for CA firms: ITR, GST, TDS and document chasing",
    description: "Agentry's CA firm pack: documents chase themselves on WhatsApp, Form 16 and AIS mismatches flagged, old vs new regime worked out, GST 2B reconciled, notices drafted.",
    h1: "Your ITR season, on autopilot", hand: "for chartered accountants",
    pains: ["July: 400 clients, half haven't sent Form 16", "The phone rings all day with \"is my return filed?\"", "A junior types AIS numbers into Excel at midnight"],
    agents: ["ca-filing-tracker", "ca-document-chaser", "ca-tax-documents-reader", "ca-itr-preparation", "ca-gst-reconciliation", "ca-compliance-calendar", "ca-notice-handler", "ca-upload-hub", "ca-gstr1", "ca-financial-statements", "ca-excel-cleaner", "ca-anomaly-finder", "excel-desk"],
    story: { title: "How a season plays out (example)", before: "One click opens the season: a card for every client, each with its own checklist.",
      after: ["Clients get a polite WhatsApp every 3 days until every document is in", "Form 16 vs AIS differences flagged before a junior would miss them", "Old vs new regime compared; the CA checks and files", "\"Is my ITR filed?\" answered on WhatsApp with the acknowledgement number"] },
    bundle: "The CA firm pack: 13 CA agents plus inbox triage, WhatsApp assistant, invoice follow-up and bookkeeping. Every agent can also be bought on its own.",
    keywords: ["ITR filing automation for CA firms", "CA practice management software India", "GST reconciliation software", "document collection for CA"],
    faqs: [["Does Agentry file returns on the portal?", "No. The CA files. Agentry prepares, checks and chases; nothing is uploaded to the income tax portal by Agentry."],
      ["Which tax year rules does it use?", "FY 2025-26 rules today, updated each year."],
      ["Can we buy only some agents?", "Yes. The pack is a starting point: untick what you don't need, or buy any agent on its own."]],
  },
  {
    slug: "clinics", name: "Clinics",
    title: "AI receptionist and WhatsApp assistant for clinics in India",
    description: "Every call and WhatsApp answered, appointments booked and reminded, no-shows followed up and reviews requested. Built and run for dental, skin and physio clinics.",
    h1: "Every patient answered, every slot filled", hand: "for clinics and salons",
    pains: ["On a busy Saturday the front desk misses 14 calls", "Enquiries on WhatsApp wait until the evening", "Booked patients don't turn up"],
    agents: ["missed-call-recovery", "ai-receptionist", "whatsapp-ai-assistant", "website-chat-agent", "appointment-concierge", "review-management", "lead-reactivation"],
    story: { title: "What changes (example)", before: "Every missed call at a dental clinic is a patient who calls the next clinic.",
      after: ["Missed and busy calls go to the AI receptionist, which answers from the clinic's own timings, treatments and prices", "WhatsApp enquiries answered in a minute and booked into the diary", "Every appointment confirmed and reminded; freed slots offered to the waitlist", "Happy patients asked for a Google review"] },
    bundle: "Front Desk in a Box: WhatsApp assistant + Website chat + Appointment concierge + Review management.",
    keywords: ["AI receptionist for clinics India", "WhatsApp appointment booking for clinics", "dental clinic chatbot", "reduce no-shows clinic"],
    faqs: [["Do patients know it's AI?", "Yes. The assistant introduces itself as an AI assistant, and calls announce that they're recorded."],
      ["Will it give medical advice?", "No. It answers from the clinic's own facts (timings, treatments, prices) and hands anything clinical to your team."],
      ["How fast can we go live?", "Most businesses are live within 7 days. We do the setup; you review the agent before it goes live."]],
  },
  {
    slug: "home-services", name: "Home services",
    title: "AI booking and dispatch for home-services businesses",
    description: "WhatsApp bookings, technicians assigned by skill and area, customers told when you're on the way, and finished jobs invoiced automatically. For AC repair, plumbing, pest control and cleaning.",
    h1: "Every service call, on one board", hand: "for AC repair, plumbing, pest control, cleaning",
    pains: ["Bookings arrive on WhatsApp at all hours", "Technicians are assigned by phone and nobody knows who went where", "Invoices go out a week late"],
    agents: ["missed-call-recovery", "whatsapp-ai-assistant", "ops-dispatcher", "speed-to-lead", "invoice-follow-up", "renewals", "review-management"],
    story: { title: "What changes (example)", before: "A home-services owner takes bookings on WhatsApp, assigns technicians by phone and invoices late.",
      after: ["The WhatsApp assistant books the visit: service, day and address", "The technician with the right skill in that area, who isn't full, gets it on WhatsApp in one tap", "The customer hears \"on the way\" and \"done\"", "The finished job becomes an invoice that chases itself; AMCs are reminded before they're due"] },
    keywords: ["field service management India", "AC repair booking software", "technician dispatch app", "home services WhatsApp booking"],
    faqs: [["Do technicians need an app?", "No. Technicians get each job on WhatsApp, and the office updates the status."],
      ["Can it remind customers about AMC renewals?", "Yes, with the Renewals agent: reminders 30, 7 and 1 days before, with a payment link."],
      ["What if no technician is free?", "The job waits as new and a card asks a person to assign it."]],
  },
  {
    slug: "agencies", name: "Agencies & firms",
    title: "AI agents for agencies and B2B firms: inbox, invoices and content",
    description: "Inbox sorted with urgent alerts and ready replies, invoices chased politely until paid, and a month of content from one recording. For digital agencies, consultancies and B2B suppliers.",
    h1: "Money in faster, inbox under control", hand: "for agencies, consultancies and B2B firms",
    pains: ["140 unread emails every morning, the urgent one seen at 11:40", "Clients pay late and chasing is awkward", "\"We should be posting more\" never happens"],
    agents: ["inbox-triage", "invoice-follow-up", "bookkeeping-assistant", "content-repurposing", "personal-cold-email", "lead-research"],
    story: { title: "What changes (example)", before: "An agency owner starts every morning in an overflowing inbox.",
      after: ["Every email labelled in your own Gmail before you open it", "The urgent one has already pinged you on WhatsApp", "A ready reply, in your tone and with your real prices, under every email that needs one", "Overdue invoices reminded politely, then firmly, until paid"] },
    bundle: "Get Paid: Inbox triage + Invoice follow-up + Bookkeeping.",
    keywords: ["AI email assistant for agencies", "invoice follow up automation India", "content repurposing service"],
    faqs: [["Do emails go out without us?", "Not at first. Every agent starts in approval mode; you choose later which steps run on their own."],
      ["Which tools does it work with?", "Gmail and Outlook, WhatsApp, Google Sheets, Tally, Zoho, QuickBooks, Razorpay and Stripe."],
      ["Where do I start?", "Inbox triage: live in a day, and its opportunity report shows the missed leads and overdue money."]],
  },
];

export const bySlug = (slug: string) => catalog.find((a) => a.slug === slug);
export const inGroup = (g: GroupKey) => catalog.filter((a) => a.group === g);

/** Page metadata with the full Open Graph / Twitter set (a page's own openGraph replaces the root one, so it's rebuilt here). */
export function pageMeta(title: string, description: string, path: string, keywords?: string[]) {
  const images = [{ url: "/opengraph-image", width: 1200, height: 630, alt: `${title} · Agentry` }];
  return {
    title, description, keywords, alternates: { canonical: path },
    openGraph: { type: "website" as const, siteName: SITE_NAME, locale: "en_IN", url: path, title, description, images },
    twitter: { card: "summary_large_image" as const, title, description, images: ["/opengraph-image"] },
  };
}

/** "Clinics" -> "clinics" mid-sentence, but acronyms stay ("CA firms"). */
export const midSentence = (name: string) => (/^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1));
