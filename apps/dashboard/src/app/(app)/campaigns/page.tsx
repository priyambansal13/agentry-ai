import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { redirect } from "next/navigation";
import { OldLeadsImport, StartCampaign } from "@/components/campaign-tools";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Campaigns" };

type Campaign = { id: string; name: string; status: string; per_hour: number; created_at: string; active: number; contacted: number;
                  replied: number; booked: number; stats: { eligible?: number } };

export default async function CampaignsPage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  await requirePage("campaigns");
  if (!active) redirect("/home");
  const canEdit = me.is_staff || can(active.role, "automation", "configure");
  const d = await api<{ items: Campaign[]; eligible_now: number; blocked: Record<string, number> }>("/org/campaigns", { orgId: active.id });
  const blocked = Object.entries(d.blocked);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Campaigns</h1>
        <p className="mt-1 text-muted">Win back old leads with no new ad spend.</p>
      </header>
      <Card>
        <CardHeader><CardTitle>Lead reactivation</CardTitle><Badge tone="lime">{d.eligible_now} ready to contact</Badge></CardHeader>
        <CardBody className="space-y-6">
          {canEdit && <OldLeadsImport />}
          {blocked.length > 0 && (
            <div className="text-sm">
              <p className="font-medium">Left out, to stay compliant:</p>
              <ul className="mt-1 list-disc pl-5 text-muted">{blocked.map(([why, n]) => <li key={why}>{n} × {why}</li>)}</ul>
            </div>
          )}
          {canEdit && <StartCampaign eligible={d.eligible_now} />}
        </CardBody>
      </Card>
      {d.items.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted"><tr>
              <th className="px-4 py-3 font-medium">Campaign</th><th className="px-4 py-3 text-right font-medium">People</th>
              <th className="px-4 py-3 text-right font-medium">Contacted</th><th className="px-4 py-3 text-right font-medium">Replied</th>
              <th className="px-4 py-3 text-right font-medium">Booked</th><th className="px-4 py-3 font-medium">Pace</th>
            </tr></thead>
            <tbody className="divide-y divide-line">
              {d.items.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-3"><div className="font-medium">{c.name}</div><div className="text-xs text-muted">{new Date(c.created_at).toLocaleDateString("en-IN")}</div></td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.stats.eligible ?? "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.contacted}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.replied}</td>
                  <td className="px-4 py-3 text-right tabular-nums font-semibold">{c.booked}</td>
                  <td className="px-4 py-3 text-xs text-muted">{c.per_hour}/hour</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
