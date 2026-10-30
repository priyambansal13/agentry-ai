import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@agentry/ui";
import { redirect } from "next/navigation";
import type { RoutingRule } from "@/app/(app)/actions";
import type { Assignee } from "@/components/approval-card";
import { ClientRouting } from "@/components/card-routing";
import { InvoiceActions, InvoiceImport } from "@/components/invoice-tools";
import { formatMetric } from "@/lib/format";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Invoices" };

type Inv = {
  id: string; number: string; currency: string; amount: number; balance: number; due_on: string; status: string; days_overdue: number;
  contact_id: string | null; contact_name: string | null; company: string | null; email: string | null; contactable: boolean; reminders: string | null; reminders_sent: number | null;
  reminders_awaiting: number | null;
  paused_until: string | null; stop_reason: string | null; notes: string | null;
};
type Data = { items: Inv[]; ageing: Record<string, number | string | null>[]; recovered_30d: number };

const STATUS: Record<string, "success" | "warning" | "danger" | "neutral" | "lime"> = {
  paid: "success", partially_paid: "lime", open: "neutral", disputed: "danger", written_off: "neutral", void: "neutral",
};
const BUCKETS: [string, string][] = [["not_due", "Not due"], ["d1_7", "1–7 days"], ["d8_14", "8–14"], ["d15_30", "15–30"], ["d30_plus", "30+"]];

export default async function InvoicesPage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  await requirePage("invoices");
  if (!active) redirect("/home");
  let d: Data;
  try {
    d = await api<Data>("/org/invoices", { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  const canAct = me.is_staff || can(active.role, "invoice", "act");
  const canRoute = me.is_staff || can(active.role, "automation", "configure");
  const [rules, people] = canRoute ? await Promise.all([
    api<{ items: RoutingRule[] }>("/org/card-routing", { orgId: active.id }).then((r) => r.items),
    api<{ items: Assignee[] }>("/org/assignees", { orgId: active.id }).then((r) => r.items.filter((p) => p.invoices)),
  ]) : [[], []];
  const handledBy = new Map(rules.filter((r) => r.scope === "contact").map((r) => [r.key, r.assign_name]));
  const clients = [...new Map(d.items.filter((i) => i.contact_id).map((i) => [i.contact_id!, i.company ?? i.contact_name ?? i.email ?? "?"])).entries()]
    .map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  const currency = d.items[0]?.currency ?? "INR";
  const ageing = d.ageing.find((a) => a.currency === currency) ?? {};
  const outstanding = BUCKETS.reduce((s, [k]) => s + Number(ageing[k] ?? 0), 0);
  const overdue = outstanding - Number(ageing.not_due ?? 0);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Invoices</h1>
        <p className="mt-1 text-muted">What&apos;s owed to {active.name}, how late it is, and where each reminder sequence stands.</p>
      </header>
      <section className="grid gap-4 sm:grid-cols-3" aria-label="Summary">
        <Stat label="Outstanding" value={formatMetric(outstanding, "currency", currency)} />
        <Stat label="Overdue" value={formatMetric(overdue, "currency", currency)} />
        <Stat label="Recovered, last 30 days" value={formatMetric(d.recovered_30d, "currency", currency)} />
      </section>
      <Card>
        <CardHeader><CardTitle>Ageing</CardTitle><span className="text-sm text-muted">balance by days overdue</span></CardHeader>
        <CardBody>
          <div className="flex h-9 w-full overflow-hidden rounded-lg border border-line" role="img"
            aria-label={BUCKETS.map(([k, l]) => `${l}: ${formatMetric(Number(ageing[k] ?? 0), "currency", currency)}`).join(", ")}>
            {BUCKETS.map(([k, l], i) => {
              const v = Number(ageing[k] ?? 0);
              return v > 0 ? <div key={k} title={`${l}: ${formatMetric(v, "currency", currency)}`} style={{ width: `${(v / (outstanding || 1)) * 100}%`, opacity: 0.35 + i * 0.16 }}
                className="h-full border-r-2 border-card bg-[var(--series-1)] last:border-r-0" /> : null;
            })}
          </div>
          <dl className="mt-3 grid grid-cols-5 gap-2 text-sm">
            {BUCKETS.map(([k, l]) => <div key={k}><dt className="text-muted">{l}</dt><dd className="font-semibold">{formatMetric(Number(ageing[k] ?? 0), "currency", currency)}</dd></div>)}
          </dl>
        </CardBody>
      </Card>
      {canAct && <Card className="p-5"><InvoiceImport /></Card>}
      {canRoute && clients.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Who handles each client</CardTitle><span className="text-sm text-muted">every card for that client goes to them</span></CardHeader>
          <CardBody><ClientRouting clients={clients} people={people} rules={rules} /></CardBody>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr>
            <th className="px-4 py-3 font-medium">Invoice</th><th className="px-4 py-3 font-medium">Customer</th>
            <th className="px-4 py-3 text-right font-medium">Balance</th><th className="px-4 py-3 font-medium">Due</th>
            <th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">Reminders</th><th className="px-4 py-3" />
          </tr></thead>
          <tbody className="divide-y divide-line">
            {d.items.length === 0 && <tr><td colSpan={7} className="px-4 py-8 text-center text-muted">No invoices yet. Import a file above.</td></tr>}
            {d.items.map((i) => (
              <tr key={i.id} className="align-top">
                <td className="px-4 py-3 font-mono text-xs">{i.number}</td>
                <td className="px-4 py-3"><div className="font-medium">{i.company ?? i.contact_name ?? "—"}</div><div className="text-xs text-muted">{i.email}</div>
                  {i.contact_id && handledBy.get(i.contact_id) && <div className="text-xs text-muted">handled by {handledBy.get(i.contact_id)}</div>}
                  {!i.contactable && ["open", "partially_paid"].includes(i.status) && <div className="mt-1"><Badge tone="warning">no email or phone: no reminders</Badge></div>}
                  {i.notes && <div className="mt-1 max-w-xs text-xs whitespace-pre-line text-ink-soft">{i.notes.split("\n").slice(-1)[0]}</div>}</td>
                <td className="px-4 py-3 text-right tabular-nums">{formatMetric(Number(i.balance), "currency", i.currency)}</td>
                <td className="px-4 py-3 whitespace-nowrap">{new Date(i.due_on).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  {i.days_overdue > 0 && i.status !== "paid" && <div className="text-xs text-danger">{i.days_overdue} days late</div>}</td>
                <td className="px-4 py-3"><Badge tone={STATUS[i.status] ?? "neutral"}>{i.status.replace("_", " ")}</Badge></td>
                <td className="px-4 py-3 text-xs">
                  {i.reminders ? <>{i.reminders}{i.reminders === "paused" && i.paused_until ? ` until ${new Date(i.paused_until).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
                    <div className="text-muted">{i.reminders_sent ?? 0} sent{i.reminders_awaiting ? ` · ${i.reminders_awaiting} awaiting your OK` : ""}
                      {i.stop_reason && i.stop_reason !== "all steps sent" ? ` · ${i.stop_reason}` : ""}</div></> : <span className="text-muted">—</span>}
                </td>
                <td className="px-4 py-3">{canAct && <InvoiceActions id={i.id} balance={Number(i.balance)} reminders={i.reminders} status={i.status} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
