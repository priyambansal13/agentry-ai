import type { Metadata } from "next";
import { Footer } from "@/components/footer";
import { SiteNav } from "@/components/site-nav";
import { StartDone } from "@/components/start";

export const metadata: Metadata = { title: "Payment received", robots: { index: false, follow: false } };

export default async function DonePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (<><SiteNav /><main id="main" className="mx-auto max-w-2xl px-4 py-16 sm:px-6"><StartDone id={id} /></main><Footer /></>);
}
