import { Card } from "@agentry/ui";

export type InboxInsights = {
  response_time: { this_month_minutes: number | null; last_month_minutes: number | null; before_agentry_minutes: number | null;
                   answered: number; unanswered: number };
  drafts_30_days: { sent_as_is: number; edited: number; discarded: number; total: number; as_is_pct: number | null };
  suspicious_30_days: number;
  ready_for_auto_send: string[]; auto_send_on: string[];
  writing_style: { guide: string; learned_at: string; samples: number } | null;
};

export function minutes(m: number | null): string {
  if (m == null) return "—";
  if (m < 60) return `${Math.round(m)} min`;
  if (m < 48 * 60) return `${(m / 60).toFixed(m < 600 ? 1 : 0)} h`;
  return `${Math.round(m / 1440)} days`;
}

/** Response time (#17), draft quality (#18) and fraud catches (#20) for inbox triage. */
export function InboxInsightsCards({ d }: { d: InboxInsights }) {
  const rt = d.response_time, dq = d.drafts_30_days;
  const faster = rt.before_agentry_minutes && rt.this_month_minutes ? rt.before_agentry_minutes / rt.this_month_minutes : null;
  return (
    <section className="grid gap-4 sm:grid-cols-3" aria-label="Inbox results">
      <Card className="p-5">
        <p className="text-sm text-muted">Typical first reply, this month</p>
        <p className="mt-1 text-3xl font-bold">{minutes(rt.this_month_minutes)}</p>
        <p className="mt-1 text-sm text-muted">
          {rt.before_agentry_minutes != null ? <>before Agentry: {minutes(rt.before_agentry_minutes)}{faster && faster > 1.1 ? <> · <strong className="text-success">{faster.toFixed(1)}× faster</strong></> : null}</>
            : rt.last_month_minutes != null ? <>last month: {minutes(rt.last_month_minutes)}</> : "measured from the first email to your first reply"}
        </p>
        {rt.unanswered > 0 && <p className="mt-1 text-xs text-warning">{rt.unanswered} conversation{rt.unanswered === 1 ? "" : "s"} this month still without a reply</p>}
      </Card>
      <Card className="p-5">
        <p className="text-sm text-muted">AI drafts, last 30 days</p>
        <p className="mt-1 text-3xl font-bold">{dq.as_is_pct != null ? `${dq.as_is_pct}% sent as written` : "—"}</p>
        <p className="mt-1 text-sm text-muted">{dq.total ? `${dq.sent_as_is} as written · ${dq.edited} edited · ${dq.discarded} discarded` : "no drafts decided yet"}</p>
        {d.auto_send_on.length > 0
          ? <p className="mt-2 text-xs text-success">Sending automatically: {d.auto_send_on.join(", ")}</p>
          : d.ready_for_auto_send.length > 0 && <p className="mt-2 text-xs text-ink-soft">Ready for automatic sending (your team sends these unchanged): {d.ready_for_auto_send.join(", ")}. Turn it on in Settings.</p>}
      </Card>
      <Card className="p-5">
        <p className="text-sm text-muted">Possible fraud caught, last 30 days</p>
        <p className="mt-1 text-3xl font-bold">{d.suspicious_30_days}</p>
        <p className="mt-1 text-sm text-muted">changed bank details, lookalike senders, gift-card and OTP requests</p>
      </Card>
    </section>
  );
}
