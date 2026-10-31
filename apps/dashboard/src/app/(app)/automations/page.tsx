import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { statusLabels } from "@/lib/format";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe } from "@/lib/session";

export const metadata = { title: "Automations" };

export type Automation = {
  template_key: string; name: string; description: string | null; status: string; metrics: string[];
  config: Record<string, unknown>; config_schema: { properties: Record<string, object> } | null; updated_at: string;
};

const CONVERSATIONAL = ["website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"];

export default async function AutomationsPage() {
  const [active, me] = await Promise.all([getActiveOrg(), getMe()]);
  if (!active) redirect("/home");
  const canTalk = me.is_staff || can(active.role, "automation", "configure");
  const canGovern = canTalk;  // owners and managers see autonomy settings (only the owner changes them)
  let items: Automation[];
  try {
    items = (await api<{ items: Automation[] }>("/org/automations", { orgId: active.id })).items;
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Automations</h1>
          <p className="mt-1 text-muted">The agents working for {active.name}.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canGovern && <Link href="/settings/autonomy" className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 text-sm font-semibold hover:border-ink">Autonomy &amp; limits</Link>}
          {canTalk && items.some((a) => CONVERSATIONAL.includes(a.template_key)) && (
            <Link href="/talk" className="inline-flex h-10 items-center rounded-xl border-2 border-ink px-4 text-sm font-semibold hover:bg-lime-soft">🎙 Talk to your agent</Link>
          )}
        </div>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((a) => (
          <Link key={a.template_key} href={`/automations/${a.template_key}`}>
            <Card className="h-full p-6 transition-transform hover:-translate-y-0.5 hover:shadow-[4px_4px_0_0_var(--ink)]">
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-display text-xl font-bold">{a.name}</h2>
                <Badge tone={statusLabels[a.status]?.tone ?? "neutral"}>{statusLabels[a.status]?.label ?? a.status}</Badge>
              </div>
              <p className="mt-2 text-sm text-ink-soft">{a.description ?? "Coming soon in your plan."}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
