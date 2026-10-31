import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { CheckReviews, ReplyBox } from "@/components/reviews";
import { timeAgo } from "@/lib/format";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Reviews" };

type Stats = { count: number; average: number | null; replied: number; low: number; themes: { t: string; bad: number; good: number }[] };
type Review = { id: string; source: string; author: string | null; rating: number; body: string | null; reviewed_at: string; sentiment: string | null;
                topics: string[]; urgent: boolean; reply: string | null; reply_status: string; replied_at: string | null };
type Data = { items: Review[]; last30: Stats; prev30: Stats; total: number; average: number | null; asked_30d: number; sample: boolean;
              review_link: string | null; can_act: boolean; watcher: { last_checked_at: string | null } | null };

const FILTERS = [["all", "All"], ["unanswered", "Needs a reply"], ["low", "1-2 stars"]] as const;
const TONE: Record<string, "success" | "warning" | "danger"> = { positive: "success", mixed: "warning", negative: "danger" };

export default async function ReviewsPage({ searchParams }: { searchParams: Promise<{ filter?: string }> }) {
  const active = await requirePage("reviews");
  const { filter = "all" } = await searchParams;
  const f = FILTERS.some(([k]) => k === filter) ? filter : "all";
  const d = await api<Data>(`/org/reviews?filter=${f}`, { orgId: active.id });
  const trend = d.last30.average != null && d.prev30.average != null ? d.last30.average - d.prev30.average : null;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Reviews</h1>
          <p className="mt-1 text-muted">
            New reviews are checked every 6 hours{d.watcher?.last_checked_at ? ` (last ${timeAgo(d.watcher.last_checked_at)})` : ""}. Bad ones alert you at once;
            every reply is drafted for you to approve.
          </p>
        </div>
        {d.can_act && <CheckReviews />}
      </header>
      {d.sample && (
        <p className="rounded-2xl border-2 border-line px-4 py-3 text-sm text-muted">
          Sample reviews for now: Google Business Profile connects once Google approves API access for Agentry. Replies are recorded, not posted to Google yet.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-4">
        <Card className="p-4"><p className="text-xs text-muted">Average (30 days)</p>
          <p className="font-display text-3xl font-bold">{d.last30.average != null ? `${d.last30.average.toFixed(1)}★` : "—"}</p>
          {trend != null && <p className={`text-xs ${trend >= 0 ? "text-success" : "text-danger"}`}>{trend >= 0 ? "▲" : "▼"} {Math.abs(trend).toFixed(1)} vs the 30 days before</p>}</Card>
        <Card className="p-4"><p className="text-xs text-muted">New reviews (30 days)</p><p className="font-display text-3xl font-bold">{d.last30.count}</p>
          <p className="text-xs text-muted">{d.total} in all{d.average != null ? `, ${d.average.toFixed(1)}★ overall` : ""}</p></Card>
        <Card className="p-4"><p className="text-xs text-muted">Replied (30 days)</p><p className="font-display text-3xl font-bold">{d.last30.replied}/{d.last30.count}</p></Card>
        <Card className="p-4"><p className="text-xs text-muted">Asked for a review (30 days)</p><p className="font-display text-3xl font-bold">{d.asked_30d}</p>
          {!d.review_link && <p className="text-xs text-warning">Add your Google review link in <Link className="underline" href="/automations/reviews">settings</Link></p>}</Card>
      </div>
      {d.last30.themes.length > 0 && (
        <p className="text-sm text-ink-soft">
          Themes this month: {d.last30.themes.map((t) => `${t.t} (${t.good} 👍 ${t.bad} 👎)`).join(" · ")}
        </p>
      )}
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="Filter">
        {FILTERS.map(([k, label]) => (
          <Link key={k} href={`/reviews?filter=${k}`} aria-current={f === k ? "page" : undefined}
                className={`rounded-full border-2 px-3 py-1 font-semibold ${f === k ? "border-ink bg-lime-soft" : "border-line hover:border-ink"}`}>{label}</Link>
        ))}
      </nav>
      <div className="space-y-3">
        {d.items.length === 0 && <p className="text-muted">No reviews here.</p>}
        {d.items.map((r) => (
          <Card key={r.id} className={`p-5 ${r.urgent ? "border-danger" : ""}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg tracking-tight text-warning" aria-label={`${r.rating} of 5 stars`}>{"★".repeat(r.rating)}<span className="text-line">{"★".repeat(5 - r.rating)}</span></span>
              <span className="font-semibold">{r.author ?? "Anonymous"}</span>
              <span className="text-xs text-muted">{timeAgo(r.reviewed_at)}</span>
              {r.urgent && <Badge tone="danger">Urgent</Badge>}
              {r.sentiment && <Badge tone={TONE[r.sentiment]}>{r.sentiment}</Badge>}
              {r.topics.map((t) => <Badge key={t}>{t}</Badge>)}
            </div>
            {r.body && <p className="mt-2 text-ink-soft">{r.body}</p>}
            {r.reply_status === "posted" && r.reply && (
              <div className="mt-3 rounded-xl bg-paper p-3 text-sm"><p className="text-xs font-semibold text-muted">Your reply · {r.replied_at ? timeAgo(r.replied_at) : ""}</p><p className="mt-1">{r.reply}</p></div>
            )}
            {r.reply_status === "skipped" && <p className="mt-2 text-xs text-muted">Not replying to this one.</p>}
            {d.can_act && ["drafted", "none"].includes(r.reply_status) && <ReplyBox id={r.id} draft={r.reply ?? ""} />}
          </Card>
        ))}
      </div>
    </div>
  );
}
