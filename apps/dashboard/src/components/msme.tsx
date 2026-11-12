"use client";

import { Badge, Button, Input, Label, Select } from "@agentry/ui";
import { Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { msmeCustomer, msmeSettings } from "@/app/(app)/actions";

/** MSME 45-day recovery (backend automations/invoice_follow_up/msme.py) on the Invoices page. */
export type MsmeInv = { id: string; number: string; issued_on: string | null; legal_due: string; days_late: number; outstanding: string; interest: string };
export type MsmeCustomer = { contact_id: string | null; customer: string; credit_days: number; written: boolean; business_buyer: boolean; invoices: MsmeInv[]; outstanding: string; late: string; interest: string };
export type Msme = { settings: { enabled: boolean; udyam: string | null; category: string | null; activity: string | null }; rate: number; bank_rate: number; late: string; interest: string; customers: MsmeCustomer[] };

const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const day = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string }>) => { setErr(null); start(async () => { const r = await f(); if (!r.ok) setErr(r.error ?? "failed"); router.refresh(); }); };
  return { err, pending, go };
}

export function MsmePanel({ d, canAct }: { d: Msme; canAct: boolean }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ enabled: d.settings.enabled, udyam: d.settings.udyam ?? "", category: d.settings.category ?? "micro", activity: d.settings.activity ?? "services" });
  const late = d.customers.filter((c) => Number(c.late) > 0);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Registered as a micro or small enterprise? Under the MSMED Act, buyers must pay within the days agreed in writing (at most 45), or 15 without
        an agreement, and owe interest at three times the RBI bank rate after that ({(d.rate * 100).toFixed(2)}% a year now, compounded monthly; bank rate {(d.bank_rate * 100).toFixed(2)}%).</p>
      {canAct && <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); go(() => msmeSettings({ ...f, udyam: f.udyam || null })); }}>
        <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" className="h-4 w-4" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} />Use it</label>
        <div className="space-y-1"><Label htmlFor="ms-u">Udyam number</Label><Input id="ms-u" value={f.udyam} onChange={(e) => setF({ ...f, udyam: e.target.value.toUpperCase() })} placeholder="UDYAM-MH-26-0012345" /></div>
        <div className="space-y-1"><Label htmlFor="ms-c">Category</Label><Select id="ms-c" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
          <option value="micro">Micro</option><option value="small">Small</option><option value="medium">Medium (not covered)</option></Select></div>
        <div className="space-y-1"><Label htmlFor="ms-a">What you do</Label><Select id="ms-a" value={f.activity} onChange={(e) => setF({ ...f, activity: e.target.value })}>
          <option value="manufacturing">Manufacturing</option><option value="services">Services</option><option value="trading">Trading (not covered)</option></Select></div>
        <Button type="submit" disabled={pending}>{pending ? "Saving…" : "Save"}</Button>
        {err && <span role="alert" className="text-sm text-danger">{err}</span>}
      </form>}
      {d.settings.enabled && <>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border-2 border-line p-3"><p className="text-xs font-semibold uppercase tracking-wide text-muted">Past the legal due date</p><p className="font-display text-2xl font-bold">{inr(d.late)}</p></div>
          <div className="rounded-xl border-2 border-line p-3"><p className="text-xs font-semibold uppercase tracking-wide text-muted">Interest they owe you so far</p><p className="font-display text-2xl font-bold">{inr(d.interest)}</p></div>
        </div>
        {late.length === 0 ? <p className="text-sm text-muted">Nobody is past the legal due date.</p> : (
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-muted"><tr><th className="py-2 pr-3 font-medium">Customer</th>
            <th className="py-2 pr-3 font-medium">Credit agreed</th><th className="py-2 pr-3 font-medium">Business buyer</th><th className="py-2 pr-3 text-right font-medium">Late</th><th className="py-2 pr-3 text-right font-medium">Interest</th><th /></tr></thead>
            <tbody className="divide-y divide-line">{late.map((c) => (
              <tr key={c.contact_id ?? c.customer}><td className="py-2 pr-3"><span className="font-medium">{c.customer}</span>
                <div className="text-xs text-muted">{c.invoices.filter((i) => i.days_late).map((i) => `${i.number}: due ${day(i.legal_due)}, ${i.days_late} days late`).join(" · ")}</div></td>
                <td className="py-2 pr-3">{c.contact_id && canAct ? <CreditDays cid={c.contact_id} days={c.written ? c.credit_days : null} /> : c.written ? `${c.credit_days} days` : "none (15 days)"}</td>
                <td className="py-2 pr-3">{c.contact_id && canAct ? <BuyerBox cid={c.contact_id} on={c.business_buyer} /> : c.business_buyer ? "yes" : "no"}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{inr(c.late)}</td><td className="py-2 pr-3 text-right tabular-nums">{inr(c.interest)}</td>
                <td className="py-2">{c.contact_id && <a href={`/api/msme-claim/${c.contact_id}`} className="inline-flex items-center gap-1 text-sm font-semibold underline"><Download aria-hidden="true" className="h-4 w-4" />Samadhaan draft</a>}</td></tr>))}</tbody></table></div>)}
        <p className="text-xs text-muted">Reminders past the legal due date now include a short, factual note about the Act and the interest. <Badge>MSME</Badge> cards appear in Needs you the day an invoice crosses it. Business buyers are also told the expense is deductible only in the
          year it&apos;s paid (Income-tax Act, 2025 section 37(2)(g); 1961 Act section 43B(h) for earlier invoices).</p>
      </>}
    </div>
  );
}

function CreditDays({ cid, days }: { cid: string; days: number | null }) {
  const { pending, go } = useGo();
  const [v, setV] = useState(days ? String(days) : "");
  return (
    <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); go(() => msmeCustomer(cid, { credit_days: v ? Number(v) : null })); }}>
      <Input aria-label="Credit days agreed in writing" className="h-8 w-16" inputMode="numeric" value={v} onChange={(e) => setV(e.target.value.replace(/\D/g, ""))} placeholder="none" />
      <Button size="sm" variant="secondary" type="submit" disabled={pending}>Set</Button>
    </form>
  );
}

function BuyerBox({ cid, on }: { cid: string; on: boolean }) {
  const { pending, go } = useGo();
  return <input type="checkbox" aria-label="Business buyer (gets the income-tax note)" className="h-4 w-4" checked={on} disabled={pending}
    onChange={(e) => go(() => msmeCustomer(cid, { business_buyer: e.target.checked }))} />;
}
