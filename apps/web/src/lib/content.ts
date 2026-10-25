/** Landing page copy. Flows mirror the reference sketches in docs/automations/*.md. */

export type Agent = {
  key: string;
  name: string;
  tagline: string;
  flow: string[];
  highlight: number;
  outcome: string;
  pricing: string;
};

export const agents: Agent[] = [
  { key: "receptionist", name: "AI receptionist", tagline: "Missed call = missed customer.",
    flow: ["Call, 24/7", "AI answers", "Book · FAQ · reschedule", "Human, if needed"], highlight: 1,
    outcome: "Every call answered, even at 11pm", pricing: "Monthly, minutes included" },
  { key: "speed-to-lead", name: "Speed-to-lead", tagline: "Call them while they still care.",
    flow: ["Form / ad lead", "Wait ~1 min", "AI voice call", "Booked"], highlight: 2,
    outcome: "New leads called within about a minute", pricing: "Per booked appointment" },
  { key: "website-chat", name: "Website chat agent", tagline: "Helpful first, never pushy.",
    flow: ["Visitor", "Need · budget · timeline", "Qualified?", "CRM + call booked"], highlight: 3,
    outcome: "Visitors turned into booked calls", pricing: "Setup + monthly" },
  { key: "reactivation", name: "Lead reactivation", tagline: "No new ad spend.",
    flow: ["Old leads list", "“Hi again!” one by one", "Re-qualify", "Book the keen ones"], highlight: 1,
    outcome: "Revenue from leads you'd written off", pricing: "No win, no fee" },
  { key: "cold-email", name: "Personal cold email", tagline: "One real line, written for them.",
    flow: ["Google Maps list", "Find decision maker", "Read their site", "Personal first line"], highlight: 3,
    outcome: "Meetings with businesses you choose", pricing: "Setup + monthly or per meeting" },
  { key: "inbox-triage", name: "Inbox triage", tagline: "Only the urgent stuff pings you.",
    flow: ["New email", "AI sorts it", "Urgent → WhatsApp", "Reply drafted"], highlight: 1,
    outcome: "An inbox that answers itself (you still press send)", pricing: "Low monthly" },
  { key: "invoices", name: "Invoice follow-up", tagline: "Polite, then firm, then paid.",
    flow: ["Overdue?", "Day 7 friendly", "Day 21 firm", "Stops when paid"], highlight: 3,
    outcome: "Get paid without the awkward chasing", pricing: "Monthly or % recovered" },
  { key: "content", name: "Content repurposing", tagline: "One video, a month of posts.",
    flow: ["45-min video", "10 best moments", "IG · LinkedIn · X", "You approve, it posts"], highlight: 1,
    outcome: "30 on-brand posts from one recording", pricing: "Setup + monthly" },
];

export const niches = [
  {
    key: "agencies",
    label: "Agencies & firms",
    who: "Digital agencies, CA and accounting firms, consultancies, IT services",
    pain: "Inboxes overflowing, invoices paid late, new business left to chance.",
    ladder: ["Inbox triage", "Invoice follow-up", "Website chat + cold email"],
  },
  {
    key: "clinics",
    label: "Clinics & appointments",
    who: "Dental and skin clinics, physios, salons, coaching institutes",
    pain: "Calls missed during busy hours, enquiries never followed up, empty slots.",
    ladder: ["Website chat or receptionist", "Lead reactivation", "The Boring Machine"],
  },
  {
    key: "home-services",
    label: "Home services",
    who: "Solar, interiors, real estate, renovation",
    pain: "Expensive ad leads that go cold before anyone calls back.",
    ladder: ["Speed-to-lead", "Lead reactivation", "AI receptionist"],
  },
];

export const faqs = [
  ["Do my customers know they're talking to AI?", "Yes. Our agents introduce themselves as AI assistants, and calls announce recording. It's the law in many places, and customers trust it more."],
  ["Will the AI send anything without my approval?", "Not at first. Every agent starts in approval mode: you see each draft and approve it. Once you trust the output, you choose which steps can run on their own."],
  ["Do messages come from you or from us?", "From you: your email, your WhatsApp number, your phone line. Cold email is the exception: it uses separate sending domains to protect your main one."],
  ["How long does setup take?", "Most businesses are live within 7 days. We do the setup for you; you just connect your accounts and review the agent before it goes live."],
  ["What tools do you work with?", "Gmail and Outlook, WhatsApp, Google Sheets, Tally, Zoho, QuickBooks, Xero, Razorpay, Stripe, Google Calendar and most CRMs."],
  ["What does it cost?", "Pick what fits: a setup fee plus a monthly retainer, pay only per booked appointment, or start small with one agent. The calculator above shows what you're losing today."],
] as const;
