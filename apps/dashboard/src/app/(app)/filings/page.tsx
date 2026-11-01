import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { BoardCard, type CaMeta, type Filing, NewFiling, StartSeason } from "@/components/ca";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Filings" };

export default async function FilingsPage({ searchParams }: { searchParams: Promise<{ mine?: string; kind?: string; period?: string; q?: string }> }) {
  const active = await requirePage("filings");
  const sp = await searchParams;
  const meta = await api<CaMeta>("/org/ca/meta", { orgId: active.id });
  if (!meta.enabled.includes("ca_filing_tracker")) {
    return <p className="text-muted">The filing board is part of the Filing tracker, which isn&apos;t switched on. <Link href="/ca-clients" className="underline">Clients</Link></p>;
  }
  const q = new URLSearchParams({ ...(sp.mine ? { assignee: "me" } : {}), ...(sp.kind ? { kind: sp.kind } : {}), ...(sp.period ? { period: sp.period } : {}), ...(sp.q ? { q: sp.q } : {}) });
  const [{ items, periods }, { items: clients }] = await Promise.all([
    api<{ items: Filing[]; periods: string[] }>(`/org/ca/filings?${q}`, { orgId: active.id }),
    api<{ items: { id: string; name: string }[] }>("/org/ca/clients", { orgId: active.id }),
  ]);
  const who = Object.fromEntries(meta.team.map((t) => [t.id, t.name]));
  const link = (p: Record<string, string | undefined>) => `/filings?${new URLSearchParams(Object.entries({ ...sp, ...p }).filter(([, v]) => v) as [string, string][])}`;
  const overdue = items.filter((f) => f.overdue).length;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Filings</h1>
          <p className="mt-1 text-muted">Every filing on one board. Clients who ask &quot;is my return filed?&quot; on WhatsApp get the answer from here.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <Link href={link({ mine: sp.mine ? undefined : "1" })} className={`inline-flex h-10 items-center rounded-xl border-2 px-4 font-semibold ${sp.mine ? "border-ink bg-lime-soft" : "border-line hover:border-ink"}`}>My work</Link>
          <Link href="/ca-clients" className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 font-semibold hover:border-ink">Clients</Link>
        </div>
      </header>

      <form className="flex flex-wrap items-end gap-2 text-sm" action="/filings">
        {sp.mine && <input type="hidden" name="mine" value="1" />}
        <select name="kind" defaultValue={sp.kind ?? ""} className="h-10 rounded-xl border-2 border-line bg-card px-3">
          <option value="">All filings</option>{Object.entries(meta.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select name="period" defaultValue={sp.period ?? ""} className="h-10 rounded-xl border-2 border-line bg-card px-3">
          <option value="">All periods</option>{periods.map((p) => <option key={p}>{p}</option>)}</select>
        <input name="q" defaultValue={sp.q ?? ""} placeholder="Client, PAN or filing" className="h-10 rounded-xl border-2 border-line bg-card px-3" />
        <button className="h-10 rounded-xl border-2 border-ink px-4 font-semibold">Filter</button>
        <span className="text-muted">{items.length} filing{items.length === 1 ? "" : "s"}{overdue ? ` · ${overdue} overdue` : ""}</span>
      </form>

      {items.length === 0 ? (
        <Card><CardBody className="text-muted">No filings here yet. Add your clients, then start a season below (e.g. ITR AY 2026-27 for every individual) or add one filing.</CardBody></Card>
      ) : (
        <div className="grid gap-4 overflow-x-auto lg:grid-cols-5">
          {meta.statuses.map((s) => {
            const col = items.filter((f) => f.status === s.key);
            return (
              <section key={s.key} className="min-w-0 space-y-2">
                <h2 className="flex items-center justify-between font-semibold">{s.label}<span className="text-sm text-muted">{col.length}</span></h2>
                <ul className="space-y-2">{col.map((f) => <BoardCard key={f.id} f={f} meta={meta} who={who} />)}</ul>
              </section>
            );
          })}
        </div>
      )}

      {meta.can_work && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Start a season</CardTitle><span className="text-sm text-muted">one card per matching client</span></CardHeader>
            <CardBody><StartSeason meta={meta} /></CardBody></Card>
          <Card><CardHeader><CardTitle>Add one filing</CardTitle></CardHeader><CardBody><NewFiling meta={meta} clients={clients} /></CardBody></Card>
        </div>
      )}
    </div>
  );
}
