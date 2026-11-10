import type { Metadata } from "next";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { breadcrumbs, JsonLd } from "@/components/json-ld";
import { SiteNav } from "@/components/site-nav";
import { TryForm } from "@/components/try-demo";
import { pageMeta, SITE_URL } from "@/lib/catalog";

const TITLE = "Try your own AI assistant, trained on your website";
const DESC = "Type your website and in 30 seconds chat with an AI assistant that answers your customers from your own pages. Free, no sign-up.";

export const metadata: Metadata = pageMeta(TITLE, DESC, "/try", ["AI chatbot trained on my website", "free AI assistant demo", "website AI assistant India"]);

export default async function TryPage({ searchParams }: { searchParams: Promise<{ site?: string }> }) {
  const { site = "" } = await searchParams;
  return (
    <>
      <SiteNav />
      <main id="main">
        <section className="relative overflow-hidden">
          <div className="grain pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
          <div className="relative mx-auto max-w-4xl px-4 pt-16 pb-20 sm:px-6">
            <nav aria-label="Breadcrumb" className="text-sm text-muted"><a href="/" className="hover:underline">Home</a> / Try it</nav>
            <p className="rise mt-8 font-hand text-2xl text-muted">free · 30 seconds · no sign-up</p>
            <h1 className="rise mt-1 font-display text-5xl leading-[1.05] font-bold tracking-tight sm:text-7xl">Meet <span className="highlight">your</span> AI assistant</h1>
            <p className="rise mt-6 max-w-2xl text-lg text-ink-soft sm:text-xl">Type your website. We read it, and you chat with an assistant that answers your customers
              from your own pages, in English, Hindi or Hinglish.</p>
            <div className="mt-8 rounded-3xl border-2 border-ink bg-card p-5 shadow-[6px_6px_0_0_var(--ink)] sm:p-7"><TryForm site={site} /></div>
            <p className="mt-4 text-sm text-muted">A 24-hour preview that only reads your public pages. The real assistant also books appointments, takes leads and hands
              over to your team.</p>
          </div>
        </section>
        <DemoForm />
      </main>
      <Footer />
      <JsonLd data={breadcrumbs([["Home", SITE_URL], ["Try it", `${SITE_URL}/try`]])} />
    </>
  );
}
