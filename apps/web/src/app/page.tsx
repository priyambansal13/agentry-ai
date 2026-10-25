import { Agents } from "@/components/agents";
import { DemoForm } from "@/components/demo-form";
import { Faq } from "@/components/faq";
import { Footer } from "@/components/footer";
import { Hero } from "@/components/hero";
import { HowItWorks } from "@/components/how-it-works";
import { Niches } from "@/components/niches";
import { Pricing } from "@/components/pricing";
import { Problem } from "@/components/problem";
import { RoiCalculator } from "@/components/roi-calculator";
import { SiteChat } from "@/components/site-chat";
import { SiteNav } from "@/components/site-nav";

export default function Home() {
  return (
    <>
      <SiteNav />
      <main>
        <Hero />
        <Problem />
        <Agents />
        <Niches />
        <HowItWorks />
        <RoiCalculator />
        <Pricing />
        <Faq />
        <DemoForm />
      </main>
      <Footer />
      <SiteChat />
    </>
  );
}
