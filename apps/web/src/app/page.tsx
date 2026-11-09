import { AllAgents } from "@/components/all-agents";
import { Agents } from "@/components/agents";
import { DemoForm } from "@/components/demo-form";
import { Faq } from "@/components/faq";
import { Footer } from "@/components/footer";
import { Hero } from "@/components/hero";
import { HowItWorks } from "@/components/how-it-works";
import { Included } from "@/components/included";
import { Industries } from "@/components/industries";
import { faqPage, JsonLd } from "@/components/json-ld";
import { Pricing } from "@/components/pricing";
import { Problem } from "@/components/problem";
import { RoiCalculator } from "@/components/roi-calculator";
import { SiteChat } from "@/components/site-chat";
import { SiteNav } from "@/components/site-nav";
import { catalog, SITE_URL } from "@/lib/catalog";
import { faqs } from "@/lib/content";

const SERVICE = {
  "@context": "https://schema.org", "@type": "Service", name: "Agentry AI agents, done for you", provider: { "@type": "Organization", name: "Agentry", url: SITE_URL },
  areaServed: "IN", serviceType: "AI automation agency",
  hasOfferCatalog: { "@type": "OfferCatalog", name: "AI agents",
    itemListElement: catalog.map((a) => ({ "@type": "Offer", itemOffered: { "@type": "Service", name: a.name, description: a.line, url: `${SITE_URL}/agents/${a.slug}` } })) },
};

export default function Home() {
  return (
    <>
      <SiteNav />
      <main id="main">
        <Hero />
        <Problem />
        <AllAgents />
        <Industries />
        <Agents />
        <HowItWorks />
        <Included />
        <RoiCalculator />
        <Pricing />
        <Faq />
        <DemoForm />
      </main>
      <Footer />
      <SiteChat />
      <JsonLd data={[SERVICE, faqPage(faqs)]} />
    </>
  );
}
