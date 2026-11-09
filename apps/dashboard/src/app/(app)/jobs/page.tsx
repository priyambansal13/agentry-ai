import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { AddTech, type Job, JobRow, NewJob, type Tech } from "@/components/jobs";
import { pageApi as api, requirePage } from "@/lib/session";

export const metadata = { title: "Jobs" };

const TONE: Record<string, "neutral" | "warning" | "success" | "lime" | "danger"> = { new: "warning", assigned: "neutral", on_the_way: "lime", in_progress: "lime", done: "success", cancelled: "neutral" };

export default async function JobsPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const active = await requirePage("jobs");
  const { day } = await searchParams;
  const d = await api<{ day: string; jobs: Job[]; technicians: Tech[]; services: string[]; can_work: boolean }>(`/org/dispatch${day ? `?day=${day}` : ""}`, { orgId: active.id });
  const shift = (n: number) => { const x = new Date(`${d.day}T12:00:00Z`); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">Jobs</h1>
          <p className="mt-1 max-w-3xl text-muted">Visits booked by your assistant or your team, assigned to the right technician by skill, area and how busy they are. Customers hear when
            the technician is on the way and when the job is done; finished jobs with an amount become invoices.</p></div>
        <div className="flex items-center gap-2 text-sm"><Link href={`/jobs?day=${shift(-1)}`} className="underline">← prev</Link>
          <span className="font-semibold">{new Date(`${d.day}T12:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })}</span>
          <Link href={`/jobs?day=${shift(1)}`} className="underline">next →</Link></div>
      </header>
      <Card><CardBody className="p-0">{d.jobs.length === 0 ? <p className="p-5 text-muted">No jobs this day.</p> : (
        <ul className="divide-y divide-line">{d.jobs.map((j) => (
          <li key={j.id} className="space-y-2 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">#{j.number} {j.service} · {j.customer}
              <span className="font-normal text-muted"> · {j.area ?? j.address ?? ""} · {j.slot}{j.day !== d.day ? ` · from ${j.day}` : ""}</span></p>
              <span className="flex gap-2">{j.technician && <Badge>{j.technician}</Badge>}<Badge tone={TONE[j.status]}>{j.status.replace(/_/g, " ")}</Badge></span></div>
            {j.description && <p className="text-sm text-muted">{j.description}</p>}
            {d.can_work && !["done", "cancelled"].includes(j.status) && <JobRow j={j} techs={d.technicians} />}
            {j.invoice_id && <p className="text-xs"><Link href="/invoices" className="underline">Invoiced</Link></p>}
          </li>))}</ul>)}</CardBody></Card>
      {d.can_work && <>
        <Card><CardHeader><CardTitle>Add a job</CardTitle></CardHeader><CardBody><NewJob services={d.services} /></CardBody></Card>
        <Card><CardHeader><CardTitle>Technicians</CardTitle></CardHeader><CardBody className="space-y-3">
          <ul className="text-sm">{d.technicians.map((t) => <li key={t.id}>{t.name}{!t.active && " (off)"} · {t.skills.join(", ") || "any work"} · {t.areas.join(", ") || "everywhere"} · {t.today}/{t.max_per_day} today</li>)}</ul>
          <AddTech /></CardBody></Card></>}
    </div>
  );
}
