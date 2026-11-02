"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { createQuote, importProducts, quoteOutcome, sendQuote } from "@/app/(app)/actions";

/** Catalogue & quotes (ROADMAP-V3 A3). */
export type Product = { code: string; name: string; category: string | null; unit: string; price: number; gst_rate: number; stock: number | null; min_qty: number };

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

export function ImportProducts() {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  return (<div className="space-y-1">
    <input type="file" accept=".csv,.xlsx" disabled={pending} className="text-sm" onChange={(e) => {
      const file = e.target.files?.[0]; if (!file) return;
      const fd = new FormData(); fd.append("file", file);
      go(() => importProducts(fd), (d) => { const r = d as { imported: number; skipped_rows: number[] }; setMsg(`${r.imported} products loaded${r.skipped_rows.length ? `, rows skipped: ${r.skipped_rows.join(", ")}` : ""}`); });
      e.target.value = "";
    }} />{msg && <p className="text-sm">{msg}</p>}<Err e={err} /></div>);
}

export function NewQuote({ products }: { products: Product[] }) {
  const { err, pending, go } = useGo();
  const [c, setC] = useState({ customer: "", phone: "", email: "", note: "" });
  const [lines, setLines] = useState<{ code: string; qty: string }[]>([{ code: products[0]?.code ?? "", qty: "1" }]);
  const byCode = Object.fromEntries(products.map((p) => [p.code, p]));
  const sub = lines.reduce((s, l) => s + (byCode[l.code]?.price ?? 0) * Number(l.qty || 0), 0);
  const submit = (send: boolean) => go(() => createQuote({ ...c, phone: c.phone || null, email: c.email || null, note: c.note || null, send,
    items: lines.filter((l) => l.code && Number(l.qty) > 0).map((l) => ({ code: l.code, qty: Number(l.qty) })) }),
    () => { setC({ customer: "", phone: "", email: "", note: "" }); setLines([{ code: products[0]?.code ?? "", qty: "1" }]); });
  if (!products.length) return <p className="text-sm text-muted">Load your catalogue first.</p>;
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="space-y-1"><Label htmlFor="qc">Customer</Label><Input id="qc" value={c.customer} onChange={(e) => setC({ ...c, customer: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="qp">WhatsApp / phone</Label><Input id="qp" value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="qe">Email</Label><Input id="qe" type="email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} /></div>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="flex gap-2">
          <Select aria-label="Product" value={l.code} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))}>
            {products.map((p) => <option key={p.code} value={p.code}>{p.name} · ₹{p.price.toLocaleString("en-IN")}/{p.unit}</option>)}</Select>
          <Input aria-label="Quantity" className="w-24" inputMode="decimal" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} />
          {lines.length > 1 && <button type="button" className="text-sm text-muted underline" onClick={() => setLines(lines.filter((_, j) => j !== i))}>remove</button>}
        </div>))}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="text-sm underline" onClick={() => setLines([...lines, { code: products[0]!.code, qty: "1" }])}>+ add a product</button>
        <span className="text-sm text-muted">about ₹{Math.round(sub).toLocaleString("en-IN")} before GST</span>
      </div>
      <Input aria-label="Note" placeholder="Note on the quote (optional)" value={c.note} onChange={(e) => setC({ ...c, note: e.target.value })} />
      <div className="flex gap-2">
        <Button disabled={pending || c.customer.length < 2} onClick={() => submit(true)}>{pending ? "Working…" : "Create and send"}</Button>
        <Button variant="secondary" disabled={pending || c.customer.length < 2} onClick={() => submit(false)}>Save as draft</Button>
      </div>
      <Err e={err} />
    </div>
  );
}

export function QuoteActions({ id, status, canAct }: { id: string; status: string; canAct: boolean }) {
  const { err, pending, go } = useGo();
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <a href={`/api/quote-pdf/${id}`} target="_blank" rel="noreferrer" className="underline">PDF</a>
      {canAct && status === "draft" && <button type="button" disabled={pending} className="underline" onClick={() => go(() => sendQuote(id))}>send</button>}
      {canAct && ["sent", "draft", "expired"].includes(status) && <>
        <button type="button" disabled={pending} className="underline" onClick={() => go(() => quoteOutcome(id, "won"))}>won</button>
        <button type="button" disabled={pending} className="text-muted underline" onClick={() => go(() => quoteOutcome(id, "lost"))}>lost</button></>}
      <Err e={err} />
    </span>
  );
}
