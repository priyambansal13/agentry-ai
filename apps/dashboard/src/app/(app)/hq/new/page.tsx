import Link from "next/link";
import { redirect } from "next/navigation";
import type { DemoRequest } from "@/components/demo-request";
import { type CatalogItem, NewClientForm, type Prefill } from "@/components/new-client-form";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "New client · Agentry HQ" };

export default async function NewClientPage({ searchParams }: { searchParams: Promise<{ from?: string }> }) {
  const [me, { from }] = await Promise.all([getMe(), searchParams]);
  if (!me.is_staff) redirect("/home");
  const { automations } = await api<{ automations: CatalogItem[] }>("/hq/catalog");
  // "Convert to client" from a demo request: start from what they told us and the agents their industry starts with
  let prefill: Prefill | undefined;
  if (from) {
    const d = await api<DemoRequest>(`/hq/demo-requests/${from}`).catch(() => null);
    if (d) {
      const packs = await api<{ items: { key: string; featured: string[] }[] }>("/hq/packs");
      const featured = packs.items.find((p) => p.key === d.suggested_pack)?.featured ?? [];
      const available = new Set(automations.filter((a) => a.available).map((a) => a.key));
      prefill = { request: d.id, name: d.company ?? d.name, website: d.website ?? "", owner: { name: d.name, email: d.email },
                  automations: featured.filter((k) => available.has(k)).slice(0, 2) };
    }
  }
  return (
    <div className="space-y-6">
      <Link href="/hq" className="text-sm text-muted hover:text-ink">← All clients</Link>
      <header>
        <p className="font-hand text-xl text-muted">Agentry HQ</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">New client</h1>
        <p className="mt-1 text-muted">Create the business, switch on what they bought, invite the owner and set the price.</p>
      </header>
      {prefill && <p className="rounded-2xl border-2 border-ink bg-lime px-4 py-3 text-sm text-lime-ink">From the demo request of {prefill.owner.name}: details filled in. Check the agents and the plan.</p>}
      <NewClientForm catalog={automations} prefill={prefill} />
    </div>
  );
}
