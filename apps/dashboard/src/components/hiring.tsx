"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { candidateStage, createJob, jobStatus, uploadCvs } from "@/app/(app)/actions";

/** Hiring assistant (ROADMAP-V3 A5). */
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

export function NewJob() {
  const { err, pending, go, router } = useGo();
  const [f, setF] = useState({ title: "", description: "", must: "", location: "", kind: "full_time" });
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); go(() => createJob({ title: f.title, description: f.description, location: f.location || null, kind: f.kind,
      must_have: f.must.split("\n").map((x) => x.trim()).filter(Boolean) }), (d) => router.push(`/hiring/${(d as { id: string }).id}`)); }}>
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="space-y-1 sm:col-span-2"><Label htmlFor="jt">Role</Label><Input id="jt" required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="AC service technician" /></div>
        <div className="space-y-1"><Label htmlFor="jl">Where</Label><Input id="jl" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></div>
      </div>
      <Label htmlFor="jd">What the work is</Label>
      <textarea id="jd" required minLength={20} rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm" />
      <Label htmlFor="jm">Must-haves (one per line)</Label>
      <textarea id="jm" rows={3} value={f.must} onChange={(e) => setF({ ...f, must: e.target.value })} placeholder={"2 years AC servicing\nTwo-wheeler licence"} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm" />
      <div className="flex gap-2"><Select aria-label="Type" className="w-auto" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
        {[["full_time", "Full time"], ["part_time", "Part time"], ["internship", "Internship"], ["contract", "Contract"]].map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <Button type="submit" disabled={pending}>{pending ? "Creating…" : "Create the job"}</Button></div>
      <Err e={err} />
    </form>
  );
}

export function JobControls({ id, status }: { id: string; status: string }) {
  const { err, pending, go } = useGo();
  return <span className="flex items-center gap-2"><Select aria-label="Job status" className="h-9 w-auto text-sm" value={status} disabled={pending}
    onChange={(e) => go(() => jobStatus(id, e.target.value))}><option value="open">Open</option><option value="paused">Paused</option><option value="closed">Closed</option></Select><Err e={err} /></span>;
}

export function UploadCvs({ jobId }: { jobId: string }) {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  return (<div className="space-y-1">
    <input type="file" multiple accept=".pdf,.docx,.txt" disabled={pending} className="text-sm" onChange={(e) => {
      const files = Array.from(e.target.files ?? []); if (!files.length) return;
      const fd = new FormData(); files.forEach((f) => fd.append("files", f));
      go(() => uploadCvs(jobId, fd), (d) => { const r = d as { added: unknown[]; errors: string[] }; setMsg(`${r.added.length} read and scored${r.errors.length ? `; ${r.errors.join("; ")}` : ""}`); });
      e.target.value = "";
    }} />{pending && <p className="text-sm text-muted">Reading the CVs…</p>}{msg && <p className="text-sm">{msg}</p>}<Err e={err} /></div>);
}

export function StagePicker({ id, jobId, status }: { id: string; jobId: string; status: string }) {
  const { err, pending, go } = useGo();
  const [when, setWhen] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const set = (s: string) => go(() => candidateStage(id, { status: s, interview_at: s === "interview" && when ? new Date(when).toISOString() : null }, jobId),
    (d) => setMsg((d as { message: string | null }).message === "sent" ? "Message sent to the candidate." : null));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label htmlFor="iw">Interview time</Label><Input id="iw" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></div>
        <Button disabled={pending || !when} onClick={() => set("interview")}>Invite to interview</Button>
      </div>
      <div className="flex flex-wrap gap-2 text-sm">{["shortlisted", "offered", "hired", "rejected"].filter((s) => s !== status).map((s) => (
        <Button key={s} size="sm" variant={s === "rejected" ? "ghost" : "secondary"} disabled={pending}
          onClick={() => (s !== "rejected" || confirm("Reject? A polite regret is sent if that's on in settings.")) && set(s)}>{s}</Button>))}</div>
      {msg && <p className="text-sm">{msg}</p>}<Err e={err} />
    </div>
  );
}
