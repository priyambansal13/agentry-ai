import type { Metadata } from "next";
import { AuditReport } from "@/components/audit-report";
import { DemoForm } from "@/components/demo-form";
import { Footer } from "@/components/footer";
import { SiteNav } from "@/components/site-nav";

export const metadata: Metadata = { title: "Your audit report", robots: { index: false, follow: false } };

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <SiteNav />
      <main id="main"><div className="mx-auto max-w-5xl px-4 pt-12 pb-20 sm:px-6"><AuditReport id={id} /></div><DemoForm /></main>
      <Footer />
    </>
  );
}
