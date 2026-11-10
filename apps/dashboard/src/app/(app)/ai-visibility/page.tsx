import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { CheckNow, CopyCode, RefreshWhileRunning, VisibilitySetup, WritePage } from "@/components/ai-visibility";
import { pageApi as api, requirePage } from "@/lib/session";

export const metadata = { title: "AI visibility" };

type Share = { name: string; me: boolean; mentions: number; pct: number };
type Fix = { kind: string; title: string; detail: string; code?: string; questions?: string[]; sites?: { site: string; times: number }[]; can_write?: boolean };
type Score = {
  asked: number; failed: number; named: number; rate: number; avg_position: number | null; previous_rate: number | null;
  engines: Record<string, { asked: number; named: number; rate: number }>; share: Share[];
  named_instead: { name: string; mentions: number }[]; sources: { site: string; times: number }[]; fixes: Fix[];
  questions: { question: string; asked: number; named: number; best_position: number | null; others: string[] }[];
};
type Run = { id: string; trigger: string; status: string; score: Score | null; mock: boolean; error: string | null; created_at: string };
type D = {
  setup: { config: { service: string | null; city: string | null; area: string | null; other_names: string[]; competitors: string[]; questions: string[]; monthly: boolean };
    business: string; competitors: { name: string; website: string | null }[]; questions: string[] };
  ready: boolean; missing: string | null; engines: { key: string; label: string }[]; test_mode: boolean;
  latest: Run | null; running: Run | null; history: { id: string; at: string; rate: number | null; status: string }[]; manual_left: number; can_edit: boolean;
};
const LABEL: Record<string, string> = { chatgpt: "ChatGPT", gemini: "Gemini", perplexity: "Perplexity" };
const KIND: Record<string, string> = { website: "Website", listings: "Listings", reviews: "Reviews", content: "Answer pages" };

