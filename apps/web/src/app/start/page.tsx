import type { Metadata } from "next";
import { Footer } from "@/components/footer";
import { breadcrumbs, JsonLd } from "@/components/json-ld";
import { SiteNav } from "@/components/site-nav";
import { StartFlow } from "@/components/start";
import { pageMeta, SITE_URL } from "@/lib/catalog";

const TITLE = "Plans and pricing: start today";
const DESC = "Pick a plan, pay the first month and set up your AI assistant today. Website chat, WhatsApp, reminders and reviews, starting at ₹2,999 a month.";

export const metadata: Metadata = pageMeta(TITLE, DESC, "/start", ["AI assistant pricing India", "WhatsApp AI assistant price", "AI chatbot for clinic price"]);

export default async function StartPage({ searchParams }: { searchParams: Promise<{ plan?: string; site?: string }> }) {
  const { plan, site } = await searchParams;
  return (
    <>
      <SiteNav />
      <main id="main" className="mx-auto max-w-6xl px-4 pt-16 pb-20 sm:px-6">
        <nav aria-label="Breadcrumb" className="text-sm text-muted"><a href="/" className="hover:underline">Home</a> / Start</nav>
        <p className="mt-8 font-hand text-2xl text-muted">no call needed · live the same day</p>
        <h1 className="mt-1 font-display text-5xl leading-[1.05] font-bold tracking-tight sm:text-6xl">Start <span className="highlight">today</span></h1>
        <p className="mt-5 max-w-2xl text-lg text-ink-soft">Pick a plan, pay the first month, and open your account from the email we send. You see every reply before it goes
          out until you trust it. Prefer to talk first? <a href="/#demo" className="font-semibold underline underline-offset-4">Book a demo</a>.</p>
        <div className="mt-10"><StartFlow plan={plan} site={site} /></div>
      </main>
      <Footer />
      <JsonLd data={breadcrumbs([["Home", SITE_URL], ["Start", `${SITE_URL}/start`]])} />
    </>
  );
}
