"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addTechnician, editJob, jobPhoto, newJob } from "@/app/(app)/actions";

/** Ops dispatcher (ROADMAP-V3 C2). */
export type Job = { id: string; number: number; customer: string; phone: string | null; address: string | null; area: string | null; service: string;
  description: string | null; day: string; slot: string; status: string; technician_id: string | null; technician: string | null; technician_phone: string | null;
  amount: number | null; photos: string[]; invoice_id: string | null; tech_message: string };
export type Tech = { id: string; name: string; skills: string[]; areas: string[]; today: number; max_per_day: number; active: boolean };

function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => { const r = await f(); if (!r.ok) return setErr(r.error ?? "failed"); after?.(r.data); router.refresh(); });
  };
  return { err, pending, go };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);
const NEXT: Record<string, [string, string][]> = {
  new: [], assigned: [["on_the_way", "On the way"]], on_the_way: [["in_progress", "Started"], ["done", "Done"]], in_progress: [["done", "Done"]] };

export function JobRow({ j, techs }: { j: Job; techs: Tech[] }) {
  const { err, pending, go } = useGo();
  const [amount, setAmount] = useState(j.amount ? String(j.amount) : "");
  const wa = j.technician_phone ? `https://wa.me/${j.technician_phone.replace(/\D/g, "")}?text=${encodeURIComponent(j.tech_message)}` : null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Technician" className="h-8 w-auto text-sm" value={j.technician_id ?? ""} disabled={pending || j.status === "done"}
          onChange={(e) => e.target.value && go(() => editJob(j.id, { technician_id: e.target.value }))}>
          <option value="">Choose a technician</option>{techs.filter((t) => t.active).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.today}/{t.max_per_day})</option>)}</Select>
        {wa && j.status !== "done" && <a href={wa} target="_blank" rel="noreferrer" className="text-sm underline">Send to {j.technician} on WhatsApp</a>}
        {(NEXT[j.status] ?? []).filter(([s]) => s !== "done").map(([s, l]) => <Button key={s} size="sm" variant="secondary" disabled={pending} onClick={() => go(() => editJob(j.id, { status: s }))}>{l}</Button>)}
        {(NEXT[j.status] ?? []).some(([s]) => s === "done") && <>
          <Input aria-label="Amount" className="h-8 w-28" inputMode="decimal" placeholder="Amount ₹" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Button size="sm" disabled={pending} onClick={() => go(() => editJob(j.id, { status: "done", ...(amount ? { amount: Number(amount) } : {}) }))}>Done</Button></>}
        {!["done", "cancelled"].includes(j.status) && <button type="button" className="text-xs text-muted underline" disabled={pending}
          onClick={() => confirm(`Cancel job #${j.number}?`) && go(() => editJob(j.id, { status: "cancelled" }))}>cancel</button>}
        <label className="cursor-pointer text-xs underline">add photo<input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => {
          const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); go(() => jobPhoto(j.id, fd)); e.target.value = ""; }} /></label>
        {j.photos.length > 0 && <span className="text-xs text-muted">{j.photos.length} photo{j.photos.length > 1 ? "s" : ""}</span>}
      </div>
      <Err e={err} />
    </div>
  );
}

export function NewJob({ services }: { services: string[] }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ customer: "", phone: "", address: "", area: "", service: services[0] ?? "", description: "", day: "", slot: "any" });
  const [msg, setMsg] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); go(() => newJob({ ...f, phone: f.phone || null, address: f.address || null, area: f.area || null, description: f.description || null }),
      (d) => { const r = d as { number: number; technician: string | null }; setMsg(`Job #${r.number}: ${r.technician ? `assigned to ${r.technician}` : "no technician free: assign one"}`); }); }}>
      <div className="space-y-1"><Label htmlFor="jc">Customer</Label><Input id="jc" required value={f.customer} onChange={set("customer")} /></div>
      <div className="space-y-1"><Label htmlFor="jp">Phone</Label><Input id="jp" value={f.phone} onChange={set("phone")} /></div>
      <div className="space-y-1"><Label htmlFor="ja">Area</Label><Input id="ja" value={f.area} onChange={set("area")} /></div>
      <div className="space-y-1"><Label htmlFor="js">Service</Label><Select id="js" value={f.service} onChange={set("service")}>{services.map((s) => <option key={s}>{s}</option>)}</Select></div>
      <div className="space-y-1 sm:col-span-2"><Label htmlFor="jad">Address</Label><Input id="jad" value={f.address} onChange={set("address")} /></div>
      <div className="space-y-1"><Label htmlFor="jd">Day</Label><Input id="jd" required type="date" value={f.day} onChange={set("day")} /></div>
      <div className="space-y-1"><Label htmlFor="jsl">When</Label><Select id="jsl" value={f.slot} onChange={set("slot")}>{["any", "morning", "afternoon", "evening"].map((s) => <option key={s}>{s}</option>)}</Select></div>
      <div className="space-y-1 sm:col-span-3"><Label htmlFor="jde">Problem</Label><Input id="jde" value={f.description} onChange={set("description")} /></div>
      <div className="flex items-end"><Button type="submit" disabled={pending}>Add job</Button></div>
      <div className="sm:col-span-4">{msg && <p className="text-sm">{msg}</p>}<Err e={err} /></div>
    </form>
  );
}

export function AddTech() {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ name: "", phone: "", skills: "", areas: "", max: "5" });
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => addTechnician({ name: f.name, phone: f.phone || null, max_per_day: Number(f.max) || 5,
      skills: f.skills.split(",").map((x) => x.trim()).filter(Boolean), areas: f.areas.split(",").map((x) => x.trim()).filter(Boolean) }), () => setF({ name: "", phone: "", skills: "", areas: "", max: "5" })); }}>
      <Input aria-label="Name" required placeholder="Name" className="w-36" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      <Input aria-label="WhatsApp" placeholder="WhatsApp" className="w-40" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
      <Input aria-label="Skills" placeholder="Skills (comma separated)" className="w-56" value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} />
      <Input aria-label="Areas" placeholder="Areas (empty = everywhere)" className="w-56" value={f.areas} onChange={(e) => setF({ ...f, areas: e.target.value })} />
      <Input aria-label="Jobs a day" className="w-20" inputMode="numeric" value={f.max} onChange={(e) => setF({ ...f, max: e.target.value })} />
      <Button type="submit" disabled={pending}>Add technician</Button><Err e={err} />
    </form>
  );
}
