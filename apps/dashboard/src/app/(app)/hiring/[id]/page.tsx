import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CopyText } from "@/components/ca-tool-forms";
import { JobControls, UploadCvs } from "@/components/hiring";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Job" };

type C = { id: string; name: string | null; source: string; score: number | null; verdict: string | null; status: string; summary: string | null; interview_at: string | null };
type J = { id: string; title: string; description: string; must_have: string[]; location: string | null; status: string; post: string | null; apply_link: string; candidates: C[] };
const TONE: Record<string, "success" | "warning" | "danger"> = { strong: "success", maybe: "warning", no: "danger" };

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("hiring");
  const { id } = await params;
  let j: J;
  try {
    j = await api<J>(`/org/hiring/jobs/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <div className="space-y-5">
      <Link href="/hiring" className="text-sm text-muted hover:text-ink">← Hiring</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">{j.title}</h1><p className="text-sm text-muted">{j.location ?? ""} · must have: {j.must_have.join(", ") || "-"}</p></div>
        <JobControls id={j.id} status={j.status} />
      </header>
      <Card><CardBody className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>Apply link: <a href={j.apply_link} target="_blank" rel="noreferrer" className="underline">{j.apply_link}</a></span>
        <CopyText text={j.apply_link} /></CardBody></Card>
      <Card><CardHeader><CardTitle>Candidates</CardTitle><span className="text-sm text-muted">{j.candidates.length}</span></CardHeader><CardBody className="space-y-3">
        <UploadCvs jobId={j.id} />
        {j.candidates.length > 0 && <ul className="divide-y divide-line">{j.candidates.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
            <div className="min-w-0"><Link href={`/hiring/candidates/${c.id}`} className="font-semibold hover:underline">{c.name ?? "Unnamed"}</Link>
              <p className="text-xs text-muted">{c.summary}{c.source === "apply_link" ? " · applied through the link" : ""}</p></div>
            <span className="flex items-center gap-2"><span className="text-lg font-semibold">{c.score ?? "-"}</span>{c.verdict && <Badge tone={TONE[c.verdict]}>{c.verdict}</Badge>}<Badge>{c.status}</Badge></span>
          </li>))}</ul>}
      </CardBody></Card>
      {j.post && <Card><CardHeader><CardTitle>Job post for Naukri / LinkedIn / Indeed</CardTitle><CopyText text={`${j.post}\n\nApply: ${j.apply_link}`} /></CardHeader>
        <CardBody><pre className="whitespace-pre-wrap font-sans text-sm">{j.post}</pre></CardBody></Card>}
    </div>
  );
}
