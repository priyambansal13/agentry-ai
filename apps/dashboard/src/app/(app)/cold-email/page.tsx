import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { NewColdCampaign } from "@/components/cold-email";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Cold email" };

type Campaign = { id: string; name: string; settings: { source?: string; query?: string; city?: string }; build_status: string | null;
                  build_error: string | null; stats: { total?: number; processed?: number }; created_at: string;
                  found: number; verified: number; approved: number; to_review: number; status: string; emailed: number; interested: number };

export default async function ColdEmailPage() {
  const active = await requirePage("cold-email");
  const d = await api<{ items: Campaign[]; can_edit: boolean }>("/org/cold-email/campaigns", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Cold email</h1>
        <p className="mt-1 text-muted">Find businesses that fit, the person who decides, and one honest first line from their own website.</p>
      </header>
      <p className="rounded-xl border-2 border-dashed border-line px-4 py-3 text-sm text-muted">
        Searches use a sample list of Pune dental clinics until Google Places is connected, and emails go through a test sender
        (recorded, not delivered) until Agentry connects your sending domains.
      </p>
      {d.can_edit && (
        <Card>
          <CardHeader><CardTitle>New prospect list</CardTitle></CardHeader>
          <CardBody><NewColdCampaign /></CardBody>
        </Card>
      )}
      {d.items.length === 0 ? (
        <p className="text-muted">No lists yet.{d.can_edit ? " Build your first one above." : ""}</p>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted"><tr>
              <th className="px-4 py-3 font-medium">List</th><th className="px-4 py-3 text-right font-medium">Businesses</th>
              <th className="px-4 py-3 text-right font-medium">Verified people</th><th className="px-4 py-3 text-right font-medium">To review</th>
              <th className="px-4 py-3 text-right font-medium">Approved</th>
              <th className="px-4 py-3 text-right font-medium">Emailed</th><th className="px-4 py-3 text-right font-medium">Interested</th>
            </tr></thead>
            <tbody className="divide-y divide-line">
              {d.items.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-3">
                    <Link href={`/cold-email/${c.id}`} className="font-medium underline-offset-2 hover:underline">{c.name}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                      {c.settings.source === "csv" ? "Uploaded list" : `${c.settings.query} · ${c.settings.city}`}
                      · {new Date(c.created_at).toLocaleDateString("en-IN")}
                      {c.build_status === "building" && <Badge tone="lime">Building {c.stats.processed ?? 0}/{c.stats.total ?? "…"}</Badge>}
                      {c.build_status === "failed" && <Badge tone="danger">Stopped</Badge>}
                      {c.status === "running" && <Badge tone="lime">Sending</Badge>}{c.status === "paused" && <Badge tone="warning">Paused</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.found}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.verified}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.to_review}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.approved}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.emailed}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">{c.interested}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
