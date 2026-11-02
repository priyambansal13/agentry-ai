import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { StagePicker } from "@/components/hiring";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Candidate" };

type C = { id: string; job_id: string; job_title: string; name: string | null; email: string | null; phone: string | null; score: number | null; verdict: string | null;
  status: string; interview_at: string | null; filename: string | null;
  assessment: { summary?: string; strengths?: { point: string; quote: string }[]; gaps?: { point: string }[]; questions?: string[]; years_experience?: number } };

export default async function CandidatePage({ params }: { params: Promise<{ cid: string }> }) {
  const active = await requirePage("hiring");
  const { cid } = await params;
  let c: C;
  try {
    c = await api<C>(`/org/hiring/candidates/${cid}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const a = c.assessment;
  return (
    <div className="space-y-5">
      <Link href={`/hiring/${c.job_id}`} className="text-sm text-muted hover:text-ink">← {c.job_title}</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">{c.name ?? "Unnamed candidate"}</h1>
          <p className="text-sm text-muted">{[c.email, c.phone].filter(Boolean).join(" · ")}{c.filename ? <> · <a href={`/api/candidate-cv/${c.id}`} className="underline">CV</a></> : null}</p></div>
        <span className="flex items-center gap-2"><span className="text-3xl font-bold">{c.score ?? "-"}</span>{c.verdict && <Badge>{c.verdict}</Badge>}<Badge>{c.status}</Badge></span>
      </header>
      {a.summary && <Card><CardBody>{a.summary}</CardBody></Card>}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Strengths</CardTitle><span className="text-sm text-muted">each quoted from the CV</span></CardHeader><CardBody className="space-y-2 text-sm">
          {(a.strengths ?? []).length === 0 ? <p className="text-muted">None shown in the CV.</p> : a.strengths!.map((s) => (
            <p key={s.point}><span className="font-medium">{s.point}</span><span className="block text-xs text-muted">“{s.quote}”</span></p>))}</CardBody></Card>
        <Card><CardHeader><CardTitle>Gaps</CardTitle></CardHeader><CardBody className="space-y-1 text-sm">
          {(a.gaps ?? []).length === 0 ? <p className="text-muted">None against the must-haves.</p> : a.gaps!.map((g) => <p key={g.point}>{g.point}</p>)}</CardBody></Card>
      </div>
      {(a.questions ?? []).length > 0 && <Card><CardHeader><CardTitle>Ask in the interview</CardTitle></CardHeader><CardBody>
        <ol className="list-decimal space-y-1 pl-5 text-sm">{a.questions!.map((q) => <li key={q}>{q}</li>)}</ol></CardBody></Card>}
      <Card><CardHeader><CardTitle>Next step</CardTitle>{c.interview_at && <span className="text-sm text-muted">interview {new Date(c.interview_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>}</CardHeader>
        <CardBody><StagePicker id={c.id} jobId={c.job_id} status={c.status} /></CardBody></Card>
    </div>
  );
}
