import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { timeAgo } from "@/lib/format";

export type AgentRun = { id: string; agent: string; kind: string; status: "running" | "ok" | "failed"; error: string | null; started_at: string;
  seconds: number; steps: { name: string; ms: number; detail?: Record<string, unknown> }[]; cost_usd?: string | number; model_calls?: number };

const KIND: Record<string, string> = {
  "triage.email": "Sorted an email", "chat.turn": "Answered a message", "content.source": "Turned a recording into posts",
  "cold_email.list": "Built a prospect list", "voice.summary": "Summarised a call", "sequence.step": "Wrote a follow-up",
};

const fmtSecs = (s: number) => (s < 1 ? "<1 s" : s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);

/** What an agent did recently, step by step (agentry/runs.py). Costs are shown only to Agentry staff. */
export function RecentRuns({ runs, staff }: { runs: AgentRun[]; staff: boolean }) {
  return (
    <Card>
      <CardHeader><CardTitle>What it did recently</CardTitle></CardHeader>
      <CardBody className="p-0">
        {runs.length === 0 ? <p className="px-5 py-6 text-sm text-muted">Nothing yet.</p> : (
          <ul className="divide-y divide-line">
            {runs.map((r) => (
              <li key={r.id} className="px-5 py-3">
                <details>
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm">
                    <span aria-hidden="true">{r.status === "ok" ? "✓" : r.status === "failed" ? "✗" : "…"}</span>
                    <span className="min-w-0 flex-1 font-medium">{KIND[r.kind] ?? r.kind}</span>
                    {r.status === "failed" && <Badge tone="danger">failed</Badge>}
                    {r.status === "running" && <Badge tone="lime">working</Badge>}
                    <span className="text-xs text-muted">{fmtSecs(r.seconds)} · {timeAgo(r.started_at)}</span>
                    {staff && r.cost_usd !== undefined && <span className="text-xs text-muted">${Number(r.cost_usd).toFixed(4)} · {r.model_calls} calls</span>}
                  </summary>
                  <ol className="mt-2 space-y-1 pl-6 text-xs text-ink-soft">
                    {r.steps.map((s, i) => (
                      <li key={i}>{s.name}{s.detail ? `: ${Object.entries(s.detail).map(([k, v]) => `${k.replace("_", " ")} ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(", ")}` : ""}
                        <span className="text-muted"> ({fmtSecs(s.ms / 1000)})</span></li>
                    ))}
                    {r.error && <li className="text-danger">{r.error}</li>}
                    {r.steps.length === 0 && !r.error && <li className="text-muted">No details recorded.</li>}
                  </ol>
                </details>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
