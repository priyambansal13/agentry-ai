import { ArrowRight, X } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Cta } from "@/components/cta";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { breadcrumbs, faqPage, JsonLd } from "@/components/json-ld";
import { SiteChat } from "@/components/site-chat";
import { SiteNav } from "@/components/site-nav";
import { audiences, bySlug, pageMeta, SITE_URL, midSentence } from "@/lib/catalog";

export const dynamicParams = false;
const NICHE: Record<string, string> = { "ca-firms": "agency_or_firm", agencies: "agency_or_firm", clinics: "clinic_or_appointments", "home-services": "home_services" };

export function generateStaticParams() {
  return audiences.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const a = audiences.find((x) => x.slug === slug);
  if (!a) return {};
  return pageMeta(a.title, a.description, `/for/${a.slug}`, a.keywords);
}

export default async function AudiencePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = audiences.find((x) => x.slug === slug);
  if (!a) notFound();
  const agents = a.agents.map(bySlug).filter((x) => x !== undefined);
  return (
    <>
      <SiteNav />
      <main id="main">
        <section className="relative overflow-hidden">
          <div className="grain pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
          <div className="relative mx-auto max-w-6xl px-4 pt-16 pb-14 sm:px-6">
            <nav aria-label="Breadcrumb" className="text-sm text-muted"><Link href="/" className="hover:underline">Home</Link> / For {midSentence(a.name)}</nav>
            <p className="rise mt-8 font-hand text-2xl text-muted">{a.hand}</p>
            <h1 className="rise mt-1 max-w-4xl font-display text-5xl leading-[1.05] font-bold tracking-tight sm:text-7xl">{a.h1.split(" ").slice(0, -2).join(" ")}{" "}
              <span className="highlight">{a.h1.split(" ").slice(-2).join(" ")}</span></h1>
            <p className="rise mt-6 max-w-2xl text-lg text-ink-soft sm:text-xl">{a.description}</p>
            <a href="#demo" className="mt-8 inline-flex h-14 items-center gap-2 rounded-2xl bg-ink px-6 font-semibold text-paper hover:opacity-90">Build my free demo <ArrowRight aria-hidden="true" className="h-5 w-5" /></a>
          </div>
        </section>

        <section className="border-y-2 border-ink bg-ink text-paper">
          <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
            <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">Sound familiar?</h2>
            <ul className="mt-8 grid gap-4 sm:grid-cols-3">
              {a.pains.map((p) => <li key={p} className="flex gap-3 rounded-2xl border border-paper/20 p-5"><X aria-hidden="true" className="h-5 w-5 shrink-0 text-lime" />{p}</li>)}
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <p className="font-hand text-2xl text-muted">{a.story.title.toLowerCase()}</p>
          <h2 className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-4xl">{a.story.before}</h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2">
            {a.story.after.map((s, i) => (
              <li key={s} className="flex gap-4 rounded-3xl border-2 border-ink bg-card p-5">
                <span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-full border-2 border-ink bg-lime font-display font-bold text-lime-ink">{i + 1}</span>
                <span className="pt-1.5">{s}</span>
              </li>
            ))}
          </ol>
          {a.bundle && <p className="mt-8 rounded-2xl border-2 border-dashed border-ink p-5 text-lg"><span className="font-semibold">Start with:</span> {a.bundle}</p>}
        </section>

        <section className="border-y-2 border-ink bg-lime-soft">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
            <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">The agents that do it</h2>
            <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {agents.map((x) => (
                <li key={x.slug}>
                  <Link href={`/agents/${x.slug}`} className="block h-full rounded-3xl border-2 border-ink bg-card p-5 transition hover:-translate-y-1 hover:shadow-[6px_6px_0_0_var(--ink)]">
                    <h3 className="font-display text-xl font-bold">{x.name}</h3>
                    <p className="mt-1 text-ink-soft">{x.line}</p>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
          <h2 className="font-display text-3xl font-bold tracking-tight">Questions</h2>
          <div className="mt-6 divide-y-2 divide-line border-y-2 border-line">
            {a.faqs.map(([q, ans]) => (
              <details key={q} className="group py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-lg font-semibold">{q}
                  <span aria-hidden="true" className="font-hand text-3xl transition-transform group-open:rotate-45">+</span></summary>
                <p className="mt-3 text-ink-soft">{ans}</p>
              </details>
            ))}
          </div>
        </section>

        <Cta title={`A demo for your ${a.name === "CA firms" ? "firm" : "business"}, with your name on it`} />
        <DemoForm niche={NICHE[a.slug]} />
      </main>
      <Footer />
      <SiteChat />
      <JsonLd data={[breadcrumbs([["Home", SITE_URL], [`For ${midSentence(a.name)}`, `${SITE_URL}/for/${a.slug}`]]), faqPage(a.faqs)]} />
    </>
  );
}
