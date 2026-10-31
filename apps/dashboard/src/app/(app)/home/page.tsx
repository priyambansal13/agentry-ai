import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@agentry/ui";
import Link from "next/link";
import { type Pulse, PulseCard } from "@/components/pulse";
import { redirect } from "next/navigation";
import { Sparkline } from "@/components/sparkline";
import { TrendChart } from "@/components/trend-chart";
import { automationNames, formatMetric, statusLabels } from "@/lib/format";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe, getSession } from "@/lib/session";

export const metadata = { title: "Home" };

type Tile = {
  key: string; name: string; unit: string; higher_is_better: boolean; value: number; previous: number;
  delta: number | null; series: { day: string; value: number }[];
};
type Opportunity = {
  days: number; currency: string; emails_triaged: number; urgent: number; enquiries: number; enquiries_never_answered: number;
  enquiries_answered_after_24h: number; invoice_emails: number; revenue_at_risk: number | null; method: string;
};
type Org = {
  settings: { status: string; currency: string; timezone: string } | null;
  automations: { template_key: string; status: string }[];
  onboarding: { step_key: string; status: string; blocker: string | null }[];
};

const STEP_LABELS: Record<string, string> = {
  profile: "Business profile", plan: "Plan & agreement", team: "Team", connect: "Connect accounts", import: "Data import",
  knowledge: "Knowledge & offers", settings: "Automation settings", persona: "Persona & voice", compliance: "Compliance",
  test: "Test", go_live: "Go live",
};

