import { Badge, Card } from "@agentry/ui";
import { redirect } from "next/navigation";
import { formatDateTime } from "@/lib/format";
import { api, ApiError, getActiveOrg } from "@/lib/session";

export const metadata = { title: "Audit log" };

type Entry = {
  id: number; at: string; actor_type: string; action: string; target_type: string | null; target_id: string | null;
  actor_name: string | null; actor_email: string | null; ip: string | null;
};

export default async function AuditPage() {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  let items: Entry[];
  try {
    items = (await api<{ items: Entry[] }>("/org/audit?limit=100", { orgId: active.id })).items;
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Audit log</h1>
        <p className="mt-1 text-muted">Everything changed in {active.name}, by whom, and when. Agentry staff access is always shown.</p>
      </header>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted">
            <tr><th className="px-5 py-3 font-medium">When</th><th className="px-5 py-3 font-medium">Who</th><th className="px-5 py-3 font-medium">What</th><th className="px-5 py-3 font-medium">Target</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.length === 0 && <tr><td colSpan={4} className="px-5 py-8 text-center text-muted">Nothing recorded yet.</td></tr>}
            {items.map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums text-muted">{formatDateTime(e.at)}</td>
                <td className="px-5 py-3">
                  {e.actor_name ?? e.actor_type}
                  {e.actor_type === "agentry_staff" && <Badge tone="lime" className="ml-2">Agentry staff</Badge>}
                </td>
                <td className="px-5 py-3 font-mono text-xs">{e.action}</td>
                <td className="px-5 py-3 text-muted">{e.target_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
