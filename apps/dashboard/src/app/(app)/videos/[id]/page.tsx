import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AutoRefresh, PlanEditor, Replan, type Video } from "@/components/videos";
import { VIDEO_STATUS, WORKING } from "@/lib/videos";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "AI video" };

export default async function VideoPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("videos");
  const { id } = await params;
  let v: Video;
  try {
    v = await api<Video>(`/org/videos/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const { can_edit } = await api<{ can_edit: boolean }>("/org/videos", { orgId: active.id });
  const [label, tone] = VIDEO_STATUS[v.status] ?? [v.status, "neutral"];
  const problems = v.checks?.at(-1)?.problems ?? [];
  return (
    <div className="space-y-5">
      <AutoRefresh active={WORKING.includes(v.status)} />
      <Link href="/videos" className="text-sm text-muted hover:text-ink">← AI videos</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="font-display text-3xl font-bold tracking-tight">{v.plan.title || v.topic || "Planning…"}</h1>
          <p className="text-sm text-muted">{v.topic}{v.seconds ? ` · ${Math.round(Number(v.seconds))} s` : ""}{v.model ? ` · ${v.model === "test" ? "test mode" : v.model}` : ""}
            {Number(v.cost_usd) ? ` · about $${Number(v.cost_usd).toFixed(2)}` : ""}</p></div>
        <span className="flex items-center gap-3">{v.publish?.url && <a href={v.publish.url} target="_blank" rel="noreferrer" className="font-semibold underline">Open on YouTube ↗</a>}
          <Badge tone={tone}>{label}</Badge></span>
      </header>
      {v.error && <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border-2 border-warning px-4 py-3 text-sm"><p>{v.error}</p>
        {can_edit && ["needs_attention", "failed", "skipped"].includes(v.status) && <Replan id={v.id} />}</div>}
      {problems.length > 0 && v.status === "needs_attention" && <Card><CardBody className="text-sm"><p className="font-semibold">Why it stopped before generating</p>
        <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul><p className="mt-2 text-muted">Fix the plan below and generate it, or reject it. Nothing has been spent.</p></CardBody></Card>}
      {WORKING.includes(v.status) && <Card><CardBody className="text-sm">
        {v.status === "generating" ? `Veo is making ${v.ops.length || v.plan.scenes?.length || ""} scene(s): ${v.ops.filter((o) => o.status === "done").length} done. This takes 1-5 minutes; the page updates itself.`
          : v.status === "planning" ? "Planning the video and checking it…" : v.status === "composing" ? "Joining the scenes and adding your hook, captions and end card…" : "Uploading to YouTube…"}</CardBody></Card>}
      <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
        <div>{v.has_file ? <video src={`/api/ai-video/${v.id}`} controls playsInline className="aspect-[9/16] w-full rounded-2xl border-2 border-ink bg-ink" />
          : <div className="flex aspect-[9/16] w-full items-center justify-center rounded-2xl border-2 border-dashed border-line text-sm text-muted">No video yet</div>}
          {v.has_file && <a href={`/api/ai-video/${v.id}`} download className="mt-2 inline-block text-sm underline">Download MP4</a>}</div>
        <Card><CardHeader><CardTitle>Plan</CardTitle></CardHeader><CardBody>
          {v.plan.title ? <PlanEditor v={v} canEdit={can_edit} /> : <p className="text-sm text-muted">Not planned yet.</p>}</CardBody></Card>
      </div>
    </div>
  );
}
