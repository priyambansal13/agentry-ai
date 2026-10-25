import { Badge, Card, CardBody, CardHeader, CardTitle, cn } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { automationNames, timeAgo } from "@/lib/format";
import { AddLeadForm } from "@/components/campaign-tools";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getFeatures, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Leads" };

type Lead = {
  id: string; source: string; stage: string; qualification: Record<string, string>; owner_automation: string | null;
  touches: number; last_touch_at: string | null; updated_at: string; name: string | null; email: string | null; phone: string | null;
  conversation_id: string | null;
};
const PIPELINE = ["new", "nurture", "contacted", "engaged", "qualified", "booked", "showed", "won"];
const STAGE_TONE: Record<string, "lime" | "success" | "warning" | "neutral" | "danger"> = {
  booked: "success", showed: "success", won: "success", qualified: "lime", engaged: "lime", opted_out: "danger", disqualified: "neutral",
};

type Source = { id: string; name: string; url: string };

export default async function LeadsPage() {
  const [active, me] = await Promise.all([getActiveOrg(), getMe()]);
  await requirePage("leads");
  if (!active) redirect("/home");
  const features = await getFeatures(active.id);
  const canForms = features.pages.includes("lead_forms") && (me.is_staff || can(active.role, "automation", "configure"));
  const sources = canForms ? (await api<{ items: Source[] }>("/org/lead-sources", { orgId: active.id })).items : [];
  let d: { items: Lead[]; by_stage: Record<string, number> };
  try {
    d = await api("/org/leads", { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Leads</h1>
        <p className="mt-1 text-muted">One list for every lead, whichever agent found them. Only one agent talks to a lead at a time.</p>
      </header>
      <ol className="grid grid-cols-4 gap-2 sm:grid-cols-8" aria-label="Pipeline">
        {PIPELINE.map((s, i) => (
          <li key={s} className={cn("rounded-xl border px-3 py-2", (d.by_stage[s] ?? 0) > 0 ? "border-ink bg-card" : "border-line text-muted")}>
            <div className="text-xs capitalize text-muted">{i + 1}. {s}</div>
            <div className="text-2xl font-semibold">{d.by_stage[s] ?? 0}</div>
          </li>
        ))}
      </ol>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr>
            <th className="px-4 py-3 font-medium">Lead</th><th className="px-4 py-3 font-medium">Wants</th><th className="px-4 py-3 font-medium">Stage</th>
            <th className="px-4 py-3 font-medium">Talking to them</th><th className="px-4 py-3 font-medium">Source</th><th className="px-4 py-3 font-medium">Updated</th>
          </tr></thead>
          <tbody className="divide-y divide-line">
            {d.items.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">No leads yet.</td></tr>}
            {d.items.map((l) => (
              <tr key={l.id}>
                <td className="px-4 py-3"><div className="font-medium">{l.conversation_id ? <Link className="hover:underline" href={`/conversations/${l.conversation_id}`}>{l.name ?? l.email ?? l.phone}</Link> : (l.name ?? l.email ?? l.phone)}</div>
                  <div className="text-xs text-muted">{l.phone ?? l.email}</div></td>
                <td className="max-w-xs px-4 py-3 text-ink-soft">{l.qualification.need ?? l.qualification.interest ?? "—"}
                  {(l.qualification.budget || l.qualification.timeline) && <div className="text-xs text-muted">{[l.qualification.budget, l.qualification.timeline].filter(Boolean).join(" · ")}</div>}</td>
                <td className="px-4 py-3"><Badge tone={STAGE_TONE[l.stage] ?? "neutral"}>{l.stage.replace("_", " ")}</Badge></td>
                <td className="px-4 py-3 text-xs">{l.owner_automation ? automationNames[l.owner_automation] ?? l.owner_automation : "—"}
                  {l.touches > 0 && <div className="text-muted">{l.touches} message{l.touches === 1 ? "" : "s"} sent</div>}</td>
                <td className="px-4 py-3 text-xs text-muted">{l.source.replace("_", " ")}</td>
                <td className="px-4 py-3 text-xs text-muted">{timeAgo(l.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {canForms && (
        <Card>
          <CardHeader><CardTitle>Lead forms (speed-to-lead)</CardTitle></CardHeader>
          <CardBody className="space-y-4">
            <p className="text-sm text-muted">Post your website form (or Meta lead ads via Zapier/Make) to one of these links. Fields: name, phone, email, message, whatsapp_optin. New leads get a message within about a minute.</p>
            <ul className="space-y-2">{sources.map((s) => (
              <li key={s.id} className="rounded-xl bg-paper p-3 text-sm"><div className="font-medium">{s.name}</div><code className="text-xs break-all text-muted">{s.url}</code></li>
            ))}{sources.length === 0 && <li className="text-sm text-muted">No lead forms yet.</li>}</ul>
            <AddLeadForm />
          </CardBody>
        </Card>
      )}
    </div>
  );
}
