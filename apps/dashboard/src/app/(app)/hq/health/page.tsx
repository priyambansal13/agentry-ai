import { Badge, Card, CardBody } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Client health · Agentry HQ" };

type H = { org_id: string; name: string; status: string; agents: number; score: number; level: "healthy" | "watch" | "at_risk"; reasons: string[];
  work_14d: number; work_prev_14d: number; last_login: string | null };
const TONE = { healthy: "success", watch: "warning", at_risk: "danger" } as const;

export default async function HealthPage() {
  const me = await getMe();
  if (!me.is_staff) redirect("/home");
  const d = await api<{ items: H[]; counts: Record<string, number> }>("/hq/health");
  return (
    <div className="space-y-6">
      <header>
        <p className="font-hand text-xl text-muted">Agentry HQ</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Client health</h1>
        <p className="mt-1 max-w-3xl text-muted">Who needs a call before they cancel: falling activity, nobody logging in, cards piling up, broken connections, failing
          runs, unpaid statements. The at-risk list is emailed to the Agentry team every Monday.</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-3">
        {(["at_risk", "watch", "healthy"] as const).map((k) => (
          <Card key={k}><CardBody><p className="text-sm text-muted">{k.replace("_", " ")}</p><p className="text-2xl font-semibold">{d.counts[k] ?? 0}</p></CardBody></Card>))}
      </div>
      <Card><CardBody className="p-0">
        <ul className="divide-y divide-line">{d.items.map((c) => (
          <li key={c.org_id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
            <div className="min-w-0"><Link href={`/hq/${c.org_id}`} className="font-semibold hover:underline">{c.name}</Link>
              <p className="text-xs text-muted">{c.agents} agents · {c.work_14d} actions in 14 days (was {c.work_prev_14d}) · last login {c.last_login ? new Date(c.last_login).toLocaleDateString("en-IN") : "never"}</p>
              {c.reasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm">{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}</div>
            <span className="flex items-center gap-2"><span className="text-xl font-semibold">{c.score}</span><Badge tone={TONE[c.level]}>{c.level.replace("_", " ")}</Badge></span>
          </li>))}</ul>
      </CardBody></Card>
    </div>
  );
}
