"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { checkVisibilityNow, saveVisibilitySetup, writeAnswerPage } from "@/app/(app)/actions";

/** AI visibility (PLAN-TRY-IT-AND-AI-VISIBILITY B). */
function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => { const r = await f(); if (!r.ok) return setErr(r.error ?? "failed"); after?.(r.data); router.refresh(); });
  };
  return { err, pending, go, router };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

type Cfg = { service: string | null; city: string | null; area: string | null; other_names: string[]; competitors: string[]; questions: string[]; monthly: boolean };

export function VisibilitySetup({ cfg, suggested }: { cfg: Cfg; suggested: string[] }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ service: cfg.service ?? "", city: cfg.city ?? "", area: cfg.area ?? "", other: cfg.other_names.join("\n"),
    competitors: cfg.competitors.join("\n"), questions: cfg.questions.join("\n"), monthly: cfg.monthly });
  const [saved, setSaved] = useState(false);
  const area = "w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm";
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault(); setSaved(false);
      go(() => saveVisibilitySetup({ service: f.service || null, city: f.city || null, area: f.area || null, other_names: lines(f.other),
        competitors: lines(f.competitors), questions: lines(f.questions), monthly: f.monthly }), () => setSaved(true));
    }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1"><Label htmlFor="vs">What you do, as a customer says it</Label><Input id="vs" value={f.service} onChange={(e) => setF({ ...f, service: e.target.value })} placeholder="dentist" /></div>
        <div className="space-y-1"><Label htmlFor="vc">City</Label><Input id="vc" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} placeholder="Bengaluru" /></div>
        <div className="space-y-1"><Label htmlFor="va">Area (optional)</Label><Input id="va" value={f.area} onChange={(e) => setF({ ...f, area: e.target.value })} placeholder="Indiranagar" /></div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="vk">Competitors, one per line: Name — website</Label>
          <textarea id="vk" rows={4} className={area} value={f.competitors} onChange={(e) => setF({ ...f, competitors: e.target.value })} placeholder={"Clove Dental — clovedental.in\nDr Rao's Dental"} /></div>
        <div className="space-y-1"><Label htmlFor="vo">Other names people use for you (one per line)</Label>
          <textarea id="vo" rows={4} className={area} value={f.other} onChange={(e) => setF({ ...f, other: e.target.value })} /></div>
      </div>
      <div className="space-y-1"><Label htmlFor="vq">Questions customers ask (one per line; leave empty to use the suggested ones)</Label>
        <textarea id="vq" rows={5} className={area} value={f.questions} onChange={(e) => setF({ ...f, questions: e.target.value })}
          placeholder={suggested.slice(0, 4).join("\n") || "What is the best dentist in Indiranagar?"} /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.monthly} onChange={(e) => setF({ ...f, monthly: e.target.checked })} /> Check on the 1st of every month</label>
      <div className="flex items-center gap-3"><Button type="submit" variant="secondary" disabled={pending}>{pending ? "Saving…" : "Save"}</Button>{saved && <span className="text-sm text-success">Saved</span>}</div>
      <Err e={err} />
    </form>
  );
}

export function CheckNow({ left, disabled }: { left: number; disabled?: string | null }) {
  const { err, pending, go } = useGo();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button disabled={pending || !!disabled || left === 0} onClick={() => go(() => checkVisibilityNow())}>{pending ? "Starting…" : "Check now"}</Button>
      <span className="text-sm text-muted">{disabled ?? `${left} extra check${left === 1 ? "" : "s"} left this month; the 1st of the month is included.`}</span>
      <Err e={err} />
    </div>
  );
}

/** While a check runs (a few minutes), refresh the page every 15 s. */
export function RefreshWhileRunning() {
  const router = useRouter();
  useEffect(() => { const t = setInterval(() => router.refresh(), 15000); return () => clearInterval(t); }, [router]);
  return null;
}

export function WritePage({ question }: { question: string }) {
  const { err, pending, go, router } = useGo();
  return (
    <span className="inline-flex items-center gap-2">
      <Button size="sm" variant="secondary" disabled={pending} onClick={() => go(() => writeAnswerPage(question), (d) => router.push(`/seo/${(d as { id: string }).id}`))}>
        {pending ? "Writing…" : "Write the page"}</Button><Err e={err} />
    </span>
  );
}

export function CopyCode({ code }: { code: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="mt-2">
      <pre className="max-h-56 overflow-auto rounded-xl border-2 border-line bg-paper p-3 text-xs">{code}</pre>
      <Button size="sm" variant="secondary" className="mt-2" onClick={async () => { await navigator.clipboard.writeText(code); setDone(true); }}>{done ? "Copied" : "Copy"}</Button>
    </div>
  );
}
