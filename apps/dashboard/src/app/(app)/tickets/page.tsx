import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { ImportOrders, NewTicket } from "@/components/tickets";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Tickets" };

type T = { id: string; number: number; subject: string; category: string; priority: string; status: string; customer: string | null; channel: string | null;
  sla_due_at: string | null; overdue: boolean; breached_at: string | null; csat: number | null; created_at: string };
type D = { items: T[]; stats: { active: number; breached: number; resolved_30d: number; csat: number | null; median_first_reply_min: number | null };
  can_work: boolean; orders: { count: number; updated: string | null } };
const TONE: Record<string, "danger" | "warning" | "neutral" | "success"> = { urgent: "danger", high: "warning", normal: "neutral", low: "neutral" };
const STATUS: Record<string, string> = { open: "Open", waiting_customer: "Waiting for customer", resolved: "Resolved", closed: "Closed" };
const due = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");

export default async function TicketsPage({ searchParams }: { searchParams: Promise<{ status?: string; mine?: string; q?: string }> }) {
  const active = await requirePage("tickets");
  const sp = await searchParams;
  const status = sp.status ?? "active";
  const q = new URLSearchParams({ ...(status !== "all" ? { status } : {}), ...(sp.mine ? { mine: "true" } : {}), ...(sp.q ? { q: sp.q } : {}) });
  const d = await api<D>(`/org/tickets?${q}`, { orgId: active.id });
  const tab = (k: string, label: string) => <Link href={`/tickets?status=${k}`} className={`rounded-xl border-2 px-3 py-1.5 ${status === k ? "border-ink bg-lime-soft" : "border-line"}`}>{label}</Link>;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Tickets</h1>
        <p className="mt-1 max-w-3xl text-muted">Customer problems from WhatsApp, website chat and hand-offs, each with an owner and a reply-by time. &quot;Where&apos;s my order?&quot; is answered from your order sheet.</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-5">
        {[["Open", d.stats.active], ["Past reply time", d.stats.breached], ["Resolved (30 days)", d.stats.resolved_30d],
          ["First reply (median)", d.stats.median_first_reply_min != null ? `${d.stats.median_first_reply_min} min` : "-"], ["Rating", d.stats.csat != null ? `${d.stats.csat} / 5` : "-"]].map(([k, v]) => (
          <Card key={String(k)}><CardBody><p className="text-sm text-muted">{k}</p><p className="text-2xl font-semibold">{v}</p></CardBody></Card>))}
      </div>
      <div className="flex flex-wrap gap-2 text-sm">{tab("active", "Open")}{tab("resolved", "Resolved")}{tab("all", "All")}
        <Link href={`/tickets?status=${status}${sp.mine ? "" : "&mine=1"}`} className={`rounded-xl border-2 px-3 py-1.5 ${sp.mine ? "border-ink bg-lime-soft" : "border-line"}`}>Mine</Link></div>
      <Card><CardBody className="p-0">
        {d.items.length === 0 ? <p className="p-5 text-muted">No tickets here.</p> : (
          <ul className="divide-y divide-line">{d.items.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0"><Link href={`/tickets/${t.id}`} className="font-semibold hover:underline">#{t.number} {t.subject}</Link>
                <p className="text-xs text-muted">{t.customer ?? "Unknown"} · {t.category}{t.channel ? ` · ${t.channel}` : ""}{t.sla_due_at && t.status === "open" ? ` · reply by ${due(t.sla_due_at)}` : ""}</p></div>
              <span className="flex items-center gap-2">{(t.overdue || t.breached_at) && t.status === "open" && <Badge tone="danger">late</Badge>}
                <Badge tone={TONE[t.priority]}>{t.priority}</Badge><Badge tone={t.status === "resolved" ? "success" : "neutral"}>{STATUS[t.status]}</Badge>
                {t.csat ? <span className="text-sm">{"★".repeat(t.csat)}</span> : null}</span>
            </li>))}</ul>)}
      </CardBody></Card>
      {d.can_work && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Open a ticket</CardTitle></CardHeader><CardBody><NewTicket /></CardBody></Card>
          <Card><CardHeader><CardTitle>Order sheet</CardTitle><span className="text-sm text-muted">{d.orders.count} orders</span></CardHeader><CardBody className="space-y-2">
            <p className="text-sm text-muted">CSV or Excel with: Order ID, Customer, Mobile, Email, Status, Items, Amount, Expected delivery, Tracking link. Upload it again whenever it changes;
              customers only ever see their own order.</p><ImportOrders /></CardBody></Card>
        </div>)}
    </div>
  );
}
