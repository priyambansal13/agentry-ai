import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { RefreshWhileBuilding } from "@/components/cold-email";
import { BulkActions, type Clip, ClipCard, type ContentPost, CutClips, DropMoment, NewBackground, LongformPanel, PostCard, SourceActions } from "@/components/content";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Content review" };

type Moment = { id: string; rank: number; start_s: number; end_s: number; quote: string; speaker: string | null; hook: string; insight: string;
                topic: string | null; dropped: boolean };
type Source = { id: string; title: string; kind: string; source_url: string | null; status: string; error: string | null; progress: { moments_total?: number; moments_done?: number };
                duration_seconds: number | null; moments: Moment[]; posts: (ContentPost & { moment_id: string })[]; clips: Record<string, Clip>; can_edit: boolean; ai_images?: boolean };
const STEP: Record<string, string> = { downloading: "Downloading from the link…", uploaded: "Queued…", transcribing: "Transcribing the recording…", finding_moments: "Finding the best moments…",
                                       writing: "Writing posts and drawing images…", cutting_clips: "Cutting vertical clips…" };

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export default async function ContentSourcePage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("content");
  const { id } = await params;
  let s: Source;
  try {
    s = await api<Source>(`/org/content/sources/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const longform = await api<{ items: Parameters<typeof LongformPanel>[0]["items"] }>(`/org/content/sources/${id}/longform`, { orgId: active.id })
    .then((r) => r.items).catch(() => []);
  const working = !["ready", "failed"].includes(s.status) || longform.some((l) => l.status === "writing")
    || Object.values(s.clips).some((c) => c.status === "cutting");
  const ready = s.posts.filter((p) => p.review === "pending").length;
  const unscheduled = s.posts.filter((p) => p.review === "approved" && !p.scheduled_at && !p.published_at).length;
  const attention = s.posts.filter((p) => p.review === "needs_attention").length;
  return (
    <div className="space-y-6">
      <RefreshWhileBuilding building={working} />
      <header>
        <Link href="/content" className="text-sm text-muted hover:text-ink">← Content</Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">{s.title}</h1>
            {s.source_url && <p className="mt-1 text-sm"><a href={s.source_url} target="_blank" rel="noopener noreferrer" className="text-muted underline hover:text-ink">
              From {new URL(s.source_url).hostname.replace(/^www\./, "")} ↗</a></p>}
            <p className="mt-1 text-muted">{s.duration_seconds ? `${Math.round(s.duration_seconds / 60)} minutes · ` : ""}{s.moments.length} moments · {s.posts.length} posts</p>
          </div>
          {s.can_edit && <span className="inline-flex flex-wrap items-center gap-2">
            {s.kind === "video" && s.status === "ready" && <CutClips sourceId={s.id} hasClips={Object.keys(s.clips).length > 0} />}
            <SourceActions id={s.id} failed={s.status === "failed"} /></span>}
        </div>
      </header>
      {working && <p role="status" className="rounded-xl border-2 border-lime bg-lime-soft px-4 py-3 text-sm">
        {STEP[s.status]}{s.status === "writing" && s.progress.moments_total ? ` ${s.progress.moments_done ?? 0} of ${s.progress.moments_total} moments done.` : ""} This page updates by itself.</p>}
      {s.status === "failed" && <p role="alert" className="rounded-xl border-2 border-danger px-4 py-3 text-sm text-danger">It stopped: {s.error}. Posts made so far are kept.</p>}
      {s.can_edit && (ready > 0 || unscheduled > 0) && (
        <div className="flex flex-wrap items-center gap-3">
          <BulkActions sourceId={s.id} ready={ready} approvedUnscheduled={unscheduled} />
          {attention > 0 && <Badge tone="warning">{attention} need attention</Badge>}
        </div>
      )}
      {(longform.length > 0 || (s.can_edit && s.status === "ready")) && (
        <section className="space-y-3"><h2 className="font-display text-xl font-bold">Blog article &amp; newsletter</h2>
          <LongformPanel sourceId={s.id} items={longform} canEdit={s.can_edit} sourceReady={s.status === "ready"} /></section>
      )}
      {s.moments.filter((m) => !m.dropped).map((m) => (
        <section key={m.id} aria-labelledby={`m-${m.id}`} className="space-y-3">
          <Card className="p-4">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-hand text-xl text-muted">#{m.rank}</span>
              <h2 id={`m-${m.id}`} className="font-semibold">{m.hook}</h2>
              {m.topic && <Badge>{m.topic}</Badge>}
              <span className="ml-auto text-xs text-muted">{clock(m.start_s)}–{clock(m.end_s)}</span>
            </div>
            <blockquote className="mt-2 border-l-4 border-lime pl-3 text-sm text-ink-soft">“{m.quote}”{m.speaker ? <span className="text-muted"> — {m.speaker}</span> : null}</blockquote>
            {s.can_edit && <div className="mt-2 flex flex-wrap gap-4"><DropMoment id={m.id} />{s.ai_images && <NewBackground id={m.id} />}</div>}
          </Card>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(() => { const c = s.clips[m.id]; return c ? <ClipCard momentId={m.id} clip={c} hook={m.hook} /> : null; })()}
            {s.posts.filter((p) => p.moment_id === m.id && p.review !== "dropped").map((p) => <PostCard key={p.id} p={p} canEdit={s.can_edit} />)}
          </div>
        </section>
      ))}
    </div>
  );
}
