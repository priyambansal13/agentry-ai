import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { NewDoc } from "@/components/docs";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Documents" };

export default async function DocsPage() {
  const active = await requirePage("docs");
  const d = await api<{ items: { id: string; kind: string; title: string; status: string; created_at: string }[]; can_edit: boolean }>("/org/docs", { orgId: active.id });
  const KIND: Record<string, string> = { sop: "SOP", proposal: "Proposal", checklist: "Checklist" };
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Documents</h1>
        <p className="mt-1 max-w-3xl text-muted">Describe a process, a client or a routine: get a step-by-step SOP with a flowchart, a proposal, or a checklist. Prices and dates
          only come from what you write; anything missing is left as [to confirm].</p>
      </header>
      {d.can_edit && <Card><CardHeader><CardTitle>New document</CardTitle></CardHeader><CardBody><NewDoc /></CardBody></Card>}
      <Card><CardBody className="p-0">{d.items.length === 0 ? <p className="p-5 text-muted">Nothing yet.</p> : (
        <ul className="divide-y divide-line">{d.items.map((x) => (
          <li key={x.id} className="flex items-center justify-between gap-2 px-4 py-3"><Link href={`/docs/${x.id}`} className="font-medium hover:underline">{x.title}</Link>
            <span className="flex gap-2"><Badge>{KIND[x.kind]}</Badge><Badge tone={x.status === "final" ? "success" : x.status === "needs_attention" ? "warning" : "neutral"}>{x.status.replace("_", " ")}</Badge></span></li>))}</ul>)}
      </CardBody></Card>
    </div>
  );
}
