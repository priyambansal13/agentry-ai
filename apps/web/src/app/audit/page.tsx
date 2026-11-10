import { Bot, MessageCircle, Search } from "lucide-react";
import type { Metadata } from "next";
import { AuditForm } from "@/components/audit-form";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { breadcrumbs, faqPage, JsonLd } from "@/components/json-ld";
import { SiteNav } from "@/components/site-nav";
import { pageMeta, SITE_URL } from "@/lib/catalog";

const TITLE = "Free AI visibility & website audit for your business";
const DESC = "Does ChatGPT recommend your business when customers ask? Can visitors reach you after hours? A free 60-second check of your "
  + "website, AI search visibility and missed enquiries, with the fixes.";

export const metadata: Metadata = pageMeta(TITLE, DESC, "/audit", ["does ChatGPT recommend my business", "AI search visibility check",
  "free website audit India", "GEO audit", "local SEO audit free"]);

const CHECKS = [
  { icon: Bot, title: "Do AI assistants name you?", body: "We ask ChatGPT and Gemini, with web search on, the questions your customers ask, and see who they recommend." },
  { icon: MessageCircle, title: "Can customers reach you at night?", body: "Chat, WhatsApp, online booking and a phone number: what an evening visitor finds on your website." },
  { icon: Search, title: "Does Google understand your site?", body: "Business details, titles, speed, sitemap and broken links, the basics that decide local search." },
];
const FAQS = [
  ["Is it really free?", "Yes. The score and your biggest problems show straight away. Leave your name and email for the full report: every AI answer and every fix, in order."],
  ["How do you know what ChatGPT says?", "We ask the assistants through their official APIs with web search switched on, in your city. Answers vary by person and place, so treat it as a good estimate, not a guarantee."],
  ["Will you spam me?", "No. You get the report by email, and one person from our team may reply to it. No newsletters, and you can ask us to delete your details any time."],
  ["What happens to my website?", "We read up to six public pages, like a search engine does. Nothing is changed, and nothing behind a login is touched."],
] as const;

export default async function AuditPage({ searchParams }: { searchParams: Promise<{ site?: string; service?: string }> }) {
  const { site = "", service = "" } = await searchParams;
  return (
    <>
      <SiteNav />
      <main id="main">
        <section className="relative overflow-hidden">
          <div className="grain pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
          <div className="relative mx-auto max-w-6xl px-4 pt-16 pb-14 sm:px-6">
            <nav aria-label="Breadcrumb" className="text-sm text-muted"><a href="/" className="hover:underline">Home</a> / Free audit</nav>
            <p className="rise mt-8 font-hand text-2xl text-muted">free · 60 seconds · no call</p>
            <h1 className="rise mt-1 max-w-4xl font-display text-5xl leading-[1.05] font-bold tracking-tight sm:text-7xl">
              Is your business <span className="highlight">losing customers?</span></h1>
            <p className="rise mt-6 max-w-2xl text-lg text-ink-soft sm:text-xl">Customers now ask ChatGPT who to call. Find out if it names you, or your competitor,
              and what a visitor finds on your website at 10 pm.</p>
            <div className="mt-8 max-w-5xl rounded-3xl border-2 border-ink bg-card p-5 shadow-[6px_6px_0_0_var(--ink)] sm:p-7">
              <AuditForm site={site} service={service} compact />
            </div>
          </div>
        </section>

        <section className="border-y-2 border-ink bg-ink text-paper">
          <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
            <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">What we check</h2>
            <ul className="mt-8 grid gap-4 sm:grid-cols-3">
              {CHECKS.map((c) => (
                <li key={c.title} className="rounded-2xl border border-paper/20 p-5">
                  <c.icon aria-hidden="true" className="h-6 w-6 text-lime" />
                  <h3 className="mt-3 font-display text-xl font-bold">{c.title}</h3>
                  <p className="mt-2 text-paper/75">{c.body}</p>
                </li>))}
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
          <h2 className="font-display text-3xl font-bold tracking-tight">Questions</h2>
          <div className="mt-6 divide-y-2 divide-line border-y-2 border-line">
            {FAQS.map(([q, a]) => (
              <details key={q} className="group py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-lg font-semibold">{q}
                  <span aria-hidden="true" className="font-hand text-3xl transition-transform group-open:rotate-45">+</span></summary>
                <p className="mt-3 text-ink-soft">{a}</p>
              </details>))}
          </div>
        </section>
        <DemoForm />
      </main>
      <Footer />
      <JsonLd data={[breadcrumbs([["Home", SITE_URL], ["Free audit", `${SITE_URL}/audit`]]), faqPage(FAQS)]} />
    </>
  );
}
