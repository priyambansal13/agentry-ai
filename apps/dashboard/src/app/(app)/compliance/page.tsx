import { Badge, Card, CardBody } from "@agentry/ui";
import Link from "next/link";
import { type CaMeta, RefreshCalendar } from "@/components/ca";
import { DueDateSources, type FirmUpdates } from "@/components/due-dates";
import { day } from "@/lib/ca";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Compliance calendar" };

type Due = { id: string; client_id: string; client: string; kind: string; period: string; title: string; due_on: string; status: string; overdue: boolean; reminded: number[] | null;
  extension: { label: string; url: string | null; was: string } | null };

export default async function CompliancePage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
  const active = await requirePage("compliance");
  const days = Number((await searchParams).days ?? 60) || 60;
  const [meta, { items }, updates] = await Promise.all([api<CaMeta>("/org/ca/meta", { orgId: active.id }),
    api<{ items: Due[] }>(`/org/ca/compliance?days=${days}`, { orgId: active.id }), api<FirmUpdates>("/org/ca/compliance/updates", { orgId: active.id })]);
  const byDay = new Map<string, Due[]>();
  for (const i of items) byDay.set(i.due_on, [...(byDay.get(i.due_on) ?? []), i]);
  const label = Object.fromEntries(meta.statuses.map((s) => [s.key, s.label]));
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Compliance calendar</h1>
          <p className="mt-1 max-w-3xl text-muted">GST, TDS, advance tax, ITR, audit and ROC dates for every client, from what their profile says applies.
            Each date goes on the filing board ahead of time; clients are reminded before it. Official extensions are applied for you (below).</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {[30, 60, 120].map((d) => <Link key={d} href={`/compliance?days=${d}`} className={`rounded-xl border-2 px-3 py-1.5 ${days === d ? "border-ink bg-lime-soft" : "border-line"}`}>{d} days</Link>)}
          {meta.can_work && <RefreshCalendar />}
        </div>
      </header>
      <DueDateSources data={updates} canWork={meta.can_work} />
      {items.length === 0 ? <Card><CardBody className="text-muted">Nothing due in the next {days} days. Tick what applies to each client (GST, TDS, audit…) on their page.</CardBody></Card> : (
        <div className="space-y-4">{[...byDay.entries()].map(([d, list]) => (
          <section key={d}>
            <h2 className="mb-1.5 font-semibold">{day(d)}</h2>
            <ul className="divide-y divide-line rounded-xl border-2 border-line bg-card">{list.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                <span><Link href={`/ca-clients/${i.client_id}`} className="font-semibold hover:underline">{i.client}</Link> · {i.title}
                  {i.extension && <span className="ml-2 text-xs text-muted"><Badge tone="success">extended</Badge> from {day(i.extension.was)}, {i.extension.url
                    ? <a href={i.extension.url} target="_blank" rel="noreferrer" className="underline">{i.extension.label}</a> : i.extension.label}</span>}</span>
                <span className="flex items-center gap-2">
                  {i.reminded?.length ? <span className="text-xs text-muted">reminded</span> : null}
                  <Badge tone={i.overdue ? "danger" : ["filed", "verified"].includes(i.status) ? "success" : "neutral"}>{i.overdue ? "overdue" : label[i.status]}</Badge>
                </span>
              </li>))}</ul>
          </section>))}</div>
      )}
    </div>
  );
}