export default async function AiVisibilityPage() {
  const active = await requirePage("ai-visibility");
  const d = await api<D>("/org/ai-visibility", { orgId: active.id });
  const s = d.latest?.score ?? null;
  const change = s && s.previous_rate !== null ? s.rate - s.previous_rate : null;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">AI visibility</h1>
        <p className="mt-1 max-w-3xl text-muted">When customers ask ChatGPT, Gemini or Perplexity for a recommendation, are you named? Checked every month with the questions
          your customers ask, against your competitors, with what to fix.</p>
      </header>

      {d.running && <Card><CardBody className="text-sm"><RefreshWhileRunning />Checking now: asking {d.engines.map((e) => e.label).join(" and ")} {d.setup.questions.length} questions, three times each. This takes a few minutes.</CardBody></Card>}

      {s && (
        <Card>
          <CardHeader><CardTitle>Named in {s.named} of {s.asked} answers: {s.rate}%</CardTitle>
            <span className="text-sm text-muted">{new Date(d.latest!.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}
              {change !== null && <> · <span className={change >= 0 ? "text-success" : "text-danger"}>{change >= 0 ? "▲" : "▼"} {Math.abs(change)} points</span> since last time</>}
              {s.avg_position !== null && <> · average position when named: {s.avg_position}</>}
              {d.latest!.mock && <> · <Badge tone="warning">test answers</Badge></>}</span></CardHeader>
          <CardBody className="grid gap-6 lg:grid-cols-2">
            <section aria-labelledby="by-engine">
              <h2 id="by-engine" className="mb-2 font-semibold">By assistant</h2>
              <ul className="space-y-2">{Object.entries(s.engines).map(([k, e]) => <Bar key={k} label={LABEL[k] ?? k} pct={e.rate} note={`${e.named} of ${e.asked}`} strong />)}</ul>
              {s.failed > 0 && <p className="mt-2 text-xs text-muted">{s.failed} answers couldn&apos;t be read (the assistant was busy) and aren&apos;t counted.</p>}
            </section>
            <section aria-labelledby="share">
              <h2 id="share" className="mb-2 font-semibold">You and your competitors</h2>
              <p className="mb-2 text-xs text-muted">Share of the answers that named one of you</p>
              <ul className="space-y-2">{s.share.map((x) => <Bar key={x.name} label={x.name} pct={x.pct} note={`${x.mentions} answers`} strong={x.me} />)}</ul>
            </section>
            {s.named_instead.length > 0 && <section aria-labelledby="instead"><h2 id="instead" className="mb-2 font-semibold">Named most often instead</h2>
              <ol className="list-decimal space-y-1 pl-5 text-sm">{s.named_instead.slice(0, 6).map((n) => <li key={n.name}>{n.name} <span className="text-muted">({n.mentions})</span></li>)}</ol></section>}
            {s.sources.length > 0 && <section aria-labelledby="sources"><h2 id="sources" className="mb-2 font-semibold">Where the assistants looked</h2>
              <ul className="space-y-1 text-sm">{s.sources.slice(0, 6).map((x) => <li key={x.site} className="flex justify-between gap-2"><span>{x.site}</span><span className="text-muted">{x.times}×</span></li>)}</ul></section>}
          </CardBody>
        </Card>
      )}

      {s && s.fixes.length > 0 && (
        <Card><CardHeader><CardTitle>What to fix</CardTitle></CardHeader><CardBody>
          <ul className="space-y-4">{s.fixes.map((f) => (
            <li key={f.title} className="rounded-xl border-2 border-line p-4 text-sm">
              <p className="flex flex-wrap items-center gap-2 font-semibold"><Badge tone="neutral">{KIND[f.kind] ?? f.kind}</Badge>{f.title}</p>
              <p className="mt-1">{f.detail}</p>
              {f.sites && <ul className="mt-2 list-disc pl-5">{f.sites.map((x) => <li key={x.site}>{x.site} <span className="text-muted">(quoted {x.times}×)</span></li>)}</ul>}
              {f.questions && <ul className="mt-2 space-y-1">{f.questions.map((q) => (
                <li key={q} className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-1"><span>“{q}”</span>{f.can_write && d.can_edit && <WritePage question={q} />}</li>))}</ul>}
              {f.code && <CopyCode code={f.code} />}
            </li>))}</ul>
        </CardBody></Card>
      )}

      {s && (
        <Card><CardHeader><CardTitle>Every question</CardTitle><span className="text-sm text-muted">Asked {Object.keys(s.engines).length > 1 ? "each assistant" : "the assistant"} three times; answers vary</span></CardHeader>
          <CardBody><div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left"><th className="py-2 pr-3">Question</th><th className="py-2 pr-3">Named you</th><th className="py-2 pr-3">Best position</th><th className="py-2">Named instead</th></tr></thead>
            <tbody>{s.questions.map((q) => (
              <tr key={q.question} className="border-b border-line align-top"><td className="py-2 pr-3">{q.question}</td>
                <td className="py-2 pr-3"><Badge tone={q.named === 0 ? "danger" : q.named === q.asked ? "success" : "warning"}>{q.named} of {q.asked}</Badge></td>
                <td className="py-2 pr-3">{q.best_position ?? "—"}</td><td className="py-2 text-muted">{q.others.join(", ") || "—"}</td></tr>))}</tbody>
          </table></div></CardBody></Card>
      )}

      {d.history.length > 1 && (
        <Card><CardHeader><CardTitle>Month by month</CardTitle></CardHeader><CardBody>
          <ul className="space-y-2">{d.history.filter((h) => h.status === "done").map((h) => (
            <Bar key={h.id} label={new Date(h.at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} pct={h.rate ?? 0} note={`${h.rate ?? 0}%`} strong={h.id === d.latest?.id} />))}</ul>
        </CardBody></Card>
      )}

      <Card><CardHeader><CardTitle>{s ? "Setup" : "Set it up"}</CardTitle>
        <span className="text-sm text-muted">{d.engines.map((e) => e.label).join(", ")}{d.test_mode ? " (test answers: no assistant keys yet)" : ""}</span></CardHeader>
        <CardBody className="space-y-5">
          {d.can_edit ? <VisibilitySetup cfg={d.setup.config} suggested={d.setup.questions} /> : <p className="text-sm text-muted">Owners and managers can change the setup.</p>}
          {d.setup.questions.length > 0 && !d.setup.config.questions.length && (
            <details className="text-sm"><summary className="cursor-pointer font-semibold">The {d.setup.questions.length} questions we&apos;ll ask</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5">{d.setup.questions.map((q) => <li key={q}>{q}</li>)}</ul></details>)}
          {d.can_edit && <CheckNow left={d.manual_left} disabled={d.running ? "A check is running." : d.missing} />}
          <p className="text-xs text-muted">Assistants answer differently for different people and places, and their apps can differ slightly from what we can ask them.
            The score is measured the same way every month, so the trend tells you whether the fixes are working.</p>
        </CardBody></Card>
    </div>
  );
}

function Bar({ label, pct, note, strong }: { label: string; pct: number; note: string; strong?: boolean }) {
  return (
    <li className="grid grid-cols-[minmax(6rem,10rem)_1fr_auto] items-center gap-3 text-sm" title={`${label}: ${pct}% (${note})`}>
      <span className={strong ? "font-semibold" : ""}>{label}</span>
      <span className="h-3 overflow-hidden rounded-full bg-paper" aria-hidden><span className={`block h-full rounded-full ${strong ? "bg-lime border-r-2 border-ink" : "bg-muted/50"}`} style={{ width: `${Math.max(2, pct)}%` }} /></span>
      <span className="tabular-nums text-muted">{pct}% · {note}</span>
    </li>
  );
}
