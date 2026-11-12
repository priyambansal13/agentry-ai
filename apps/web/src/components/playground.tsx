"use client";

import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { BillBox, ColdEmailBox, ContentBox, DocBox, FestivalBox, HiringBox, InboxBox, LeadResearchBox, ReactivationBox, ShelfBox, VideoBox } from "./try/ai";
import { Audit3cdBox, BankBox, CalendarBox, CapitalGainsBox, ChaserBox, ExcelBox, FilingTrackerBox, GstBox, ItrBox, NoticeBox, RecurringBooksBox, TaxDocsBox, TdsBox } from "./try/ca";
import { AgentSlug, SourceOfTruth } from "./try/kit";
import { DispatcherBox, MissedCallBox, RenewalsBox, SpeedToLeadBox } from "./try/sims";

const TALK = ["website-chat-agent", "whatsapp-ai-assistant", "telegram-assistant", "ai-receptionist", "appointment-concierge", "support-desk", "catalogue-and-quotes"];
const FOUND = ["ai-visibility", "local-seo", "review-management", "competitor-watch"];

/** Agent page -> its try-it box: the agent's real engine on a sample or the visitor's own input (components/try/). */
const BOXES: Record<string, () => React.ReactNode> = {
  "ai-video-studio": VideoBox, "bookkeeping-assistant": BillBox, "content-repurposing": ContentBox, "excel-desk": ExcelBox,
  "festival-campaigns": FestivalBox, "hiring-assistant": HiringBox, "inbox-triage": InboxBox, "lead-reactivation": ReactivationBox,
  "lead-research": LeadResearchBox, "ops-dispatcher": DispatcherBox, "personal-cold-email": ColdEmailBox, "recurring-books": RecurringBooksBox,
  renewals: RenewalsBox, "missed-call-recovery": MissedCallBox, "sop-and-proposal-drafter": DocBox, "speed-to-lead": SpeedToLeadBox, "stock-shelf-scanner": ShelfBox,
  "ca-bank-classifier": BankBox, "ca-capital-gains": CapitalGainsBox, "ca-compliance-calendar": CalendarBox, "ca-document-chaser": ChaserBox,
  "ca-filing-tracker": FilingTrackerBox, "ca-gst-reconciliation": GstBox, "ca-itr-preparation": ItrBox, "ca-notice-handler": NoticeBox,
  "ca-tax-audit-3cd": Audit3cdBox, "ca-tax-documents-reader": TaxDocsBox, "ca-tds-returns": TdsBox,
};

/** "Try it" on an agent's page: every agent has something to try without signing up. */
export function Playground({ slug }: { slug: string }) {
  const Box = BOXES[slug];
  if (Box) return <AgentSlug.Provider value={slug}><Box /></AgentSlug.Provider>;
  if (slug === "invoice-follow-up") return <ReminderPreview />;
  if (TALK.includes(slug)) return <Card title="Try it on your own website" body="Type your website and chat with an assistant that answers from your own pages. 30 seconds, no sign-up." href="/try" cta="Build my assistant" field="site" />;
  if (FOUND.includes(slug)) return <Card title="Does ChatGPT recommend you?" body="A free 60-second check: who AI assistants name for your service in your city, and what visitors find on your website." href="/audit" cta="Run the free audit" field="site" />;
  return null;
}

function Card({ title, body, href, cta, field }: { title: string; body: string; href: string; cta: string; field: string }) {
  const [site, setSite] = useState("");
  return (
    <section aria-label={title} className="mt-16 rounded-3xl border-2 border-ink bg-lime-soft p-6 sm:p-8">
      <p className="font-hand text-2xl text-muted">try it now</p>
      <h2 className="mt-1 font-display text-3xl font-bold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-2xl text-ink-soft">{body}</p>
      <form action={href} className="mt-5 flex max-w-xl flex-col gap-3 sm:flex-row">
        <label htmlFor={`pg-${field}`} className="sr-only">Your website</label>
        <input id={`pg-${field}`} name={field} inputMode="url" placeholder="yourbusiness.in" value={site} onChange={(e) => setSite(e.target.value)}
          className="h-12 w-full rounded-xl border-2 border-ink bg-card px-4 sm:flex-1 focus:outline-none" />
        <button type="submit" className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90">{cta} <ArrowRight aria-hidden="true" className="h-5 w-5" /></button>
      </form>
    </section>
  );
}

