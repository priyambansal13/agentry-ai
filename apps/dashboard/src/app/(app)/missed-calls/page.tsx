import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { CopyUrl, TestCall } from "@/components/missed-calls";
import { pageApi as api, requirePage } from "@/lib/session";

export const metadata = { title: "Missed calls" };

type Stats = { missed: number; messaged: number; replied: number; booked: number };
type Call = { id: string; caller: string; contact: string | null; status: string; outcome: string; skip_reason: string | null; at: string;
  sent_at: string | null; replied_at: string | null; booked_at: string | null; conversation_id: string | null };
type D = { hook_url: string; status: string; callers_informed: boolean; template: string | null; stats: Record<"1" | "30", Stats>; calls: Call[] };

const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const PROVIDERS = [
  ["Exotel", "App Bazaar → your flow → Passthru applet (or Call Status webhook) → paste the address"],
  ["MyOperator", "Settings → Webhooks → Call details: missed calls → paste the address"],
  ["Knowlarity / SuperReceptionist", "Settings → Integrations → Webhook → event: missed call"],
  ["TATA Tele, Airtel IQ, others", "Any “call status” or “missed call” webhook / URL callback: POST or GET, the caller's number and the status"],
];

/** Missed-call recovery (backend automations/missed_call): numbers, results and the phone-system hook-up. */
export default async function MissedCallsPage() {
  const active = await requirePage("missed-calls");
  const d = await api<D>("/org/missed-calls", { orgId: active.id });
  const m = d.stats["30"];
  const tiles: [string, number, string][] = [["Missed calls", m.missed, "last 30 days"], ["Got a WhatsApp", m.messaged, "within a minute"],
    ["Replied", m.replied, "the assistant took over"], ["Booked", m.booked, "customers won back"]];
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Missed calls</h1>
        <p className="mt-1 max-w-3xl text-muted">Every call you miss gets a WhatsApp within a minute (&quot;Sorry we missed your call, how can we help?&quot;). Your WhatsApp
          assistant answers and books; anything it can&apos;t handle comes to you. Today: {d.stats["1"].missed} missed, {d.stats["1"].messaged} messaged.</p>
      </header>
      {!d.callers_informed && <Card className="border-warning"><CardBody className="text-sm">
        <strong>Nothing is being sent yet.</strong> Tell callers they&apos;ll get a WhatsApp when you miss them (on your IVR greeting or website), then switch on
        &quot;Callers are told they&apos;ll get a WhatsApp&quot; in <Link href="/automations" className="underline">Automations → Missed-call recovery</Link>. That&apos;s their consent to this one message.</CardBody></Card>}
      {!d.template && <p className="text-sm text-muted">Agentry is getting your WhatsApp template approved: until then, only callers who wrote to you in the last 24 hours get the message.</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{tiles.map(([l, v, n]) => (
        <Card key={l}><CardBody><p className="text-xs font-semibold uppercase tracking-wide text-muted">{l}</p><p className="font-display text-3xl font-bold">{v}</p>
          <p className="text-xs text-muted">{n}</p></CardBody></Card>))}</div>

      <Card>
        <CardHeader><CardTitle>Recent missed calls</CardTitle></CardHeader>
        <CardBody>{d.calls.length === 0 ? <p className="text-sm text-muted">None yet. Connect your phone system below, or try a test call.</p> : (
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-muted"><tr>
            <th className="py-2 pr-4 font-medium">When</th><th className="py-2 pr-4 font-medium">Caller</th><th className="py-2 pr-4 font-medium">WhatsApp</th><th className="py-2 font-medium">Result</th></tr></thead>
            <tbody className="divide-y divide-line">{d.calls.map((c) => (
              <tr key={c.id}><td className="py-2 pr-4 whitespace-nowrap">{when(c.at)}</td><td className="py-2 pr-4">{c.contact ?? c.caller}<div className="text-xs text-muted">{c.contact ? c.caller : c.status}</div></td>
                <td className="py-2 pr-4">{c.outcome === "sent" ? (c.conversation_id ? <Link href={`/conversations/${c.conversation_id}`} className="underline">sent {c.sent_at ? when(c.sent_at) : ""}</Link> : "sent")
                  : c.outcome === "waiting" ? <Badge>waiting</Badge> : <span className="text-muted">{c.outcome}: {c.skip_reason}</span>}</td>
                <td className="py-2">{c.booked_at ? <Badge tone="success">booked</Badge> : c.replied_at ? <Badge>replied</Badge> : "–"}</td></tr>))}</tbody></table></div>)}</CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>Connect your phone system</CardTitle></CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-muted">Give this address to your phone provider as the webhook for missed (or all) calls. Answered calls are ignored.</p>
          <CopyUrl url={d.hook_url} />
          <ul className="space-y-1.5 text-sm">{PROVIDERS.map(([p, how]) => <li key={p}><strong>{p}:</strong> <span className="text-ink-soft">{how}</span></li>)}</ul>
          <div className="border-t border-line pt-4"><TestCall /></div>
        </CardBody>
      </Card>
    </div>
  );
}
