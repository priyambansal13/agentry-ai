"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { hqGenerateStatement, hqIssueStatement, hqResolveDispute, hqSavePlan } from "@/app/(app)/actions";
import { type Line, money } from "@/lib/billing";

export type PlanIn = {
  currency: string; setup_fee: number | string; retainer: number | string; tax_rate: number | string; pilot_until: string | null;
  included: Record<string, number>; overage: Record<string, number | string>;
  outcome_prices: { outcome: string; price?: number | string | null; pct_of_customer_value?: number | null; min?: number | string | null }[];
  revenue_share: { basis: string; rate: number; cap?: number | string | null; window_days: number; strong_only: boolean };
};

export const EMPTY: PlanIn = { currency: "INR", setup_fee: 0, retainer: 0, tax_rate: 0.18, pilot_until: null, included: {}, overage: {},
  outcome_prices: [], revenue_share: { basis: "none", rate: 0, cap: null, window_days: 30, strong_only: false } };

const num = (v: string) => (v === "" ? null : Number(v));

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  // the label wraps its input, so each field is named for screen readers (and getByLabel in browser checks)
  return <Label className="mb-0 space-y-1 font-normal"><span className="block text-sm font-medium">{label}</span>{children}{hint && <span className="block text-xs text-muted">{hint}</span>}</Label>;
}

export type PlanForm = {
  currency: string; setup_fee: string; retainer: string; tax_pct: string; pilot_until: string;
  inc_messages: string; ovr_messages: string; inc_emails: string; ovr_emails: string; inc_minutes: string; ovr_minutes: string; inc_videos: string; ovr_videos: string;
  booking_mode: string; booking_price: string; booking_pct: string; booking_min: string;
  rs_basis: string; rs_pct: string; rs_cap: string; rs_window: string; rs_strong: boolean;
};

export function formFromPlan(plan: PlanIn | null): PlanForm {
  const p0 = plan ?? EMPTY;
  const op = p0.outcome_prices[0];
  return {
    currency: p0.currency, setup_fee: String(p0.setup_fee), retainer: String(p0.retainer), tax_pct: String(Math.round(Number(p0.tax_rate) * 100)),
    pilot_until: p0.pilot_until ?? "",
    inc_messages: String(p0.included.messages ?? ""), ovr_messages: String(p0.overage.messages ?? ""),
    inc_emails: String(p0.included.emails_triaged ?? ""), ovr_emails: String(p0.overage.emails_triaged ?? ""),
    inc_minutes: String(p0.included.voice_minutes ?? ""), ovr_minutes: String(p0.overage.voice_minutes ?? ""),
    inc_videos: String(p0.included.content_videos ?? ""), ovr_videos: String(p0.overage.content_videos ?? ""),
    booking_mode: op ? (op.price != null ? "fixed" : "pct") : "none", booking_price: String(op?.price ?? ""),
    booking_pct: op?.pct_of_customer_value ? String(op.pct_of_customer_value * 100) : "", booking_min: String(op?.min ?? ""),
    rs_basis: p0.revenue_share.basis, rs_pct: String(+(p0.revenue_share.rate * 100).toFixed(2)), rs_cap: String(p0.revenue_share.cap ?? ""),
    rs_window: String(p0.revenue_share.window_days), rs_strong: p0.revenue_share.strong_only,
  };
}

