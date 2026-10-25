"use client";

import { Badge, Button, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { disputeLine } from "@/app/(app)/actions";
import { type Line, money, type StatementDetail, STATUS_TONE } from "@/lib/billing";

function Evidence({ ids, d }: { ids: string[]; d: StatementDetail }) {
  const items = ids.map((i) => d.evidence[i]).filter((o): o is NonNullable<typeof o> => Boolean(o));
  if (!items.length) return null;
  return (
    <details className="mt-1 text-xs print:hidden">
      <summary className="cursor-pointer text-muted">Show the {items.length} result{items.length === 1 ? "" : "s"} behind this line</summary>
      <ul className="mt-2 space-y-1">
        {items.map((o) => (
          <li key={o.id} className="rounded-lg bg-paper px-3 py-1.5">
            {new Date(o.occurred_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} ·{" "}
            {o.kind === "appointment_booked"
              ? <>appointment booked{o.evidence.service ? `: ${String(o.evidence.service)}` : ""}{o.evidence.source ? ` (via ${o.evidence.source === "voice" ? "phone call" : String(o.evidence.source).replace("_", " ")})` : ""}</>
              : <>invoice {String(o.evidence.invoice)} paid {money(o.value, d.statement.currency)} ({o.strength} match{o.evidence.days_overdue != null ? `, ${String(o.evidence.days_overdue)} days overdue` : ""}, {Array.isArray(o.evidence.reminders) ? o.evidence.reminders.length : 0} reminder(s) before payment)</>}
            {o.evidence.mock ? <span className="ml-1 text-muted">(sample data)</span> : null}
            {o.call && (
              <div className="mt-1.5 space-y-1">
                <p className="text-muted">
                  Call{o.call.duration_seconds != null ? ` ${Math.floor(o.call.duration_seconds / 60)}:${String(o.call.duration_seconds % 60).padStart(2, "0")} min` : ""}
                  {o.call.summary ? `: ${o.call.summary}` : ""}
                </p>
                {o.call.recording && <audio controls preload="none" src={`/api/recording/${o.call.conversation_id}`} className="h-8 w-full max-w-md"><track kind="captions" /></audio>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function DisputeButton({ line }: { line: Line }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  if (line.disputed) return <Badge tone={line.dispute_resolution === "accepted" || line.dispute_resolution === "partial" ? "success" : line.dispute_resolution === "rejected" ? "neutral" : "warning"}>
    {line.dispute_resolution === "accepted" ? "removed after your dispute" : line.dispute_resolution === "partial" ? "partly credited after your dispute (see credit below)"
      : line.dispute_resolution === "rejected" ? "dispute reviewed: stays" : "disputed: under review"}</Badge>;
  return open ? (
    <form className="mt-2 space-y-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await disputeLine(line.id, reason);
      if (!r.ok) return setErr(r.error);
      router.refresh();
    }); }}>
      <Textarea aria-label="Why is this line wrong?" required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. this patient booked directly by phone" />
      <div className="flex gap-2"><Button size="sm" type="submit" disabled={pending}>Send dispute</Button><Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>Cancel</Button></div>
      {err && <p className="text-xs text-danger">{err}</p>}
    </form>
  ) : <button type="button" onClick={() => setOpen(true)} className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline print:hidden">Dispute</button>;
}

export function StatementView({ d, canDispute, company }: { d: StatementDetail; canDispute: boolean; company: string }) {
  const s = d.statement;
  const disputable = canDispute && s.status === "issued" && s.dispute_until && new Date(s.dispute_until) > new Date();
  return (
    <article className="rounded-2xl border border-line bg-card p-6 shadow-card sm:p-10 print:border-0 print:p-0 print:shadow-none">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-6">
        <div>
          <p className="font-display text-2xl font-bold">{company}</p>
          <p className="text-sm text-muted">Statement for {d.client.name}</p>
        </div>
        <div className="text-right text-sm">
          <p className="font-mono">{s.number}</p>
          <p>{new Date(s.period_start).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} – {new Date(s.period_end).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</p>
          <Badge tone={STATUS_TONE[s.status] ?? "neutral"} className="mt-1">{s.status}</Badge>
        </div>
      </header>
      <table className="mt-6 w-full text-left text-sm">
        <thead className="text-muted"><tr><th className="pb-2 font-medium">Description</th><th className="pb-2 text-right font-medium">Qty</th>
          <th className="pb-2 text-right font-medium">Rate</th><th className="pb-2 text-right font-medium">Amount</th></tr></thead>
        <tbody className="divide-y divide-line">
          {d.lines.length === 0 && <tr><td colSpan={4} className="py-6 text-center text-muted">Nothing billable in this period.</td></tr>}
          {d.lines.map((l) => (
            <tr key={l.id} className={l.disputed && !["rejected", "partial"].includes(l.dispute_resolution ?? "") ? "text-muted line-through decoration-1" : ""}>
              <td className="py-3 pr-4 align-top">
                <div>{l.description}</div>
                <Evidence ids={l.evidence} d={d} />
                {disputable && ["outcome", "commission", "overage"].includes(l.kind) && <div className="mt-1 no-underline"><DisputeButton line={l} /></div>}
                {!disputable && l.disputed && <div className="mt-1"><DisputeButton line={l} /></div>}
              </td>
              <td className="py-3 text-right align-top tabular-nums">{Number(l.quantity).toLocaleString("en-IN")}</td>
              <td className="py-3 text-right align-top tabular-nums">{money(l.unit_price, s.currency)}</td>
              <td className="py-3 text-right align-top tabular-nums">{money(l.amount, s.currency)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="text-sm">
          <tr><td colSpan={3} className="pt-4 text-right text-muted">Subtotal</td><td className="pt-4 text-right tabular-nums">{money(s.subtotal, s.currency)}</td></tr>
          {Number(s.tax) > 0 && <tr><td colSpan={3} className="text-right text-muted">{d.client.country === "IN" ? "GST" : "Tax"} ({Math.round((Number(s.tax) / Math.max(Number(s.subtotal), 1)) * 100)}%)</td><td className="text-right tabular-nums">{money(s.tax, s.currency)}</td></tr>}
          <tr><td colSpan={3} className="pt-2 text-right font-semibold">Total</td><td className="pt-2 text-right text-lg font-bold tabular-nums">{money(s.total, s.currency)}</td></tr>
        </tfoot>
      </table>
      {d.excluded.length > 0 && (
        <details className="mt-6 text-sm print:hidden">
          <summary className="cursor-pointer text-muted">{d.excluded.length} result{d.excluded.length === 1 ? " was" : "s were"} not charged, and why</summary>
          <ul className="mt-2 space-y-1 text-xs">{d.excluded.map((e, i) => (
            <li key={i} className="rounded-lg bg-paper px-3 py-1.5">{new Date(e.occurred_at).toLocaleDateString("en-IN")} · {e.kind.replace("_", " ")} {money(e.value, s.currency)}: {e.exclusion_reason}</li>
          ))}</ul>
        </details>
      )}
      <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-sm print:hidden">
        <span className="text-muted">
          {s.status === "issued" && s.dispute_until ? `You can dispute lines until ${new Date(s.dispute_until).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}.` : null}
          {s.status === "paid" && s.paid_at ? `Paid on ${new Date(s.paid_at).toLocaleDateString("en-IN")}. Thank you!` : null}
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => window.print()}>Download PDF</Button>
          {s.payment_link && s.status !== "paid" && <a href={s.payment_link} target="_blank" rel="noopener" className="inline-flex h-10 items-center rounded-xl border-2 border-ink bg-lime px-4 text-sm font-semibold text-lime-ink">Pay {money(s.total, s.currency)}</a>}
        </div>
      </footer>
    </article>
  );
}
