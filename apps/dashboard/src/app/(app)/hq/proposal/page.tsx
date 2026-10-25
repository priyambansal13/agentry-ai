import { redirect } from "next/navigation";
import type { DemoRequest } from "@/components/demo-request";
import { ProposalBuilder, type ProposalPrefill } from "@/components/proposal-builder";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Proposal builder · Agentry HQ" };

export default async function ProposalPage({ searchParams }: { searchParams: Promise<{ request?: string }> }) {
  const [me, { request }] = await Promise.all([getMe(), searchParams]);
  if (!me.is_staff) redirect("/home");
  const orgs = await api<{ items: { id: string; name: string }[] }>("/hq/orgs");
  // opened from a demo request: address it to them and send it to their email
  const d = request ? await api<DemoRequest>(`/hq/demo-requests/${request}`).catch(() => null) : null;
  const prefill: ProposalPrefill | undefined = d
    ? { request: d.id, business: d.company ?? d.name, contact: d.name, email: d.email, niche: d.niche ?? "" } : undefined;
  return <ProposalBuilder orgs={orgs.items.map((o) => ({ id: o.id, name: o.name }))} preparedBy={me.user.name} prefill={prefill} />;
}
