import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { TicketControls } from "@/components/tickets";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Ticket" };

type Ticket = { id: string; number: number; subject: string; summary: string | null; category: string; priority: string; status: string; assignee: string | null;
  order_ref: string | null; customer: string | null; channel: string | null; sla_due_at: string | null; first_response_at: string | null; resolved_at: string | null;
  breached_at: string | null; csat: number | null; created_at: string; conversation_id: string | null; notes: { by: string; at: string; text: string }[];
  messages: { direction: string; author: string; body: string; created_at: string }[]; order: Record<string, string | number | null> | null };
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "-");

export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("tickets");
  const { id } = await params;
  let t: Ticket;
  try {
    t = await api<Ticket>(`/org/tickets/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const { team, can_work } = await api<{ team: { id: string; name: string }[]; can_work: boolean }>("/org/tickets?status=closed", { orgId: active.id });
  const who = Object.fromEntries(team.map((m) => [m.id, m.name]));
  return (
    <div className="space-y-5">
      <Link href="/tickets" className="text-sm text-muted hover:text-ink">← Tickets</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">#{t.number} {t.subject}</h1>
          <p className="text-sm text-muted">{t.customer ?? "Unknown customer"}{t.channel ? ` · ${t.channel}` : ""} · opened {when(t.created_at)}</p></div>
        <span className="flex gap-2">{t.breached_at && t.status === "open" && <Badge tone="danger">past reply time</Badge>}<Badge>{t.priority}</Badge></span>
      </header>
      {t.summary && <Card><CardBody>{t.summary}</CardBody></Card>}
      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <Card><CardHeader><CardTitle>Conversation</CardTitle>{t.conversation_id && <Link href={`/conversations/${t.conversation_id}`} className="text-sm underline">Open and reply →</Link>}</CardHeader>
          <CardBody className="space-y-2">{t.messages.length === 0 ? <p className="text-sm text-muted">No conversation attached.</p> : t.messages.map((m, i) => (
            <div key={i} className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.direction === "in" ? "bg-paper" : "ml-auto bg-lime-soft"}`}>
              <p className="whitespace-pre-wrap">{m.body}</p><p className="mt-1 text-xs text-muted">{m.author} · {when(m.created_at)}</p></div>))}</CardBody></Card>
        <div className="space-y-5">
          {can_work && <Card><CardBody><TicketControls t={t} team={team} /></CardBody></Card>}
          <Card><CardBody className="space-y-1 text-sm">
            <p><span className="text-muted">Reply by:</span> {when(t.sla_due_at)}</p><p><span className="text-muted">First reply:</span> {when(t.first_response_at)}</p>
            <p><span className="text-muted">Resolved:</span> {when(t.resolved_at)}</p><p><span className="text-muted">Owner:</span> {t.assignee ? who[t.assignee] ?? "someone" : "nobody"}</p>
            {t.csat && <p><span className="text-muted">Rating:</span> {"★".repeat(t.csat)}</p>}</CardBody></Card>
          {t.order && <Card><CardHeader><CardTitle>Order {String(t.order.order_ref)}</CardTitle></CardHeader><CardBody className="space-y-1 text-sm">
            <p>{String(t.order.status)}{t.order.eta ? ` · arriving ${t.order.eta}` : ""}</p>{t.order.items && <p className="text-muted">{String(t.order.items)}</p>}
            {t.order.tracking_url && <a href={String(t.order.tracking_url)} target="_blank" rel="noreferrer" className="underline">Tracking ↗</a>}</CardBody></Card>}
          {t.notes.length > 0 && <Card><CardHeader><CardTitle>Notes</CardTitle></CardHeader><CardBody className="space-y-2 text-sm">{t.notes.map((n, i) => (
            <p key={i}>{n.text}<span className="block text-xs text-muted">{who[n.by] ?? "team"} · {when(n.at)}</span></p>))}</CardBody></Card>}
        </div>
      </div>
    </div>
  );
}
