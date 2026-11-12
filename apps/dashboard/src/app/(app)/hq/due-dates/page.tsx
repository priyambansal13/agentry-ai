import { Badge, Card, CardBody } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AddRule, AddUpdate, Checks, day, Decide, type Figure, FiguresTable, HqCheckNow, RuleChecks, RuleDecide, type RuleUpdate, type Sync, type Update } from "@/components/due-dates";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Official updates · Agentry HQ" };

const TONE = { proposed: "warning", active: "success", rejected: "neutral", withdrawn: "neutral" } as const;
const LABEL = { proposed: "To review", active: "In force", rejected: "Rejected", withdrawn: "Withdrawn" } as const;

/** Official changes to statutory due dates, for every CA firm (backend automations/ca/due_dates.py). */
export default async function DueDatesPage() {
  const me = await getMe();
  if (!me.is_staff) redirect("/home");
  const [d, r] = await Promise.all([
    api<{ updates: Update[]; syncs: Sync[]; kinds: Record<string, string>; sources: { name: string; url: string }[]; searched: string[] }>("/hq/due-dates"),
    api<{ updates: RuleUpdate[]; figures: Figure[] }>("/hq/due-dates/rules")]);
  const rReview = r.updates.filter((u) => u.status === "proposed");
  const rActive = r.updates.filter((u) => u.status === "active");
  const rRow = (u: RuleUpdate) => (
    <li key={u.id} className="space-y-1.5 px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{u.title} <Badge tone={TONE[u.status]}>{LABEL[u.status]}</Badge></p>
          <p className="text-sm text-ink-soft">{u.source_url ? <a href={u.source_url} target="_blank" rel="noreferrer" className="underline">{u.source}</a> : u.source}
            {u.applies_from && <span> · from {u.applies_from}</span>}<span className="text-muted"> · {u.found_by === "sync" ? "found by the check" : "entered by staff"}</span>
            {u.decided_by && <span className="text-muted"> · {u.status} by {u.decided_by}</span>}</p>
        </div>
        <RuleDecide u={u} />
      </div>
      {u.quote && <blockquote className="border-l-4 border-line pl-3 text-sm italic text-ink-soft">“{u.quote}”</blockquote>}
      <RuleChecks c={u.checks} />
    </li>);
  const review = d.updates.filter((u) => u.status === "proposed");
  const active = d.updates.filter((u) => u.status === "active");
  const past = d.updates.filter((u) => u.status === "rejected" || u.status === "withdrawn");
  const running = d.syncs[0]?.status === "running";
  const row = (u: Update) => (
    <li key={u.id} className="space-y-1.5 px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{u.title} <Badge tone={TONE[u.status]}>{LABEL[u.status]}</Badge></p>
          <p className="text-sm text-ink-soft">{u.source_url ? <a href={u.source_url} target="_blank" rel="noreferrer" className="underline">{u.source}</a> : u.source}
            <span className="text-muted"> · {u.found_by === "sync" ? "found by the check" : "entered by staff"} {day(u.created_at.slice(0, 10))}</span>
            {u.decided_by && <span className="text-muted"> · {u.status} by {u.decided_by}{u.status === "active" ? `, ${u.cards} card(s) moved` : ""}</span>}</p>
        </div>
        <Decide u={u} />
      </div>
      {u.quote && <blockquote className="border-l-4 border-line pl-3 text-sm italic text-ink-soft">“{u.quote}”</blockquote>}
      <Checks c={u.checks} />
    </li>);
  return (
    <div className="space-y-8">
      <Link href="/hq" className="text-sm text-muted hover:text-ink">← Agentry HQ</Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-hand text-xl text-muted">Agentry HQ</p>
          <h1 className="font-display text-3xl font-bold tracking-tight">Official updates</h1>
          <p className="mt-1 max-w-3xl text-muted">Due-date extensions, and changes to the rates, thresholds, limits and festival dates the agents use. Official sources are checked every
            morning at 7:30; each change found is checked on the official page and must apply from a year after the law the figures follow. Nothing changes for any firm until you approve it.</p>
        </div>
        <HqCheckNow running={running} />
      </header>

      <h2 className="font-display text-2xl font-bold">Due dates</h2>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">To review ({review.length})</h2>
        <Card>{review.length ? <ul className="divide-y divide-line">{review.map(row)}</ul> : <CardBody className="text-muted">Nothing waiting. New finds also arrive by email.</CardBody>}</Card>
      </section>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">In force ({active.length})</h2>
        <Card>{active.length ? <ul className="divide-y divide-line">{active.map(row)}</ul> : <CardBody className="text-muted">No extensions in force: every firm sees the standard dates.</CardBody>}</Card>
      </section>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Enter a change from a notification</h2>
        <Card><CardBody><AddUpdate kinds={d.kinds} /></CardBody></Card>
      </section>
      <h2 className="font-display text-2xl font-bold">Rates, limits and festival dates</h2>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">To review ({rReview.length})</h2>
        <Card>{rReview.length ? <ul className="divide-y divide-line">{rReview.map(rRow)}</ul> : <CardBody className="text-muted">Nothing waiting.</CardBody>}</Card>
      </section>
      {rActive.length > 0 && <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Changes in force ({rActive.length})</h2>
        <Card><ul className="divide-y divide-line">{rActive.map(rRow)}</ul></Card>
      </section>}
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Change a figure from a notification</h2>
        <Card><CardBody><AddRule figures={r.figures} /></CardBody></Card>
      </section>
      <details className="rounded-2xl border-2 border-line bg-card p-5">
        <summary className="cursor-pointer font-display text-xl font-semibold">Every figure the agents use ({r.figures.length})</summary>
        <div className="mt-4"><FiguresTable figures={r.figures} /></div>
      </details>
      <section className="space-y-3">
        <h2 className="font-display text-xl font-semibold">Recent checks</h2>
        <Card className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr><th className="px-5 py-2 font-medium">When</th><th className="px-5 py-2 font-medium">Asked by</th>
            <th className="px-5 py-2 font-medium">Result</th><th className="px-5 py-2 font-medium">Sources</th></tr></thead>
          <tbody className="divide-y divide-line">{d.syncs.map((s) => (
            <tr key={s.id}><td className="px-5 py-2 whitespace-nowrap">{new Date(s.started_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</td>
              <td className="px-5 py-2">{s.trigger === "daily" ? "daily check" : s.trigger === "firm" || s.trigger === "requested" ? "check now" : s.trigger}</td>
              <td className="px-5 py-2">{s.status === "running" ? "running…" : s.status === "failed" ? <span className="text-danger">failed: {s.error}</span> : `${s.found} found, ${s.proposed} new`}</td>
              <td className="px-5 py-2 text-xs">{s.sources.map((x) => `${x.ok ? "✓" : "✗"} ${x.name}`).join(" · ")}</td></tr>))}</tbody></table></Card>
        <p className="text-xs text-muted">Read directly: {d.sources.map((s) => s.name).join(", ")}. Searched: {d.searched.join(", ")}.</p>
      </section>
      {past.length > 0 && <section className="space-y-3"><h2 className="font-display text-xl font-semibold">Rejected and withdrawn</h2>
        <Card><ul className="divide-y divide-line">{past.map(row)}</ul></Card></section>}
    </div>
  );
}