export function planFromForm(f: PlanForm) {
  const included: Record<string, number> = {}, overage: Record<string, number> = {};
  if (f.inc_messages) included.messages = Number(f.inc_messages);
  if (f.ovr_messages) overage.messages = Number(f.ovr_messages);
  if (f.inc_emails) included.emails_triaged = Number(f.inc_emails);
  if (f.ovr_emails) overage.emails_triaged = Number(f.ovr_emails);
  if (f.inc_minutes) included.voice_minutes = Number(f.inc_minutes);
  if (f.ovr_minutes) overage.voice_minutes = Number(f.ovr_minutes);
  if (f.inc_videos) included.content_videos = Number(f.inc_videos);
  if (f.ovr_videos) overage.content_videos = Number(f.ovr_videos);
  const outcome_prices = f.booking_mode === "fixed" ? [{ outcome: "appointment_booked", price: num(f.booking_price) }]
    : f.booking_mode === "pct" ? [{ outcome: "appointment_booked", pct_of_customer_value: Number(f.booking_pct) / 100, min: num(f.booking_min) }] : [];
  return { currency: f.currency, setup_fee: Number(f.setup_fee || 0), retainer: Number(f.retainer || 0), tax_rate: Number(f.tax_pct || 0) / 100,
    pilot_until: f.pilot_until || null, included, overage, outcome_prices,
    revenue_share: { basis: f.rs_basis, rate: f.rs_basis === "none" ? 0 : Number(f.rs_pct || 0) / 100, cap: num(f.rs_cap),
                     window_days: Number(f.rs_window || 30), strong_only: f.rs_strong } };
}

/** The plan's fields. `show` limits the sections to what the client's automations can earn from. */
export function PlanFields({ f, setF, show = { usage: true, bookings: true, recovery: true }, lockCurrency = false }:
  { f: PlanForm; setF: (f: PlanForm) => void; show?: { usage: boolean; bookings: boolean; recovery: boolean }; lockCurrency?: boolean }) {
  const set = (k: keyof PlanForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });
  return (
    <div className="space-y-6">
      <fieldset className="grid gap-4 sm:grid-cols-3">
        <legend className="mb-2 text-sm font-semibold">Fixed fees</legend>
        <Field label="Currency">{lockCurrency ? <Input value={f.currency} disabled readOnly />
          : <Select value={f.currency} onChange={set("currency")}>{["INR", "USD", "EUR", "GBP", "AED"].map((c) => <option key={c}>{c}</option>)}</Select>}</Field>
        <Field label="Setup fee (one time)"><Input type="number" min={0} step="any" value={f.setup_fee} onChange={set("setup_fee")} /></Field>
        <Field label="Monthly retainer"><Input type="number" min={0} step="any" value={f.retainer} onChange={set("retainer")} /></Field>
        <Field label="Tax %" hint="18 for GST in India"><Input type="number" min={0} max={30} step="any" value={f.tax_pct} onChange={set("tax_pct")} /></Field>
        <Field label="Pilot until" hint="No retainer is charged before this date"><Input type="date" value={f.pilot_until} onChange={set("pilot_until")} /></Field>
      </fieldset>
      {show.usage && (
        <fieldset className="grid gap-4 sm:grid-cols-4">
          <legend className="mb-2 text-sm font-semibold">Usage (included, then per unit)</legend>
          <Field label="Messages included"><Input type="number" min={0} value={f.inc_messages} onChange={set("inc_messages")} /></Field>
          <Field label="Per extra message"><Input type="number" min={0} step="any" value={f.ovr_messages} onChange={set("ovr_messages")} /></Field>
          <Field label="Emails triaged included"><Input type="number" min={0} value={f.inc_emails} onChange={set("inc_emails")} /></Field>
          <Field label="Per extra email"><Input type="number" min={0} step="any" value={f.ovr_emails} onChange={set("ovr_emails")} /></Field>
          <Field label="Call minutes included"><Input type="number" min={0} value={f.inc_minutes} onChange={set("inc_minutes")} /></Field>
          <Field label="Per extra call minute"><Input type="number" min={0} step="any" value={f.ovr_minutes} onChange={set("ovr_minutes")} /></Field>
          <Field label="Videos included (content)" hint="Recordings turned into posts per month"><Input type="number" min={0} value={f.inc_videos} onChange={set("inc_videos")} /></Field>
          <Field label="Per extra video"><Input type="number" min={0} step="any" value={f.ovr_videos} onChange={set("ovr_videos")} /></Field>
        </fieldset>
      )}
      {show.bookings && (
        <fieldset className="grid gap-4 sm:grid-cols-4">
          <legend className="mb-2 text-sm font-semibold">Pay per booked appointment</legend>
          <Field label="Charge"><Select value={f.booking_mode} onChange={set("booking_mode")}>
            <option value="none">Not charged</option><option value="fixed">Fixed price</option><option value="pct">% of customer value</option></Select></Field>
          {f.booking_mode === "fixed" && <Field label="Price per booking"><Input type="number" min={0} step="any" required value={f.booking_price} onChange={set("booking_price")} /></Field>}
          {f.booking_mode === "pct" && <>
            <Field label="% of value" hint="Usually 10–20"><Input type="number" min={0.1} max={100} step="any" required value={f.booking_pct} onChange={set("booking_pct")} /></Field>
            <Field label="Minimum per booking"><Input type="number" min={0} step="any" value={f.booking_min} onChange={set("booking_min")} /></Field>
          </>}
        </fieldset>
      )}
      {show.recovery && (
        <fieldset className="grid gap-4 sm:grid-cols-4">
          <legend className="mb-2 text-sm font-semibold">Share of money recovered (invoice follow-up)</legend>
          <Field label="Basis"><Select value={f.rs_basis} onChange={set("rs_basis")}>
            <option value="none">None</option><option value="overdue_only">Overdue invoices only</option><option value="all_recovered">Everything paid after a reminder</option></Select></Field>
          {f.rs_basis !== "none" && <>
            <Field label="Share %"><Input type="number" min={0} max={50} step="any" value={f.rs_pct} onChange={set("rs_pct")} /></Field>
            <Field label="Monthly cap" hint="Blank = no cap"><Input type="number" min={0} step="any" value={f.rs_cap} onChange={set("rs_cap")} /></Field>
            <Field label="Window (days after reminder)"><Input type="number" min={1} max={120} value={f.rs_window} onChange={set("rs_window")} /></Field>
            <label className="flex items-center gap-2 text-sm sm:col-span-4"><input type="checkbox" checked={f.rs_strong} onChange={set("rs_strong")} className="h-4 w-4 accent-[var(--ink)]" />
              Only count payments that name the invoice (strong matches)</label>
          </>}
        </fieldset>
      )}
    </div>
  );
}

