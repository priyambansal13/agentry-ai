import { ProposalDocument, type ProposalSnapshot } from "@agentry/ui";
import { notFound } from "next/navigation";
import { PrintButton } from "@/components/print-button";

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

export const dynamic = "force-dynamic";
export const metadata = { title: "Your Agentry proposal", robots: { index: false, follow: false } };

/** A proposal sent from Agentry HQ: the exact snapshot the client was sent, behind a private link. */
export default async function ProposalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const r = await fetch(`${API}/public/proposals/${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!r.ok) notFound();
  const { snapshot, reply_to: replyTo } = (await r.json()) as { snapshot: ProposalSnapshot; reply_to: string };
  const subject = encodeURIComponent(`Re: Agentry proposal for ${snapshot.business}`);
  return (
    <main className="mx-auto max-w-4xl px-4 py-8 sm:py-12">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <p className="text-sm text-muted">Proposal for {snapshot.business}</p>
        <div className="flex gap-2">
          <PrintButton className="h-10 rounded-xl border-2 border-ink px-4 text-sm font-semibold hover:bg-lime-soft" />
          <a href={`mailto:${replyTo}?subject=${subject}`} className="inline-flex h-10 items-center rounded-xl border-2 border-ink bg-lime px-4 text-sm font-semibold text-lime-ink">
            Reply to get started
          </a>
        </div>
      </div>
      <article className="rounded-3xl border-2 border-line bg-card p-6 sm:p-12 print:border-0 print:p-0">
        <ProposalDocument p={snapshot} />
      </article>
    </main>
  );
}
