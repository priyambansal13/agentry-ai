import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { type CaClient, type CaMeta, ClientForm, ImportClients } from "@/components/ca";
import { PortalSettingsForm, type PortalSettings } from "@/components/ca-portal";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Clients" };

export default async function CaClientsPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const active = await requirePage("ca-clients");
  const { q } = await searchParams;
  const [meta, { items }] = await Promise.all([
    api<CaMeta>("/org/ca/meta", { orgId: active.id }),
    api<{ items: CaClient[] }>(`/org/ca/clients${q ? `?q=${encodeURIComponent(q)}` : ""}`, { orgId: active.id }),
  ]);
  const portal = meta.enabled.includes("ca_filing_tracker") ? await api<PortalSettings>("/org/ca/portal", { orgId: active.id }) : null;
  const who = Object.fromEntries(meta.team.map((t) => [t.id, t.name]));
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Clients</h1>
          <p className="mt-1 text-muted">The people and businesses you file for. Their profile decides which documents are asked for and which due dates apply.</p>
        </div>
        <form action="/ca-clients"><input name="q" defaultValue={q ?? ""} placeholder="Name, PAN or phone" className="h-10 rounded-xl border-2 border-line bg-card px-3 text-sm" /></form>
      </header>
      <Card>
        <CardBody className="p-0">
          {items.length === 0 ? <p className="p-5 text-muted">{q ? "Nobody matches." : "No clients yet: add one below or import your list."}</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-muted"><tr><th className="p-3">Name</th><th className="p-3">PAN</th><th className="hidden p-3 sm:table-cell">Phone</th>
                <th className="hidden p-3 md:table-cell">Looked after by</th><th className="p-3 text-right">Open filings</th></tr></thead>
              <tbody className="divide-y divide-line">{items.map((c) => (
                <tr key={c.id}><td className="p-3"><Link href={`/ca-clients/${c.id}`} className="font-semibold hover:underline">{c.name}</Link>
                  <span className="ml-2 text-xs text-muted">{c.kind}</span></td>
                  <td className="p-3 font-mono text-xs">{c.pan ?? "-"}</td><td className="hidden p-3 sm:table-cell">{c.phone ?? "-"}</td>
                  <td className="hidden p-3 md:table-cell">{c.assignee ? who[c.assignee] ?? "-" : "-"}</td><td className="p-3 text-right">{c.open_filings}</td></tr>))}
              </tbody>
            </table>)}
        </CardBody>
      </Card>
      {meta.can_work && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardHeader><CardTitle>Add a client</CardTitle></CardHeader><CardBody><ClientForm meta={meta} /></CardBody></Card>
          <Card><CardHeader><CardTitle>Import your list</CardTitle></CardHeader><CardBody><ImportClients /></CardBody></Card>
        </div>
      )}
      {portal && <Card><CardHeader><CardTitle>Client portal</CardTitle></CardHeader>
        <CardBody><PortalSettingsForm s={portal} canEdit={["owner", "manager", "agentry_staff"].includes(active.role)} /></CardBody></Card>}
    </div>
  );
}
