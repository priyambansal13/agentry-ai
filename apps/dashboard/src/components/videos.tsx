"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { editVideo, generateVideo, makeVideo, publishVideo, rejectVideo, replanVideo } from "@/app/(app)/actions";

/** AI video studio (docs/flows/agents/ai-video-studio.md). */
export type Scene = { prompt: string; caption: string };
export type Plan = { topic?: string; title?: string; description?: string; hashtags?: string[]; hook?: string; scenes?: Scene[] };
export type Video = { id: string; status: string; trigger: string; slot: string | null; topic: string | null; plan: Plan; checks: { ok: boolean; problems: string[] }[];
  ops: { name: string; status: string; error?: string }[]; model: string | null; seconds: number | null; cost_usd: number | string; has_file: boolean;
  publish: { platform?: string; url?: string; privacy?: string; at?: string }; error: string | null; created_at: string };

function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => {
      const r = await f();
      if (!r.ok) return setErr(r.error ?? "failed");
      after?.(r.data);
      router.refresh();
    });
  };
  return { err, pending, go, router };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);

export function MakeVideo({ estimate, testMode }: { estimate: number; testMode: boolean }) {
  const { err, pending, go, router } = useGo();
  const [topic, setTopic] = useState("");
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => makeVideo(topic), (d) => router.push(`/videos/${(d as { id: string }).id}`)); }}>
      <div className="min-w-64 flex-1 space-y-1"><Label htmlFor="vt">Topic (optional)</Label>
        <Input id="vt" maxLength={200} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Leave empty: the studio picks from your topics and services" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Starting…" : "Make a video now"}</Button>
      <span className="pb-2 text-xs text-muted">{testMode ? "Test mode: free test clips" : `about $${estimate.toFixed(2)} with Veo`}</span>
      <Err e={err} />
    </form>
  );
}

/** Refresh the page every few seconds while a video is being made. */
export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), 5000);
    return () => clearInterval(t);
  }, [active, router]);
  return null;
}

export function Replan({ id }: { id: string }) {
  const { err, pending, go } = useGo();
  return <span className="flex items-center gap-2"><Button variant="secondary" disabled={pending} onClick={() => go(() => replanVideo(id))}>{pending ? "Starting…" : "Plan it again"}</Button><Err e={err} /></span>;
}

export function PlanEditor({ v, canEdit }: { v: Video; canEdit: boolean }) {
  const { err, pending, go } = useGo();
  const scenesEditable = v.status === "needs_attention";
  const [f, setF] = useState({ title: v.plan.title ?? "", description: v.plan.description ?? "", hook: v.plan.hook ?? "",
    hashtags: (v.plan.hashtags ?? []).filter((h) => h.toLowerCase() !== "#shorts").join(" ") });
  const [scenes, setScenes] = useState<Scene[]>(v.plan.scenes ?? []);
  const locked = !canEdit || ["published", "publishing", "rejected"].includes(v.status);
  const save = (then?: () => Promise<{ ok: boolean; error?: string }>) => go(async () => {
    const r = await editVideo(v.id, { ...f, hashtags: f.hashtags.split(/[\s,]+/).filter(Boolean), ...(scenesEditable ? { scenes } : {}) });
    return r.ok && then ? then() : r;
  });
  return (
    <div className="space-y-3">
      <div className="space-y-1"><Label htmlFor="pt">Title</Label><Input id="pt" maxLength={100} disabled={locked} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></div>
      <div className="space-y-1"><Label htmlFor="pd">Description</Label>
        <textarea id="pd" rows={4} disabled={locked} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })}
          className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm" /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="ph">Hook (banner, first 3 s)</Label><Input id="ph" maxLength={80} disabled={locked || !scenesEditable} value={f.hook} onChange={(e) => setF({ ...f, hook: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="pg">Hashtags (#Shorts is added)</Label><Input id="pg" disabled={locked} value={f.hashtags} onChange={(e) => setF({ ...f, hashtags: e.target.value })} /></div>
      </div>
      <div className="space-y-2">
        <p className="text-sm font-semibold">Scenes <span className="font-normal text-muted">(8 seconds each{scenesEditable ? "" : "; fixed once generated"})</span></p>
        {scenes.map((s, i) => (
          <div key={i} className="space-y-1 rounded-xl border-2 border-line p-3">
            <Label htmlFor={`sc${i}`} className="text-xs">Scene {i + 1}: what Veo makes</Label>
            <textarea id={`sc${i}`} rows={3} disabled={locked || !scenesEditable} value={s.prompt} onChange={(e) => setScenes(scenes.map((x, j) => (j === i ? { ...x, prompt: e.target.value } : x)))}
              className="w-full rounded-lg border-2 border-line bg-card px-2 py-1 text-sm" />
            <Input aria-label={`Scene ${i + 1} caption`} disabled={locked || !scenesEditable} maxLength={80} value={s.caption}
              onChange={(e) => setScenes(scenes.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)))} />
          </div>))}
      </div>
      {!locked && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={pending} onClick={() => save()}>Save</Button>
          {v.status === "needs_attention" && <Button disabled={pending} onClick={() => save(() => generateVideo(v.id))}>Save and generate</Button>}
          {v.status === "review" && <Button disabled={pending} onClick={() => save(() => publishVideo(v.id))}>Save and publish</Button>}
          {["needs_attention", "review", "failed"].includes(v.status) && <Button variant="ghost" disabled={pending}
            onClick={() => confirm("Reject this video? It won't be published.") && go(() => rejectVideo(v.id))}>Reject</Button>}
        </div>)}
      <Err e={err} />
    </div>
  );
}
