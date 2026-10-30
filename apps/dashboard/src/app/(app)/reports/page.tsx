import { Card } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { PrintButton } from "@/components/print-button";
import { money } from "@/lib/billing";
import { api, getActiveOrg, getFeatures } from "@/lib/session";

export const metadata = { title: "Results report" };

type Report = { month: string; appointments: number; appointments_value: number; recovered: number; invoices_recovered: number;
                messages: number; emails_triaged: number; currency: string;
                content: { videos: number; generated: number; approved: number; approved_as_written_pct: number | null; published: number;
                           turnaround_minutes: number | null }; value_delivered: number; fee: number | null; roi_multiple: number | null };

function monthShift(m: string, by: number) {
  const [y, mo] = m.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, mo - 1 + by, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default async function ReportsPage({ searchParams }: { searchParams: Promise<{ month?: string }> }) {
  const [{ month }, active] = await Promise.all([searchParams, getActiveOrg()]);
  if (!active) redirect("/home");
  const lastMonth = monthShift(new Date().toISOString().slice(0, 7), -1);
  const r = await api<Report>(`/org/reports/results?month=${month ?? lastMonth}`, { orgId: active.id });
  const label = new Date(`${r.month}-01T00:00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  const auto = (await getFeatures(active.id)).automations;
  const has = (...k: string[]) => k.some((x) => auto.includes(x));
  const booking = has("website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist");
  const rows = ([
    booking && ["Appointments booked by your agents", r.appointments.toLocaleString("en-IN")],
    booking && ["Value of those appointments", money(r.appointments_value, r.currency)],
    has("invoice_follow_up") && ["Overdue money recovered", `${money(r.recovered, r.currency)} (${r.invoices_recovered} invoices)`],
    has("invoice_follow_up", "lead_reactivation", "speed_to_lead", "whatsapp_assistant") && ["Messages sent for you", r.messages.toLocaleString("en-IN")],
    has("inbox_triage") && ["Emails sorted", r.emails_triaged.toLocaleString("en-IN")],
    has("content_repurposing") && ["Posts written from your recordings", `${r.content.generated} from ${r.content.videos} recording${r.content.videos === 1 ? "" : "s"}`],
    has("content_repurposing") && ["Posts published", r.content.published.toLocaleString("en-IN")],
    has("content_repurposing") && r.content.approved_as_written_pct != null && ["Approved without changes", `${r.content.approved_as_written_pct}% of approved posts`],
  ].filter(Boolean)) as [string, string][];
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4 print:hidden">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">Results report</h1><p className="mt-1 text-muted">What your agents delivered, and what it was worth.</p></div>
        <nav className="flex items-center gap-2 text-sm">
          <Link className="rounded-lg border border-line px-3 py-1.5 hover:border-ink" href={`/reports?month=${monthShift(r.month, -1)}`}>← Earlier</Link>
          <span className="px-2 font-medium">{label}</span>
          <Link className="rounded-lg border border-line px-3 py-1.5 hover:border-ink" href={`/reports?month=${monthShift(r.month, 1)}`}>Later →</Link>
          <PrintButton />
        </nav>
      </header>
      <Card className="p-8 print:border-0 print:shadow-none">
        <p className="font-hand text-2xl text-muted">{active.name} · {label}</p>
        <div className="mt-4 grid gap-8 lg:grid-cols-[1fr_1.2fr]">
          {booking || has("invoice_follow_up") ? (
            <div className="rounded-3xl border-2 border-ink bg-lime p-8 text-lime-ink">
              <p className="text-sm font-semibold uppercase tracking-wide">Return on what you paid</p>
              <p className="mt-2 text-7xl font-bold tracking-tight">{r.roi_multiple != null ? `${r.roi_multiple}×` : "—"}</p>
              <p className="mt-2 text-lg">{money(r.value_delivered, r.currency)} delivered{r.fee != null ? ` for ${money(r.fee, r.currency)}` : ""}</p>
              {r.fee == null && <p className="mt-2 text-sm">The ROI appears once this month&apos;s statement is issued.</p>}
            </div>
          ) : (
            <div className="rounded-3xl border-2 border-ink bg-lime p-8 text-lime-ink">
              <p className="text-sm font-semibold uppercase tracking-wide">Time given back to you</p>
              <p className="mt-2 text-7xl font-bold tracking-tight">{Math.round((r.emails_triaged * 2) / 60)} h</p>
              <p className="mt-2 text-lg">{r.emails_triaged.toLocaleString("en-IN")} emails sorted, labelled and drafted for you</p>
              <p className="mt-2 text-sm">Estimate: about 2 minutes saved per email.</p>
            </div>
          )}
          <dl className="divide-y divide-line">
            {rows.map(([k, v]) => <div key={k} className="flex items-baseline justify-between gap-4 py-3"><dt className="text-ink-soft">{k}</dt><dd className="text-lg font-semibold">{v}</dd></div>)}
          </dl>
        </div>
        {(booking || has("invoice_follow_up")) && <p className="mt-6 text-xs text-muted">Value delivered = appointments booked × their value + overdue money recovered. Every number links to evidence on your statement.</p>}
      </Card>
    </div>
  );
}