const STEPS = [
  { day: 7, tone: "friendly", text: (c: string, n: string, amt: string, me: string) =>
    `Hi ${c}, a gentle reminder that invoice ${n} for ${amt} was due last week. Here's the payment link if it helps. Thank you! – ${me}` },
  { day: 14, tone: "clear", text: (c: string, n: string, amt: string, me: string) =>
    `Hi ${c}, invoice ${n} (${amt}) is now two weeks overdue. Could you let us know when we can expect payment? You can pay here in a minute. – ${me}` },
  { day: 21, tone: "firm", text: (c: string, n: string, amt: string, me: string) =>
    `Hi ${c}, invoice ${n} for ${amt} is three weeks overdue. Please arrange payment this week, or reply if there's a problem with the invoice. – ${me}` },
  { day: 28, tone: "final", text: (c: string, n: string, amt: string, me: string) =>
    `Hi ${c}, invoice ${n} (${amt}) is four weeks overdue. Please pay by Friday or call us so we can sort it out together. – ${me}` },
];

function ReminderPreview() {
  const [v, setV] = useState({ customer: "Ravi", invoice: "INV-1042", amount: 48500, business: "Sharma Digital" });
  const amt = `₹${v.amount.toLocaleString("en-IN")}`;
  const input = "h-11 w-full rounded-xl border-2 border-ink bg-card px-3 focus:outline-none";
  return (
    <section aria-label="Preview the reminders" className="mt-16 rounded-3xl border-2 border-ink bg-lime-soft p-6 sm:p-8">
      <p className="font-hand text-2xl text-muted">try it now</p>
      <h2 className="mt-1 font-display text-3xl font-bold tracking-tight">See the reminders your customer would get</h2>
      <div className="mt-5 grid gap-3 sm:grid-cols-4">
        <div><label htmlFor="r-c" className="mb-1 block text-sm font-semibold">Customer</label><input id="r-c" className={input} value={v.customer} onChange={(e) => setV({ ...v, customer: e.target.value })} /></div>
        <div><label htmlFor="r-n" className="mb-1 block text-sm font-semibold">Invoice</label><input id="r-n" className={input} value={v.invoice} onChange={(e) => setV({ ...v, invoice: e.target.value })} /></div>
        <div><label htmlFor="r-a" className="mb-1 block text-sm font-semibold">Amount (₹)</label><input id="r-a" type="number" min={0} className={input} value={v.amount} onChange={(e) => setV({ ...v, amount: Math.max(0, Number(e.target.value) || 0) })} /></div>
        <div><label htmlFor="r-b" className="mb-1 block text-sm font-semibold">Your business</label><input id="r-b" className={input} value={v.business} onChange={(e) => setV({ ...v, business: e.target.value })} /></div>
      </div>
      <ol className="mt-6 grid gap-4 md:grid-cols-2">{STEPS.map((s) => (
        <li key={s.day} className="rounded-2xl border-2 border-ink bg-card p-4">
          <p className="text-sm font-semibold">Day {s.day} after the due date · <span className="text-muted">{s.tone}</span></p>
          <p className="mt-2 rounded-2xl rounded-tl-sm bg-[#dcf8c6] p-3 text-sm text-[#111]">{s.text(v.customer || "there", v.invoice, amt, v.business)}</p>
        </li>))}</ol>
      <p className="mt-4 text-sm text-muted">Sample wording: yours uses your facts and tone, stops the moment it&apos;s paid, pauses when they promise a date, and passes disputes to a person.</p>
      <SourceOfTruth slug="invoice-follow-up" />
    </section>
  );
}