/** Which parts of a plan can earn money, given the client's automations. */
export function planSections(automations: string[]) {
  const has = (...k: string[]) => k.some((x) => automations.includes(x));
  return { usage: has("inbox_triage", "invoice_follow_up", "lead_reactivation", "speed_to_lead", "whatsapp_assistant"),
           bookings: has("website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"),
           recovery: has("invoice_follow_up") };
}

export function PlanEditor({ orgId, plan, automations }: { orgId: string; plan: PlanIn | null; automations: string[] }) {
  const router = useRouter();
  const [f, setF] = useState<PlanForm>(formFromPlan(plan));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await hqSavePlan(orgId, planFromForm(f));
      setMsg(r.ok ? { ok: true, text: "Plan saved. It applies to the next statement generated." } : { ok: false, text: r.error });
      if (r.ok) router.refresh();
    }); }}>
      <PlanFields f={f} setF={setF} show={planSections(automations)} />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending}>{plan ? "Save plan" : "Create plan"}</Button>
        {msg && <span role="status" className={msg.ok ? "text-sm text-success" : "text-sm text-danger"}>{msg.text}</span>}
      </div>
    </form>
  );
}

export function GenerateStatement({ orgId, defaultMonth }: { orgId: string; defaultMonth: string }) {
  const router = useRouter();
  const [month, setMonth] = useState(defaultMonth);
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await hqGenerateStatement(orgId, month);
      if (!r.ok) return setErr(r.error);
      router.push(`/hq/${orgId}/statements/${r.data.statement_id}`);
    }); }}>
      <div className="space-y-1"><Label htmlFor="month">Month</Label><Input id="month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} required /></div>
      <Button type="submit" variant="secondary" disabled={pending}>Generate draft</Button>
      {err && <p className="w-full text-xs text-danger">{err}</p>}
    </form>
  );
}

