import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ConfigForm } from "@/components/config-form";
import { type InboxInsights, InboxInsightsCards } from "@/components/inbox-insights";
import { WritingStyleCard } from "@/components/writing-style";
import { PauseToggle } from "@/components/pause-toggle";
import { Sparkline } from "@/components/sparkline";
import { categoryTone, formatMetric, statusLabels, timeAgo } from "@/lib/format";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe } from "@/lib/session";
import type { Automation } from "../page";

type Tile = { key: string; name: string; unit: string; value: number; delta: number | null; higher_is_better: boolean; series: { value: number }[] };
type Row = { id: string; subject: string | null; contact_email: string | null; contact_name: string | null; last_message_at: string;
             triage: { category: string; urgent?: boolean; summary?: string } | null; preview: string | null; channel: string };

export default async function AutomationPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  const [{ items }, overview] = await Promise.all([
    api<{ items: Automation[] }>("/org/automations", { orgId: active.id }),
    api<{ currency: string; tiles: Tile[] }>("/org/overview?days=30", { orgId: active.id }),
  ]);
  const a = items.find((x) => x.template_key === key);
  if (!a) notFound();
  const channel = key === "inbox_triage" ? "email" : key === "website_chat" ? "web_chat" : null;
  const recent = channel && can(active.role, "conversation", "read") || me.is_staff
    ? (await api<{ items: Row[] }>(`/org/conversations?limit=8${channel ? `&channel=${channel}` : ""}`, { orgId: active.id })).items
    : [];
  const tiles = overview.tiles.filter((t) => a.metrics.includes(t.key));
  const canConfigure = me.is_staff || can(active.role, "automation", "configure");
  const canPause = me.is_staff || can(active.role, "automation", "pause");
  const insights = key === "inbox_triage" ? await api<InboxInsights>("/org/inbox/insights", { orgId: active.id }).catch(() => null) : null;

  return (
    <div className="space-y-8">
      <Link href="/automations" className="text-sm text-muted hover:text-ink">← Automations</Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">{a.name}</h1>
          <p className="mt-1 max-w-2xl text-muted">{a.description}</p>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={statusLabels[a.status]?.tone ?? "neutral"}>{statusLabels[a.status]?.label ?? a.status}</Badge>
          {canPause && <PauseToggle automationKey={key} status={a.status} canConfigure={canConfigure} />}
        </div>
      </header>
      {a.status === "approval_mode" && (
        <p className="rounded-2xl border-2 border-dashed border-lime bg-lime-soft px-4 py-3 text-sm">
          Approval mode: every message this agent writes waits in <Link href="/needs-you" className="font-semibold underline">Needs you</Link> until you approve it.
        </p>
      )}
      {tiles.length > 0 && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Results, last 30 days">
          {tiles.map((t) => (
            <Stat key={t.key} label={t.name} value={formatMetric(t.value, t.unit, overview.currency)} delta={t.delta}
              deltaLabel="vs previous 30 days" higherIsBetter={t.higher_is_better} trend={<Sparkline values={t.series.map((p) => p.value)} label={t.name} />} />
          ))}
        </section>
      )}
      {insights && <InboxInsightsCards d={insights} />}
      {insights && <WritingStyleCard style={insights.writing_style} canConfigure={canConfigure} />}
      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader><CardTitle>Recent activity</CardTitle><Link href={`/conversations${channel ? `?channel=${channel}` : ""}`} className="text-sm text-muted hover:text-ink">All →</Link></CardHeader>
          <CardBody className="divide-y divide-line p-0">
            {recent.length === 0 && <p className="px-5 py-6 text-sm text-muted">Nothing yet.</p>}
            {recent.map((r) => (
              <Link key={r.id} href={`/conversations/${r.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-paper">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{r.subject ?? r.contact_name ?? r.contact_email ?? "Website visitor"}</div>
                  <div className="truncate text-xs text-muted">{r.triage?.summary && r.triage.summary !== r.subject ? r.triage.summary : r.preview}</div>
                </div>
                {r.triage && <Badge tone={categoryTone[r.triage.category] ?? "neutral"}>{r.triage.category}</Badge>}
                <span className="text-xs text-muted">{timeAgo(r.last_message_at)}</span>
              </Link>
            ))}
          </CardBody>
        </Card>
        {a.config_schema && (
          <Card>
            <CardHeader><CardTitle>Settings</CardTitle></CardHeader>
            <CardBody>
              <ConfigForm automationKey={key} schema={a.config_schema as never} value={a.config} isStaff={me.is_staff} canEdit={canConfigure} />
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
