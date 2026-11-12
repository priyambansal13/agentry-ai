import { Check } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AgentStory } from "@/components/agent-story";
import { Cta } from "@/components/cta";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { breadcrumbs, JsonLd } from "@/components/json-ld";
import { Playground } from "@/components/playground";
import { SiteChat } from "@/components/site-chat";
import { SiteNav } from "@/components/site-nav";
import { audiences, bySlug, catalog, groups, inGroup, pageMeta, SITE_URL, midSentence } from "@/lib/catalog";

export const dynamicParams = false;

export function generateStaticParams() {
  return catalog.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const a = bySlug((await params).slug);
  if (!a) return {};
  const title = `${a.name}: ${a.line.replace(/\.$/, "")}`;
  const description = `${a.line} ${a.does.slice(0, 3).join(". ")}. Built and run for you by Agentry.`.slice(0, 300);
  return pageMeta(title, description, `/agents/${a.slug}`, a.keywords);
}

export default async function AgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const a = bySlug((await params).slug);
  if (!a) notFound();
  const group = groups.find((g) => g.key === a.group)!;
  const related = inGroup(a.group).filter((x) => x.slug !== a.slug);
  const forWho = audiences.filter((x) => x.agents.includes(a.slug));
  const url = `${SITE_URL}/agents/${a.slug}`;
  return (
    <>
      <SiteNav />
      <main id="main">
        <article className="mx-auto max-w-6xl px-4 pt-16 pb-12 sm:px-6">
          <nav aria-label="Breadcrumb" className="text-sm text-muted">
            <Link href="/" className="hover:underline">Home</Link> / <Link href="/agents" className="hover:underline">Agents</Link> /{" "}
            <Link href={`/agents#group-${group.key}`} className="hover:underline">{group.name}</Link>
          </nav>
          <div className="mt-8 grid gap-10 lg:grid-cols-[1.3fr_1fr]">
            <div>
              <p className="font-hand text-2xl text-muted">{group.hand}</p>
              <h1 className="mt-1 font-display text-4xl font-bold tracking-tight sm:text-6xl">{a.name}</h1>
              <p className="mt-4 text-2xl text-ink-soft"><span className="highlight">{a.line}</span></p>
              <a href="#demo" className="mt-8 inline-flex h-12 items-center rounded-2xl bg-ink px-6 font-semibold text-paper hover:opacity-90">Get a free demo</a>
            </div>
            <div className="rounded-3xl border-2 border-ink bg-card p-6 shadow-[6px_6px_0_0_var(--ink)] sm:p-8">
              <h2 className="font-display text-xl font-bold">What it does</h2>
              <ul className="mt-4 space-y-3">
                {a.does.map((d) => <li key={d} className="flex gap-3"><Check aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-success" />{d}</li>)}
              </ul>
              {a.note && <p className="mt-5 rounded-2xl bg-lime-soft p-4 text-sm"><span className="font-semibold">Good to know:</span> {a.note}</p>}
            </div>
          </div>
          <AgentStory slug={a.slug} name={a.name} />
          <Playground slug={a.slug} />
          <section className="mt-16 grid gap-6 rounded-3xl border-2 border-line p-6 sm:grid-cols-3 sm:p-8" aria-label="How we run it">
            <div><h2 className="font-display text-lg font-bold">Done for you</h2><p className="mt-1 text-ink-soft">We set it up with your business, connect your accounts and test it with you.</p></div>
            <div><h2 className="font-display text-lg font-bold">You stay in control</h2><p className="mt-1 text-ink-soft">It starts in approval mode: you see drafts until you trust it, and nothing goes out at night.</p></div>
            <div><h2 className="font-display text-lg font-bold">See every result</h2><p className="mt-1 text-ink-soft">One portal shows every message, booking and rupee, next to what you pay.</p></div>
          </section>
          {forWho.length > 0 && (
            <p className="mt-10 text-lg">Part of our setup for{" "}
              {forWho.map((x, i) => <span key={x.slug}>{i > 0 && (i === forWho.length - 1 ? " and " : ", ")}<Link href={`/for/${x.slug}`} className="font-semibold underline underline-offset-4">{midSentence(x.name)}</Link></span>)}.
            </p>
          )}
          {related.length > 0 && (
            <section className="mt-14">
              <h2 className="font-display text-2xl font-bold">More in {group.name.toLowerCase()}</h2>
              <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {related.map((r) => (
                  <li key={r.slug}><Link href={`/agents/${r.slug}`} className="block h-full rounded-2xl border-2 border-line px-4 py-3 hover:border-ink hover:bg-lime-soft">
                    <span className="block font-semibold">{r.name}</span><span className="block text-sm text-ink-soft">{r.line}</span></Link></li>
                ))}
              </ul>
            </section>
          )}
        </article>
        <Cta title={`See ${midSentence(a.name)} with your business name`} />
        <DemoForm />
      </main>
      <Footer />
      <SiteChat />
      <JsonLd data={[breadcrumbs([["Home", SITE_URL], ["Agents", `${SITE_URL}/agents`], [a.name, url]]),
        { "@context": "https://schema.org", "@type": "Service", name: a.name, description: `${a.line} ${a.does.join(". ")}.`, url,
          serviceType: group.name, areaServed: "IN", provider: { "@type": "Organization", name: "Agentry", url: SITE_URL } }]} />
    </>
  );
}
