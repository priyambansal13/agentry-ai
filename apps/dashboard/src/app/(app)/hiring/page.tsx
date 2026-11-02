import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { NewJob } from "@/components/hiring";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Hiring" };

type J = { id: string; title: string; location: string | null; status: string; candidates: number; strong: number; unseen: number; apply_link: string };

export default async function HiringPage() {
  const active = await requirePage("hiring");
  const { items } = await api<{ items: J[] }>("/org/hiring/jobs", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Hiring</h1>
        <p className="mt-1 max-w-3xl text-muted">Every CV is read and scored against the job, with the reasons quoted from the CV. Name, gender, age, religion, caste, photo and address
          are never used. Share the apply link anywhere; strong candidates show up in Needs you.</p>
      </header>
      <Card><CardBody className="p-0">{items.length === 0 ? <p className="p-5 text-muted">No jobs yet.</p> : (
        <ul className="divide-y divide-line">{items.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div><Link href={`/hiring/${j.id}`} className="font-semibold hover:underline">{j.title}</Link><p className="text-xs text-muted">{j.location ?? ""}</p></div>
            <span className="flex items-center gap-2 text-sm">{j.candidates} applied · {j.strong} strong{j.unseen ? ` · ${j.unseen} new` : ""}<Badge>{j.status}</Badge></span>
          </li>))}</ul>)}</CardBody></Card>
      <Card><CardHeader><CardTitle>New job</CardTitle></CardHeader><CardBody><NewJob /></CardBody></Card>
    </div>
  );
}
