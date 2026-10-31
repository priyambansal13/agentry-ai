"use client";

import { Badge, Button, buttonClasses, Card, Textarea } from "@agentry/ui";
import Link from "next/link";
import { useState, useTransition } from "react";
import { assignApproval, confirmPayment, decideApproval, snoozeApproval } from "@/app/(app)/actions";
import { approvalKinds, timeAgo } from "@/lib/format";

export type Approval = {
  id: string; kind: string; title: string; body: string | null; created_at: string; conversation_id: string | null;
  channel: string | null; last_inbound: string | null; automation_key: string | null; snoozed_until?: string | null;
  assigned_to?: string | null; assigned_name?: string | null; channel_problem?: string | null;
  payload: { category?: string; urgent?: boolean; kb_sources?: string[]; ai_failed?: boolean; phone?: string | null;
             suspicious?: boolean; risk?: string[]; language?: string | null; nudge?: boolean;
             invoice_id?: string; payment_id?: string; utr?: string | null; withdrawn?: string; held_because?: string };
};

export type SavedReply = { id: string; title: string; body: string };
export type Assignee = { id: string; name: string; role: string; conversations: boolean; invoices: boolean };
const LANG: Record<string, string> = { hi: "Hindi", mr: "Marathi", ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam", bn: "Bengali", gu: "Gujarati", pa: "Punjabi", ur: "Urdu", or: "Odia" };

/** Snooze choices, in the viewer's local time. */
function snoozeTimes(): [string, Date][] {
  const now = new Date();
  const at9 = (d: Date) => { const x = new Date(d); x.setHours(9, 0, 0, 0); return x; };
  const tomorrow = at9(new Date(now.getTime() + 86400000));
  const monday = at9(new Date(now.getTime() + ((8 - now.getDay()) % 7 || 7) * 86400000));
  return [["1 hour", new Date(now.getTime() + 3600000)], ["3 hours", new Date(now.getTime() + 3 * 3600000)],
          ["Tomorrow 9 am", tomorrow], ["Monday 9 am", monday]];
}

export type OpenInvoice = { id: string; number: string; balance: number; company: string | null };

export function ApprovalCard({ a, canAct, templates = [], assignees = [], openInvoices = [] }: { a: Approval; canAct: boolean; templates?: SavedReply[];
                                                                                                assignees?: Assignee[]; openInvoices?: OpenInvoice[] }) {
  const [matchTo, setMatchTo] = useState("");
  const [body, setBody] = useState(a.body ?? "");
  const [pending, start] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const isDraft = a.kind === "reply_draft" || a.kind === "outbound_draft";

  function act(action: "approve" | "reject" | "resolve") {
    start(async () => {
      const r = await decideApproval(a.id, action, isDraft ? body : undefined);
      setResult(r.ok ? { ok: true, text: action === "approve" ? "Sent" : action === "reject" ? "Discarded" : a.kind === "callback" ? "Called back" : "Marked as handled" }
                     : { ok: false, text: r.error });
    });
  }

  function snooze(until: Date | null) {
    start(async () => {
      const r = await snoozeApproval(a.id, until ? until.toISOString() : null);
      setResult(r.ok ? { ok: true, text: until ? `Snoozed until ${until.toLocaleString("en-IN", { weekday: "short", hour: "numeric", minute: "2-digit" })}` : "Back in the queue" }
                     : { ok: false, text: r.error });
    });
  }

  if (result?.ok) {
    return <Card className="p-4 text-sm text-muted">✓ {result.text}: {a.title}</Card>;
  }
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={a.payload?.urgent ? "danger" : a.kind === "handoff" ? "warning" : "lime"}>
          {a.payload?.urgent ? "Urgent · " : ""}{approvalKinds[a.kind] ?? a.kind}
        </Badge>
        {a.payload?.category && <Badge>{a.payload.category}</Badge>}
        {a.payload?.language && LANG[a.payload.language] && <Badge>in {LANG[a.payload.language]}</Badge>}
        {a.assigned_name && <Badge tone="lime">for {a.assigned_name}</Badge>}
        <span className="ml-auto text-xs text-muted">{timeAgo(a.created_at)}</span>
      </div>
      <h3 className="mt-3 font-semibold">{a.title}</h3>
      {a.payload?.suspicious && (
        <div role="alert" className="mt-3 rounded-xl border-2 border-danger bg-danger/5 px-4 py-3 text-sm">
          <p className="font-semibold text-danger">⚠ This email may be fraud. Don&apos;t pay or share codes before checking by phone.</p>
          {a.payload.risk?.length ? <ul className="mt-1 list-disc pl-5 text-ink-soft">{a.payload.risk.map((r) => <li key={r}>{r}</li>)}</ul> : null}
        </div>
      )}
      {a.last_inbound && (
        <blockquote className="mt-3 max-h-32 overflow-y-auto rounded-xl border-l-4 border-line bg-paper px-4 py-3 text-sm whitespace-pre-wrap text-ink-soft">
          {a.last_inbound}
        </blockquote>
      )}
      {a.payload?.held_because && <p className="mt-2 text-xs text-muted">Waiting for you because: {a.payload.held_because}</p>}
      {a.channel_problem && (
        <p role="alert" className="mt-3 rounded-xl border-2 border-warning px-4 py-3 text-sm text-warning">
          This can&apos;t be sent: {a.channel_problem}. Discard it, or fix that in Settings → Connections first.
        </p>
      )}
      {isDraft ? (
        <div className="mt-4">
          <label htmlFor={`draft-${a.id}`} className="mb-1.5 block text-sm font-medium">
            {a.kind === "outbound_draft" ? "Message the agent wants to send, edit before approving" : "AI draft, edit before sending"}
          </label>
          {a.payload?.ai_failed && <p role="alert" className="mb-2 rounded-lg border border-warning px-3 py-2 text-sm text-warning">The AI couldn&apos;t write this reply (its models were unavailable). Write the reply yourself; Agentry has been alerted.</p>}
          {canAct && templates.length > 0 && (
            <select aria-label="Insert a saved reply" className="mb-2 h-9 rounded-lg border-2 border-line bg-card px-2 text-sm" value=""
              onChange={(e) => { const t = templates.find((x) => x.id === e.target.value); if (t) setBody(t.body); }}>
              <option value="">Use a saved reply…</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          )}
          <Textarea id={`draft-${a.id}`} value={body} onChange={(e) => setBody(e.target.value)} rows={Math.min(12, body.split("\n").length + 2)} disabled={!canAct} />
          {a.payload?.kb_sources && a.payload.kb_sources.length > 0 && (
            <p className="mt-1.5 text-xs text-muted">Used knowledge: {a.payload.kb_sources.filter(Boolean).join(", ")}</p>
          )}
          {body.includes("[") && <p className="mt-1.5 text-xs text-warning">Fill in the [bracketed] parts before sending.</p>}
        </div>
      ) : a.body ? <p className="mt-3 text-sm text-ink-soft">{a.body}</p> : null}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {canAct && isDraft && <Button onClick={() => act("approve")} disabled={pending || body.includes("[") || !!a.channel_problem}>Approve &amp; send</Button>}
        {canAct && isDraft && <Button variant="secondary" onClick={() => act("reject")} disabled={pending}>Discard</Button>}
        {canAct && a.kind === "handoff" && a.conversation_id && (
          <Link href={`/conversations/${a.conversation_id}`} className={buttonClasses("primary", "md")}>Reply now</Link>
        )}
        {canAct && a.kind === "payment_review" && !a.payload?.payment_id && a.payload?.invoice_id && (
          <Button disabled={pending} onClick={() => start(async () => {
            const r = await confirmPayment(a.id);
            setResult(r.ok ? { ok: true, text: "Payment confirmed: the invoice is closed" } : { ok: false, text: r.error });
          })}>Confirm paid</Button>
        )}
        {canAct && a.kind === "payment_review" && a.payload?.payment_id && openInvoices.length > 0 && (
          <span className="inline-flex items-center gap-2">
            <select aria-label="Which invoice is this payment for?" className="h-10 rounded-xl border-2 border-line bg-card px-2 text-sm" value={matchTo} onChange={(e) => setMatchTo(e.target.value)}>
              <option value="">Which invoice?</option>
              {openInvoices.map((i) => <option key={i.id} value={i.id}>{i.number} · {i.company ?? ""} · {i.balance.toLocaleString("en-IN")}</option>)}
            </select>
            <Button disabled={pending || !matchTo} onClick={() => start(async () => {
              const r = await confirmPayment(a.id, matchTo);
              setResult(r.ok ? { ok: true, text: "Matched: the invoice is updated" } : { ok: false, text: r.error });
            })}>Match</Button>
          </span>
        )}
        {canAct && a.kind === "escalation" && a.payload?.phone && <a href={`tel:${a.payload.phone}`} className={buttonClasses("primary", "md")}>Call {a.payload.phone}</a>}
        {canAct && a.kind === "callback" && (a.payload?.phone
          ? <a href={`tel:${a.payload.phone}`} className={buttonClasses("primary", "md")}>Call {a.payload.phone}</a>
          : <span className="text-sm text-muted">No number captured: check the call recording.</span>)}
        {canAct && !isDraft && <Button variant={a.kind === "handoff" || a.kind === "callback" ? "secondary" : "primary"} onClick={() => act("resolve")} disabled={pending}>{a.kind === "callback" ? "Done, called back" : "Mark handled"}</Button>}
        {canAct && assignees.length > 1 && (
          <select aria-label="Assign to" className="h-10 rounded-xl border-2 border-line bg-card px-2 text-sm" value={a.assigned_to ?? ""} disabled={pending}
            onChange={(e) => start(async () => {
              const r = await assignApproval(a.id, e.target.value || null);
              if (!r.ok) setResult({ ok: false, text: r.error });
            })}>
            <option value="">{a.assigned_to ? "Unassign" : "Assign to…"}</option>
            {assignees.filter((p) => (a.automation_key === "invoice_follow_up" ? p.invoices : p.conversations)).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        {canAct && (a.snoozed_until && new Date(a.snoozed_until) > new Date()
          ? <Button variant="secondary" onClick={() => snooze(null)} disabled={pending}>Wake now</Button>
          : <select aria-label="Snooze" className="h-10 rounded-xl border-2 border-line bg-card px-2 text-sm" value="" disabled={pending}
              onChange={(e) => { const t = snoozeTimes().find(([l]) => l === e.target.value); if (t) snooze(t[1]); }}>
              <option value="">Snooze…</option>
              {snoozeTimes().map(([l]) => <option key={l}>{l}</option>)}
            </select>)}
        {a.conversation_id && <Link href={`/conversations/${a.conversation_id}`} className="ml-auto text-sm text-muted underline-offset-4 hover:text-ink hover:underline">Open conversation →</Link>}
      </div>
      {result && !result.ok && <p role="alert" className="mt-2 text-sm text-danger">{result.text}</p>}
    </Card>
  );
}
