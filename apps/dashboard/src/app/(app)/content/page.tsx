import { Badge, buttonClasses, Card, CardBody, CardHeader, CardTitle, Stat } from "@agentry/ui";
import Link from "next/link";
import { NewContent } from "@/components/content";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Content" };

type Source = { id: string; title: string; kind: string; status: string; error: string | null; created_at: string; duration_seconds: number | null;
                posts: number; to_review: number; approved: number; published: number };
const STATUS: Record<string, string> = { uploaded: "Queued", transcribing: "Transcribing", finding_moments: "Finding moments", writing: "Writing posts",
                                         ready: "Ready", failed: "Stopped" };

export default async function ContentPage() {
  const active = await requirePage("content");
  const [d, res] = await Promise.all([
    api<{ items: Source[]; can_edit: boolean }>("/org/content/sources", { orgId: active.id }),
    api<{ recordings: number; generated: number; approved_as_written_pct: number | null; published: number; turnaround_minutes: number | null }>(
      "/org/content/results?days=30", { orgId: active.id }),
  ]);
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Content</h1>
          <p className="mt-1 text-muted">One long video or podcast becomes a month of posts for LinkedIn, Instagram and X, in your words.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/content/calendar" className={buttonClasses("secondary", "md")}>Calendar</Link>
          <Link href="/content/brand" className={buttonClasses("secondary", "md")}>Brand kit</Link>
        </div>
      </header>
      <p className="rounded-xl border-2 border-dashed border-line px-4 py-3 text-sm text-muted">
        Test mode: scheduled posts are recorded at their time, not posted, until Agentry connects your social accounts.
      </p>
      {res.generated > 0 && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Last 30 days">
          <Stat label="Recordings, last 30 days" value={String(res.recordings)} />
          <Stat label="Posts written" value={String(res.generated)} />
          <Stat label="Approved without changes" value={res.approved_as_written_pct != null ? `${res.approved_as_written_pct}%` : "—"} />
          <Stat label="Upload to drafts (median)" value={res.turnaround_minutes != null ? `${Math.max(1, Math.round(res.turnaround_minutes))} min` : "—"} />
        </section>
      )}
      {d.can_edit && <Card><CardHeader><CardTitle>New recording</CardTitle></CardHeader><CardBody><NewContent /></CardBody></Card>}
      {d.items.length === 0 ? <p className="text-muted">Nothing yet.</p> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted"><tr>
              <th className="px-4 py-3 font-medium">Recording</th><th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 text-right font-medium">Posts</th><th className="px-4 py-3 text-right font-medium">To review</th>
              <th className="px-4 py-3 text-right font-medium">Approved</th><th className="px-4 py-3 text-right font-medium">Published</th>
            </tr></thead>
            <tbody className="divide-y divide-line">{d.items.map((s) => (
              <tr key={s.id}>
                <td className="px-4 py-3"><Link href={`/content/${s.id}`} className="font-medium hover:underline">{s.title}</Link>
                  <div className="text-xs text-muted">{s.duration_seconds ? `${Math.round(s.duration_seconds / 60)} min · ` : ""}{new Date(s.created_at).toLocaleDateString("en-IN")}</div></td>
                <td className="px-4 py-3"><Badge tone={s.status === "ready" ? "lime" : s.status === "failed" ? "danger" : "neutral"}>{STATUS[s.status] ?? s.status}</Badge></td>
                <td className="px-4 py-3 text-right tabular-nums">{s.posts}</td>
                <td className="px-4 py-3 text-right tabular-nums">{s.to_review}</td>
                <td className="px-4 py-3 text-right tabular-nums">{s.approved}</td>
                <td className="px-4 py-3 text-right font-semibold tabular-nums">{s.published}</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
