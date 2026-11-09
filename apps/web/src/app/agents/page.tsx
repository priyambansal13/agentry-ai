import type { Metadata } from "next";
import { AllAgents } from "@/components/all-agents";
import { Cta } from "@/components/cta";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { breadcrumbs, JsonLd } from "@/components/json-ld";
import { SiteChat } from "@/components/site-chat";
import { SiteNav } from "@/components/site-nav";
import { catalog, pageMeta, SITE_URL } from "@/lib/catalog";

const TITLE = `All ${catalog.length} AI agents for your business`;
const DESC = "WhatsApp and website chat, AI receptionist, speed-to-lead, invoice follow-up, inbox triage, bookkeeping, hiring, content, "
  + "local SEO and 13 agents for CA firms. Each built and run for you.";

export const metadata: Metadata = pageMeta(TITLE, DESC, "/agents");

export default function AgentsPage() {
  return (
    <>
      <SiteNav />
      <main id="main">
        <header className="mx-auto max-w-6xl px-4 pt-16 sm:px-6">
          <nav aria-label="Breadcrumb" className="text-sm text-muted"><a href="/" className="hover:underline">Home</a> / Agents</nav>
          <p className="mt-6 font-hand text-2xl text-muted">meet the team</p>
          <h1 className="mt-1 max-w-4xl font-display text-4xl font-bold tracking-tight sm:text-6xl">
            {catalog.length} AI agents. <span className="highlight">Pick the boring job.</span>
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-ink-soft">{DESC}</p>
        </header>
        <AllAgents heading={false} />
        <Cta />
        <DemoForm />
      </main>
      <Footer />
      <SiteChat />
      <JsonLd data={[breadcrumbs([["Home", SITE_URL], ["Agents", `${SITE_URL}/agents`]]),
        { "@context": "https://schema.org", "@type": "ItemList", name: TITLE,
          itemListElement: catalog.map((a, i) => ({ "@type": "ListItem", position: i + 1, name: a.name, url: `${SITE_URL}/agents/${a.slug}` })) }]} />
    </>
  );
}
