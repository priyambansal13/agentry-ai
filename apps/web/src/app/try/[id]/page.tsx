import type { Metadata } from "next";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { SiteNav } from "@/components/site-nav";
import { TryChat } from "@/components/try-demo";

export const metadata: Metadata = { title: "Your AI assistant", robots: { index: false, follow: false } };

export default async function TryChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <SiteNav />
      <main id="main"><div className="mx-auto max-w-5xl px-4 pt-10 pb-20 sm:px-6"><TryChat id={id} /></div><DemoForm /></main>
      <Footer />
    </>
  );
}
