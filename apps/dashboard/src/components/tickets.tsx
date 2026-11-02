"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { editTicket, importOrders, newTicket } from "@/app/(app)/actions";

/** Support desk (ROADMAP-V3 A2). */
const CATS = ["order", "delivery", "refund", "product", "complaint", "billing", "technical", "other"];
const PRI = ["low", "normal", "high", "urgent"];
const STATUSES: [string, string][] = [["open", "Open"], ["waiting_customer", "Waiting for customer"], ["resolved", "Resolved"], ["closed", "Closed"]];

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

export function TicketControls({ t, team }: { t: { id: string; status: string; priority: string; category: string; assignee: string | null }; team: { id: string; name: string }[] }) {
  const { err, pending, go } = useGo();
  const [note, setNote] = useState("");
  const set = (body: Record<string, unknown>) => go(() => editTicket(t.id, body));
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <div className="space-y-1"><Label htmlFor="ts">Status</Label><Select id="ts" value={t.status} disabled={pending} onChange={(e) => set({ status: e.target.value })}>
          {STATUSES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
        <div className="space-y-1"><Label htmlFor="tp">Priority</Label><Select id="tp" value={t.priority} disabled={pending} onChange={(e) => set({ priority: e.target.value })}>
          {PRI.map((p) => <option key={p}>{p}</option>)}</Select></div>
        <div className="space-y-1"><Label htmlFor="tc">Category</Label><Select id="tc" value={t.category} disabled={pending} onChange={(e) => set({ category: e.target.value })}>
          {CATS.map((c) => <option key={c}>{c}</option>)}</Select></div>
        <div className="space-y-1"><Label htmlFor="ta">Owner</Label><Select id="ta" value={t.assignee ?? ""} disabled={pending} onChange={(e) => set({ assignee: e.target.value || null })}>
          <option value="">Nobody</option>{team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></div>
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) go(() => editTicket(t.id, { note }), () => setNote("")); }}>
        <Input aria-label="Internal note" placeholder="Internal note (the customer doesn't see it)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button variant="secondary" disabled={pending}>Add note</Button></form>
      <Err e={err} />
    </div>
  );
}

export function NewTicket() {
  const { err, pending, go, router } = useGo();
  const [f, setF] = useState({ subject: "", summary: "", category: "other", priority: "normal", order_ref: "" });
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); go(() => newTicket({ ...f, order_ref: f.order_ref || null }), (d) => router.push(`/tickets/${(d as { id: string }).id}`)); }}>
      <Input aria-label="Subject" required minLength={3} placeholder="What's the issue?" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} />
      <textarea aria-label="Details" rows={2} placeholder="Details" value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm" />
      <div className="flex flex-wrap gap-2">
        <Select aria-label="Category" className="w-auto" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{CATS.map((c) => <option key={c}>{c}</option>)}</Select>
        <Select aria-label="Priority" className="w-auto" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{PRI.map((p) => <option key={p}>{p}</option>)}</Select>
        <Input aria-label="Order number" className="w-36" placeholder="Order no." value={f.order_ref} onChange={(e) => setF({ ...f, order_ref: e.target.value })} />
        <Button type="submit" disabled={pending}>Open ticket</Button>
      </div>
      <Err e={err} />
    </form>
  );
}

export function ImportOrders() {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="space-y-1">
      <input type="file" accept=".csv,.xlsx" disabled={pending} className="text-sm" onChange={(e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const fd = new FormData(); fd.append("file", file);
        go(() => importOrders(fd), (d) => setMsg(`${(d as { imported: number }).imported} orders loaded`));
        e.target.value = "";
      }} />
      {msg && <p className="text-sm">{msg}</p>}<Err e={err} />
    </div>
  );
}
