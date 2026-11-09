import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { AutoRefresh, MakeVideo, type Script, ScriptCard, type Video, WriteScript } from "@/components/videos";
import { VIDEO_STATUS, WORKING } from "@/lib/videos";
import { pageApi as api, requirePage } from "@/lib/session";

export const metadata = { title: "AI videos" };

type Data = { items: Video[]; status: string | null; test_mode: boolean; youtube: string | null; spent: number; budget: number; estimate: number;
  schedule: { days: string[]; time: string }; can_edit: boolean };
const DAY: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

export default async function VideosPage() {
  const active = await requirePage("videos");
  const [d, { items: scripts }] = await Promise.all([api<Data>("/org/videos", { orgId: active.id }), api<{ items: Script[] }>("/org/videos/scripts", { orgId: active.id })]);
  const working = d.items.some((v) => WORKING.includes(v.status));
  return (
    <div className="space-y-6">
      <AutoRefresh active={working} />
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">AI videos</h1>
          <p className="mt-1 max-w-3xl text-muted">Short vertical videos planned from your business, made with Veo, checked, branded with your hook, captions and end card,
            and posted to YouTube as Shorts. {d.status === "live" ? "Live: they publish by themselves." : "Approval mode: you approve each one before it's posted."}</p>
        </div>
        <div className="text-right text-sm">
          <p>{d.schedule.days.map((x) => DAY[x]).join(", ") || "No days set"} at {d.schedule.time}</p>
          <p className="text-muted">${d.spent.toFixed(2)} of ${d.budget.toFixed(0)} this month</p>
        </div>
      </header>
      {d.test_mode && <p className="rounded-2xl border-2 border-warning px-4 py-3 text-sm">Test mode: Veo isn&apos;t connected on this server, so each scene is a plain branded test clip (free). Everything else works as it will for real.</p>}
      {!d.youtube && <p className="rounded-2xl border-2 border-line px-4 py-3 text-sm">YouTube isn&apos;t connected: videos wait for you to approve them. <Link href="/settings/connections" className="underline">Connect YouTube</Link></p>}
      {d.can_edit && <Card><CardBody><MakeVideo estimate={d.estimate} testMode={d.test_mode} /></CardBody></Card>}
      <Card><CardHeader><CardTitle>Videos</CardTitle><span className="text-sm text-muted">{d.youtube ? `posting to ${d.youtube}` : ""}</span></CardHeader>
        <CardBody className="p-0">
          {d.items.length === 0 ? <p className="p-5 text-muted">No videos yet. Make one now, or wait for the next scheduled day.</p> : (
            <ul className="divide-y divide-line">{d.items.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0"><Link href={`/videos/${v.id}`} className="font-semibold hover:underline">{v.plan.title || v.topic || "Planning…"}</Link>
                  <p className="text-xs text-muted">{new Date(v.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} · {v.trigger === "schedule" ? "scheduled" : "made by hand"}
                    {v.seconds ? ` · ${Math.round(Number(v.seconds))} s` : ""}{Number(v.cost_usd) ? ` · $${Number(v.cost_usd).toFixed(2)}` : ""}</p>
                  {v.error && ["failed", "skipped", "needs_attention", "review"].includes(v.status) && <p className="text-xs text-warning">{v.error}</p>}</div>
                <span className="flex items-center gap-2">{v.publish?.url && <a href={v.publish.url} target="_blank" rel="noreferrer" className="text-sm underline">YouTube ↗</a>}
                  <Badge tone={VIDEO_STATUS[v.status]?.[1]}>{VIDEO_STATUS[v.status]?.[0] ?? v.status}</Badge></span>
              </li>))}</ul>)}
        </CardBody></Card>
      <Card><CardHeader><CardTitle>Scripts to film yourself</CardTitle><span className="text-sm text-muted">30-60 s, timed, in your voice</span></CardHeader>
        <CardBody className="space-y-3">{d.can_edit && <WriteScript />}{scripts.map((s) => <ScriptCard key={s.id} s={s} canEdit={d.can_edit} />)}</CardBody></Card>
    </div>
  );
}