export function StatementActions({ orgId, sid, status, total, currency, disputes, evidence = {} }:
  { orgId: string; sid: string; status: string; total: number; currency: string; disputes: Line[];
    evidence?: Record<string, { id: string; kind: string; value: number; evidence: Record<string, unknown> }> }) {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const [partialFor, setPartialFor] = useState<string | null>(null);
  const [credit, setCredit] = useState("");
  const [note, setNote] = useState("");
  const [excluded, setExcluded] = useState<string[]>([]);
  const act = (fn: () => Promise<{ ok: boolean; error?: string }>) => start(async () => {
    const r = await fn();
    if (!r.ok) setErr(r.error ?? "Failed"); else { setErr(null); setPartialFor(null); router.refresh(); }
  });
  const label = (o: { kind: string; value: number; evidence: Record<string, unknown> }) =>
    o.kind === "amount_recovered" ? `Invoice ${String(o.evidence.invoice)} · ${money(o.value, currency)}`
      : `Booking${o.evidence.service ? `: ${String(o.evidence.service)}` : ""} · ${money(o.value, currency)}`;
  return (
    <div className="space-y-4 rounded-2xl border-2 border-dashed border-line p-5 print:hidden">
      <p className="font-hand text-xl text-muted">Agentry HQ</p>
      {status === "draft" && (
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={pending} onClick={() => act(() => hqIssueStatement(orgId, sid))}>Issue to client ({money(total, currency)})</Button>
          <span className="text-sm text-muted">Clients don&apos;t see drafts. Issuing opens a 7-day dispute window and creates a payment link.</span>
        </div>
      )}
      {disputes.length > 0 ? (
        <div className="space-y-2">
          <p className="text-sm font-semibold">Open disputes</p>
          {disputes.map((l) => (
            <div key={l.id} className="space-y-3 rounded-xl border border-warning bg-paper px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><div className="font-medium">{l.description} · {money(l.amount, currency)}</div><div className="text-ink-soft">“{l.dispute_reason}”</div></div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={pending} onClick={() => act(() => hqResolveDispute(orgId, sid, l.id, true))}>Accept (remove line)</Button>
                  <Button size="sm" variant="secondary" disabled={pending} onClick={() => { setPartialFor(partialFor === l.id ? null : l.id); setCredit(""); setNote(""); setExcluded([]); }}>Partial credit…</Button>
                  <Button size="sm" variant="secondary" disabled={pending} onClick={() => act(() => hqResolveDispute(orgId, sid, l.id, false))}>Reject (keep)</Button>
                </div>
              </div>
              {partialFor === l.id && (
                <form className="space-y-3 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault();
                  act(() => hqResolveDispute(orgId, sid, l.id, false, { credit: Number(credit), note, exclude_outcomes: excluded })); }}>
                  {l.evidence.length > 0 && (
                    <fieldset className="space-y-1"><legend className="mb-1 font-medium">Which results was the client right about?</legend>
                      {l.evidence.map((id) => evidence[id] && (
                        <label key={id} className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-[var(--ink)]"
                          checked={excluded.includes(id)} onChange={() => setExcluded(excluded.includes(id) ? excluded.filter((x) => x !== id) : [...excluded, id])} />
                          {label(evidence[id]!)}</label>
                      ))}
                    </fieldset>
                  )}
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="space-y-1"><Label htmlFor={`cr-${l.id}`}>Credit ({currency})</Label>
                      <Input id={`cr-${l.id}`} type="number" min={0.01} max={Number(l.amount)} step="0.01" required value={credit} onChange={(e) => setCredit(e.target.value)} className="w-36" /></div>
                    <div className="min-w-60 flex-1 space-y-1"><Label htmlFor={`cn-${l.id}`}>Note on the statement</Label>
                      <Input id={`cn-${l.id}`} required maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Invoice P-2 was paid before the reminder" /></div>
                    <Button size="sm" type="submit" disabled={pending}>Give credit</Button>
                  </div>
                  <p className="text-xs text-muted">The line stays; a credit line is added below it and tax is recalculated. Ticked results are excluded from the client&apos;s results report.</p>
                </form>
              )}
            </div>
          ))}
        </div>
      ) : status !== "draft" && <p className="text-sm text-muted">No open disputes.</p>}
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
    </div>
  );
}
