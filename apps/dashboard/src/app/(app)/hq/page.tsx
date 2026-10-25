import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { DEMO_STATUS, statusLabels } from "@/lib/format";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Agentry HQ" };

type OrgRow = {
  id: string; name: string; slug: string; status: string | null; industry_pack: string | null; country: string | null;
  members: number; automations: number; steps_done: number; steps_total: number; blockers: string | null;
};
type Demo = { id: string; name: string; email: string; company: string | null; niche: string | null; status: string; created_at: string };

export default async function HqPage() {
  const me = await getMe();
  if (!me.is_staff) redirect("/home");
  const [orgs, demos] = await Promise.all([
    api<{ items: OrgRow[] }>("/hq/orgs"),
    api<{ items: Demo[] }>("/hq/demo-requests"),
  ]);
  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-hand text-xl text-muted">Agentry HQ</p>
          <h1 className="font-display text-3xl font-bold tracking-tight">All clients</h1>
        </div>
        <Link href="/hq/new" className="inline-flex h-11 items-center rounded-xl border-2 border-ink bg-lime px-5 font-semibold text-lime-ink">+ New client</Link>
      </header>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted">
            <tr>
              <th className="px-5 py-3 font-medium">Client</th><th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Pack</th><th className="px-5 py-3 text-right font-medium">Agents</th>
              <th className="px-5 py-3 text-right font-medium">Team</th><th className="px-5 py-3 font-medium">Onboarding</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {orgs.items.map((o) => (
              <tr key={o.id}>
                <td className="px-5 py-3"><Link href={`/hq/${o.id}`} className="font-medium underline-offset-4 hover:underline">{o.name}</Link><div className="text-xs text-muted">{o.country}</div></td>
                <td className="px-5 py-3"><Badge tone={statusLabels[o.status ?? ""]?.tone ?? "neutral"}>{statusLabels[o.status ?? ""]?.label ?? "Not set up"}</Badge></td>
                <td className="px-5 py-3 font-mono text-xs text-muted">{o.industry_pack ?? "—"}</td>
                <td className="px-5 py-3 text-right tabular-nums">{o.automations}</td>
                <td className="px-5 py-3 text-right tabular-nums">{o.members}</td>
                <td className="px-5 py-3">
                  <span className="tabular-nums">{o.steps_done}/{o.steps_total}</span>
                  {o.blockers && <span className="ml-2 text-xs text-warning">⚠ {o.blockers}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Demo requests</h2>
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted">
              <tr><th className="px-5 py-3 font-medium">Received</th><th className="px-5 py-3 font-medium">Name</th><th className="px-5 py-3 font-medium">Company</th><th className="px-5 py-3 font-medium">Niche</th><th className="px-5 py-3 font-medium">Status</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {demos.items.length === 0 && <tr><td colSpan={5} className="px-5 py-8 text-center text-muted">No demo requests yet.</td></tr>}
              {demos.items.map((d) => (
                <tr key={d.id}>
                  <td className="whitespace-nowrap px-5 py-3 tabular-nums text-muted">{new Date(d.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</td>
                  <td className="px-5 py-3"><Link href={`/hq/demo-requests/${d.id}`} className="font-medium underline-offset-4 hover:underline">{d.name}</Link><div className="text-xs text-muted">{d.email}</div></td>
                  <td className="px-5 py-3">{d.company ?? "—"}</td>
                  <td className="px-5 py-3 text-muted">{d.niche?.replaceAll("_", " ") ?? "—"}</td>
                  <td className="px-5 py-3"><Badge tone={DEMO_STATUS[d.status]?.tone ?? "neutral"}>{DEMO_STATUS[d.status]?.label ?? d.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}
