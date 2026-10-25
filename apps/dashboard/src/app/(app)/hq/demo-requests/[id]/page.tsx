import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { BuildDemo, ConvertLink, type DemoRequest, NotesForm, SendDemo, StatusButtons } from "@/components/demo-request";
import { DEMO_STATUS, formatDateTime } from "@/lib/format";
import { api, ApiError, getMe } from "@/lib/session";

export const metadata = { title: "Demo request · Agentry HQ" };

const STEPS = ["new", "demo_built", "demo_sent", "in_talks", "won"];

export default async function DemoRequestPage({ params }: { params: Promise<{ id: string }> }) {
  const [{ id }, me] = await Promise.all([params, getMe()]);
  if (!me.is_staff) redirect("/home");
  let d: DemoRequest;
  try {
    d = await api<DemoRequest>(`/hq/demo-requests/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const { items: packs } = await api<{ items: { key: string; name: string }[] }>("/hq/packs");
  const st = DEMO_STATUS[d.status] ?? { label: d.status, tone: "neutral" as const };
  const reached = STEPS.indexOf(d.status);
  const nextFollowUp = d.status === "demo_sent" && d.demo_sent_at && d.followups_sent < d.follow_up_days.length
    ? new Date(new Date(d.demo_sent_at).getTime() + d.follow_up_days[d.followups_sent]! * 86400000) : null;
  return (
    <div className="space-y-6">
      <Link href="/hq" className="text-sm text-muted hover:text-ink">← Agentry HQ</Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-hand text-xl text-muted">Demo request</p>
          <h1 className="font-display text-3xl font-bold tracking-tight">{d.company ?? d.name}</h1>
          <p className="mt-1 text-muted">{d.name} · {d.email}{d.phone ? ` · ${d.phone}` : ""} · received {formatDateTime(d.created_at)}</p>
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </header>
      <ol className="flex flex-wrap gap-2 text-xs" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} className={`rounded-full border-2 px-3 py-1 ${d.status === "lost" ? "border-line text-muted" : i <= reached ? "border-ink bg-lime font-semibold" : "border-line text-muted"}`}>
            {i + 1}. {DEMO_STATUS[s]!.label}
          </li>
        ))}
        {d.status === "lost" && <li className="rounded-full border-2 border-ink px-3 py-1 font-semibold">Lost</li>}
      </ol>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>1. Build their demo</CardTitle></CardHeader><CardBody><BuildDemo d={d} packs={packs} /></CardBody></Card>
          <Card><CardHeader><CardTitle>2. Send it</CardTitle>
            {d.demo_sent_at && <span className="text-sm text-muted">sent {formatDateTime(d.demo_sent_at)}</span>}</CardHeader>
            <CardBody className="space-y-3">
              <SendDemo d={d} />
              {d.demo_sent_at && (
                <p className="text-sm text-muted">
                  Follow-ups: {d.followups_sent} of {d.follow_up_days.length} sent (days {d.follow_up_days.join(", ")}).{" "}
                  {nextFollowUp ? `Next on ${formatDateTime(nextFollowUp.toISOString())}, unless you mark a reply.` : d.status === "demo_sent" ? "All sent." : "Stopped (status changed)."}
                </p>
              )}
            </CardBody></Card>
          <Card><CardHeader><CardTitle>3. Win them</CardTitle></CardHeader><CardBody className="space-y-4">
            <StatusButtons d={d} />
            <div className="space-y-2">
              <p className="text-sm font-medium">Proposals</p>
              {d.proposals.length === 0 && <p className="text-sm text-muted">None sent yet.</p>}
              <ul className="space-y-1 text-sm">{d.proposals.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2">
                  <span>Sent {formatDateTime(p.sent_at)}</span>
                  <Badge tone={p.first_viewed_at ? "success" : "neutral"}>{p.first_viewed_at ? `opened ${formatDateTime(p.first_viewed_at)}${p.views > 1 ? ` · ${p.views} views` : ""}` : "not opened yet"}</Badge>
                  <a className="underline" href={p.url} target="_blank" rel="noopener">their copy →</a>
                </li>
              ))}</ul>
              <Link href={`/hq/proposal?request=${d.id}`} className="inline-flex h-10 items-center rounded-xl border-2 border-ink px-4 text-sm font-semibold hover:bg-lime-soft">
                {d.proposals.length ? "Send another proposal" : "Create proposal"} →
              </Link>
            </div>
            <ConvertLink d={d} />
          </CardBody></Card>
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>What they told us</CardTitle></CardHeader><CardBody className="space-y-2 text-sm">
            <p><span className="text-muted">Website:</span> {d.website ? <a className="underline" href={d.website} target="_blank" rel="noopener">{d.website}</a> : "—"}</p>
            <p><span className="text-muted">Business type:</span> {d.niche?.replaceAll("_", " ") ?? "—"}</p>
            <p className="whitespace-pre-wrap"><span className="text-muted">Message:</span> {d.message ?? "—"}</p>
          </CardBody></Card>
          <Card><CardHeader><CardTitle>Their replies</CardTitle></CardHeader><CardBody className="space-y-3 text-sm">
            {d.messages.length === 0 && <p className="text-muted">None yet. Replies to your emails show up here within a couple of minutes.</p>}
            {d.messages.map((m) => (
              <div key={m.received_at + (m.subject ?? "")} className="rounded-xl bg-paper px-3 py-2">
                <p className="text-xs text-muted">{formatDateTime(m.received_at)} · {{ reply: "reply", auto_reply: "automatic reply", bounce: "bounced: address not reachable" }[m.kind]}</p>
                {m.subject && <p className="font-medium">{m.subject}</p>}
                {m.snippet && <p className="mt-1 whitespace-pre-wrap text-ink-soft">{m.snippet}</p>}
              </div>
            ))}
          </CardBody></Card>
          <Card><CardBody><NotesForm d={d} /></CardBody></Card>
        </div>
      </div>
    </div>
  );
}
