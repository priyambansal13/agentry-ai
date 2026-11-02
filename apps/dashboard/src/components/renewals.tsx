"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addRenewal, importRenewals, markRenewal } from "@/app/(app)/actions";

/** Renewals & repeat business (ROADMAP-V3 A4). */
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

export function ImportRenewals() {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  return (<div className="space-y-1">
    <input type="file" accept=".csv,.xlsx" disabled={pending} className="text-sm" onChange={(e) => {
      const file = e.target.files?.[0]; if (!file) return;
      const fd = new FormData(); fd.append("file", file);
      go(() => importRenewals(fd), (d) => { const r = d as { added: number; skipped_rows: number[] }; setMsg(`${r.added} added${r.skipped_rows.length ? `, rows skipped: ${r.skipped_rows.join(", ")}` : ""}`); });
      e.target.value = "";
    }} />{msg && <p className="text-sm">{msg}</p>}<Err e={err} /></div>);
}

export function AddRenewal() {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ customer: "", phone: "", email: "", item: "", due_on: "", amount: "", every: "yearly" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); go(() => addRenewal({ ...f, phone: f.phone || null, email: f.email || null,
      amount: f.amount ? Number(f.amount) : null }), () => setF({ ...f, customer: "", phone: "", email: "", amount: "" })); }}>
      <div className="space-y-1"><Label htmlFor="rc">Customer</Label><Input id="rc" required value={f.customer} onChange={set("customer")} /></div>
      <div className="space-y-1"><Label htmlFor="rp">WhatsApp</Label><Input id="rp" value={f.phone} onChange={set("phone")} /></div>
      <div className="space-y-1"><Label htmlFor="ri">What renews</Label><Input id="ri" required value={f.item} onChange={set("item")} placeholder="AC AMC" /></div>
      <div className="space-y-1"><Label htmlFor="rd">Due on</Label><Input id="rd" required type="date" value={f.due_on} onChange={set("due_on")} /></div>
      <div className="space-y-1"><Label htmlFor="ra">Amount (₹)</Label><Input id="ra" inputMode="decimal" value={f.amount} onChange={set("amount")} /></div>
      <div className="space-y-1"><Label htmlFor="rv">Every</Label><Select id="rv" value={f.every} onChange={set("every")}>
        {[["monthly", "month"], ["quarterly", "quarter"], ["half_yearly", "6 months"], ["yearly", "year"], ["once", "once"]].map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
      <div className="space-y-1"><Label htmlFor="re">Email</Label><Input id="re" type="email" value={f.email} onChange={set("email")} /></div>
      <div className="flex items-end"><Button type="submit" disabled={pending}>Add</Button></div>
      <div className="sm:col-span-4"><Err e={err} /></div>
    </form>
  );
}

export function MarkRenewal({ id }: { id: string }) {
  const { err, pending, go } = useGo();
  return <span className="flex items-center gap-2 text-sm">
    <button type="button" disabled={pending} className="underline" onClick={() => go(() => markRenewal(id, "renewed"))}>renewed</button>
    <button type="button" disabled={pending} className="text-muted underline" onClick={() => confirm("Stop reminding this customer?") && go(() => markRenewal(id, "cancelled"))}>cancel</button>
    <Err e={err} /></span>;
}