export default async function HomePage() {
  const [session, me, active] = await Promise.all([getSession(), getMe(), getActiveOrg()]);
  if (!active) redirect(me.is_staff ? "/hq" : "/sign-in");
  const [org, overview] = await Promise.all([
    api<Org>("/org", { orgId: active.id }),
    api<{ days: number; currency: string; tiles: Tile[] }>("/org/overview?days=30", { orgId: active.id }),
  ]);
  const lead = overview.tiles[0];
  const canConverse = me.is_staff || can(active.role, "conversation", "read");
  const canSetUp = me.is_staff || can(active.role, "automation", "configure");
  const hasTriage = org.automations.some((a) => a.template_key === "inbox_triage" && a.status !== "setup");
  const [pending, opportunity] = await Promise.all([
    canConverse ? api<{ pending_by_kind: Record<string, number> }>("/org/approvals?limit=1", { orgId: active.id })
      .then((r) => Object.values(r.pending_by_kind).reduce((a, b) => a + b, 0)).catch(() => 0) : Promise.resolve(0),
    hasTriage ? api<Opportunity>("/org/reports/opportunity?days=30", { orgId: active.id }).catch(() => null) : Promise.resolve(null),
  ]);
  const doneSteps = org.onboarding.filter((s) => s.status === "done").length;
  // Skip titles and initials ("Dr.", "S.") so "Dr. Neha Kulkarni" -> "Neha", "S. Natarajan" -> "Natarajan".
  const brief = org.settings?.status === "live" ? await api<Pulse>("/org/pulse", { orgId: active.id }).catch(() => null) : null;
  const firstName = session.user.name.split(" ").find((w) => w.length > 2 && !w.endsWith(".")) || session.user.name || "there";

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-hand text-xl text-muted">Hi {firstName},</p>
          <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">
            Here&apos;s what your agents did <span className="highlight">this month</span>
          </h1>
        </div>
        <Badge tone={statusLabels[active.status]?.tone ?? "neutral"}>{statusLabels[active.status]?.label ?? active.status}</Badge>
      </header>

      {brief && <PulseCard p={brief} />}

      {pending > 0 && (
        <Link href="/needs-you" className="flex items-center justify-between gap-4 rounded-2xl border-2 border-ink bg-lime px-5 py-4 text-lime-ink transition-transform hover:-translate-y-0.5">
          <span className="font-semibold">{pending} {pending === 1 ? "item needs" : "items need"} you: drafts to approve and people asking for a person</span>
          <span aria-hidden="true">→</span>
        </Link>
      )}

      {org.settings?.status !== "live" && org.onboarding.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{canSetUp ? <Link href="/onboarding" className="hover:underline">Getting you live →</Link> : "Getting you live"}</CardTitle>
            <span className="text-sm text-muted">{doneSteps} of {org.onboarding.length} steps done</span>
          </CardHeader>
          <CardBody>
            <div className="h-2 overflow-hidden rounded-full bg-paper" role="progressbar" aria-valuenow={doneSteps} aria-valuemax={org.onboarding.length}>
              <div className="h-full rounded-full bg-lime" style={{ width: `${(doneSteps / org.onboarding.length) * 100}%` }} />
            </div>
            <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {org.onboarding.map((s) => (
                <li key={s.step_key} className="flex items-start gap-2 text-sm">
                  <span className={s.status === "done" ? "text-success" : s.status === "blocked" ? "text-warning" : "text-muted"} aria-hidden="true">
                    {s.status === "done" ? "✓" : s.status === "blocked" ? "!" : "○"}
                  </span>
                  <span>
                    {STEP_LABELS[s.step_key] ?? s.step_key}
                    {s.blocker && <span className="block text-xs text-warning">Waiting: {s.blocker}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      )}

      {overview.tiles.length === 0 ? (
        <Card><CardBody className="py-10 text-center text-muted">No activity yet. Numbers appear here as soon as your agents start working.</CardBody></Card>
      ) : (
        <section aria-label="Results, last 30 days" className={`grid gap-4 sm:grid-cols-2 ${overview.tiles.length % 3 === 0 ? "lg:grid-cols-3" : "lg:grid-cols-4"}`}>
          {overview.tiles.map((t) => (
            <Stat
              key={t.key}
              label={t.name}
              value={formatMetric(t.value, t.unit, overview.currency)}
              delta={t.delta}
              deltaLabel="vs previous 30 days"
              higherIsBetter={t.higher_is_better}
              trend={<Sparkline values={t.series.map((p) => p.value)} label={t.name} />}
            />
          ))}
        </section>
      )}

      {opportunity && opportunity.emails_triaged > 0 && (
        <Card>
          <CardHeader><CardTitle>What your inbox is telling us</CardTitle><span className="text-sm text-muted">last {opportunity.days} days</span></CardHeader>
          <CardBody>
            <dl className="grid gap-4 sm:grid-cols-4">
              <div><dt className="text-sm text-muted">Emails sorted</dt><dd className="text-2xl font-semibold">{opportunity.emails_triaged}</dd></div>
              <div><dt className="text-sm text-muted">New enquiries</dt><dd className="text-2xl font-semibold">{opportunity.enquiries}</dd></div>
              <div><dt className="text-sm text-muted">Enquiries not answered yet</dt><dd className={`text-2xl font-semibold ${opportunity.enquiries_never_answered ? "text-danger" : ""}`}>{opportunity.enquiries_never_answered}</dd></div>
              <div><dt className="text-sm text-muted">Revenue at risk</dt><dd className="text-2xl font-semibold">{opportunity.revenue_at_risk != null ? formatMetric(opportunity.revenue_at_risk, "currency", opportunity.currency) : "—"}</dd></div>
            </dl>
            <p className="mt-3 text-xs text-muted">Estimate: {opportunity.method}.</p>
          </CardBody>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        {lead && (
          <Card>
            <CardHeader>
              <CardTitle>{lead.name} per day</CardTitle>
              <span className="text-sm text-muted">last 30 days</span>
            </CardHeader>
            <CardBody>
              <TrendChart data={lead.series} format={lead.unit === "currency" ? "currency" : "count"} currency={overview.currency} />
            </CardBody>
          </Card>
        )}
        <Card>
          <CardHeader><CardTitle>Your agents</CardTitle></CardHeader>
          <CardBody>
            <ul className="divide-y divide-line">
              {org.automations.map((a) => (
                <li key={a.template_key} className="flex items-center justify-between gap-3 py-3">
                  <Link href={`/automations/${a.template_key}`} className="text-sm font-medium hover:underline">{automationNames[a.template_key] ?? a.template_key}</Link>
                  <Badge tone={statusLabels[a.status]?.tone ?? "neutral"}>{statusLabels[a.status]?.label ?? a.status}</Badge>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
