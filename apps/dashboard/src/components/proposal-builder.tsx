"use client";

import { Button, Card, Input, Label, ProposalDocument, type ProposalSnapshot, Select, Textarea } from "@agentry/ui";
import { useMemo, useState, useTransition } from "react";
import { hqSavePlan, hqSendProposal } from "@/app/(app)/actions";
import { money } from "@/lib/billing";

/** The "What is it worth?" calculator (docs/PRICING.md §2) turned into a printable proposal.
 *  Money lost = leads × % missed × close rate × value per customer; the fee is a slice of what the agents win back. */

const AGENTS: Record<string, string> = {
  inbox_triage: "Inbox triage", invoice_followup: "Invoice follow-up", website_chat: "Website chat agent", speed_to_lead: "Speed-to-lead",
  lead_reactivation: "Lead reactivation", ai_receptionist: "AI receptionist", cold_email: "Personal cold email",
  content_repurposing: "Content repurposing", boring_machine: "The Boring Machine (all lead agents, one calendar)",
};
const NICHE_AGENTS: Record<string, string[]> = {
  agencies: ["inbox_triage", "invoice_followup", "cold_email"],
  clinics: ["website_chat", "speed_to_lead", "lead_reactivation", "ai_receptionist"],
  home_services: ["ai_receptionist", "speed_to_lead", "lead_reactivation"],
};
const MODELS = { hybrid: "Setup + small retainer + pay per booking", retainer: "Setup + monthly retainer", start_small: "Start small (inbox triage first)" } as const;
type Model = keyof typeof MODELS;

const round = (v: number, to: number) => Math.max(to, Math.round(v / to) * to);

export type ProposalPrefill = { request: string; business: string; contact: string; email: string; niche: string };
const REQUEST_NICHE: Record<string, string> = { agency_or_firm: "agencies", clinic_or_appointments: "clinics", home_services: "home_services" };

export function ProposalBuilder({ orgs, preparedBy, prefill }: { orgs: { id: string; name: string }[]; preparedBy: string; prefill?: ProposalPrefill }) {
  const niche0 = (prefill && REQUEST_NICHE[prefill.niche]) || "clinics";
  const [f, setF] = useState({ business: prefill?.business ?? "Sunrise Dental", contact: prefill?.contact ?? "Dr. Mehta", niche: niche0, currency: "INR",
    leads: 150, missedPct: 30, closePct: 25, value: 8000, capturePct: 60, overdue: 0, model: "hybrid" as Model });
  const [agents, setAgents] = useState<string[]>(NICHE_AGENTS[niche0]!);
  const [to, setTo] = useState(prefill?.email ?? "");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState<{ ok: boolean; text: string; url?: string } | null>(null);
  const [applyTo, setApplyTo] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const v = e.target.type === "number" ? Number(e.target.value) : e.target.value;
    setF({ ...f, [k]: v });
    if (k === "niche") setAgents(NICHE_AGENTS[e.target.value] ?? []);
  };

  const r = useMemo(() => {
    const inr = f.currency === "INR";
    const missed = f.leads * (f.missedPct / 100);
    const lostCustomers = missed * (f.closePct / 100);
    const lost = lostCustomers * f.value;
    const wonCustomers = lostCustomers * (f.capturePct / 100);
    const wonBack = wonCustomers * f.value;
    const recovered = f.overdue * 0.5; // assume half of the overdue amount comes in after reminders
    const setup = inr ? (f.model === "start_small" ? 5000 : 15000) : (f.model === "start_small" ? 99 : 299);
    let retainer = 0, perBooking = 0, sharePct = 0;
    if (f.model === "hybrid") { retainer = inr ? 2999 : 49; perBooking = round(f.value * 0.15, inr ? 100 : 5); }
    if (f.model === "retainer") retainer = round(wonBack * 0.25, inr ? 500 : 10);
    if (f.model === "start_small") retainer = inr ? 4999 : 79;
    if (f.overdue > 0 && f.model !== "start_small") sharePct = 2;
    const monthlyFee = retainer + perBooking * wonCustomers + (recovered * sharePct) / 100;
    const value = (f.model === "start_small" ? 0 : wonBack) + (f.model === "start_small" ? 0 : recovered);
    return { missed, lostCustomers, lost, wonCustomers, wonBack, recovered, setup, retainer, perBooking, sharePct, monthlyFee, value,
             roi: monthlyFee > 0 && value > 0 ? value / monthlyFee : null };
  }, [f]);

  const plan = () => ({
    currency: f.currency, setup_fee: r.setup, retainer: r.retainer, tax_rate: f.currency === "INR" ? 0.18 : 0, pilot_until: null,
    included: {}, overage: {},
    outcome_prices: r.perBooking ? [{ outcome: "appointment_booked", price: r.perBooking }] : [],
    revenue_share: r.sharePct ? { basis: "overdue_only", rate: r.sharePct / 100, cap: null, window_days: 30, strong_only: false }
      : { basis: "none", rate: 0, cap: null, window_days: 30, strong_only: false },
  });

  const m = (v: number) => money(Math.round(v), f.currency).replace(/\.00$/, "");
  const today = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
  // what the client sees: the same snapshot is shown here and saved when the proposal is sent
  const snapshot: ProposalSnapshot = {
    business: f.business, contact: f.contact, date: today, preparedBy, lost: m(r.lost), leads: f.leads, missed: Math.round(r.missed),
    closePct: f.closePct, lostCustomers: r.lostCustomers.toFixed(1), valuePerCustomer: m(f.value),
    cards: [
      { label: "Lost today", value: m(r.lost), note: "per month" },
      { label: "Our agents win back", value: m(r.wonBack + r.recovered), note: `≈ ${r.wonCustomers.toFixed(1)} customers${r.recovered ? " + overdue money" : ""}` },
      { label: "Return on your fee", value: r.roi ? `${r.roi.toFixed(1)}×` : "—", note: r.roi ? `for ${m(r.monthlyFee)} a month` : "starts after step 1" },
    ],
    agents: agents.map((a) => AGENTS[a]!).filter(Boolean),
    modelLabel: MODELS[f.model],
    investment: [
      { label: "One-time setup (onboarding, connections, testing)", amount: m(r.setup) },
      ...(r.retainer > 0 ? [{ label: `Monthly ${f.model === "hybrid" ? "running costs (numbers, messages, models)" : "retainer"}`, amount: `${m(r.retainer)} / month` }] : []),
      ...(r.perBooking > 0 ? [{ label: "Per booked appointment (≈15% of a customer's value). No booking, no fee.", amount: m(r.perBooking) }] : []),
      ...(r.sharePct > 0 ? [{ label: "Share of overdue money recovered after our reminders", amount: `${r.sharePct}%` }] : []),
    ],
    gstNote: f.currency === "INR", startSmall: f.model === "start_small",
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[380px_1fr]">
      <Card className="h-fit space-y-4 p-5 print:hidden">
        <div><p className="font-hand text-xl text-muted">Agentry HQ</p><h1 className="font-display text-2xl font-bold">Proposal builder</h1></div>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 space-y-1"><Label htmlFor="biz">Business</Label><Input id="biz" value={f.business} onChange={set("business")} /></div>
          <div className="space-y-1"><Label htmlFor="who">Addressed to</Label><Input id="who" value={f.contact} onChange={set("contact")} /></div>
          <div className="space-y-1"><Label htmlFor="cur">Currency</Label><Select id="cur" value={f.currency} onChange={set("currency")}><option>INR</option><option>USD</option></Select></div>
          <div className="col-span-2 space-y-1"><Label htmlFor="niche">Niche</Label><Select id="niche" value={f.niche} onChange={set("niche")}>
            <option value="agencies">Agencies &amp; B2B firms</option><option value="clinics">Clinics &amp; appointments</option><option value="home_services">Home services</option></Select></div>
          <div className="space-y-1"><Label htmlFor="leads">Leads / month</Label><Input id="leads" type="number" min={0} value={f.leads} onChange={set("leads")} /></div>
          <div className="space-y-1"><Label htmlFor="missed">% missed</Label><Input id="missed" type="number" min={0} max={100} value={f.missedPct} onChange={set("missedPct")} /></div>
          <div className="space-y-1"><Label htmlFor="close">Close rate %</Label><Input id="close" type="number" min={0} max={100} value={f.closePct} onChange={set("closePct")} /></div>
          <div className="space-y-1"><Label htmlFor="value">Value per customer</Label><Input id="value" type="number" min={0} value={f.value} onChange={set("value")} /></div>
          <div className="space-y-1"><Label htmlFor="capture">Agents win back %</Label><Input id="capture" type="number" min={0} max={100} value={f.capturePct} onChange={set("capturePct")} /></div>
          <div className="space-y-1"><Label htmlFor="overdue">Overdue invoices / month</Label><Input id="overdue" type="number" min={0} value={f.overdue} onChange={set("overdue")} /></div>
          <div className="col-span-2 space-y-1"><Label htmlFor="model">Pricing model</Label><Select id="model" value={f.model} onChange={set("model")}>
            {Object.entries(MODELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
        </div>
        <fieldset className="space-y-1.5"><legend className="mb-1 text-sm font-medium">Agents in the proposal</legend>
          {Object.entries(AGENTS).map(([k, v]) => (
            <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[var(--ink)]" checked={agents.includes(k)}
              onChange={() => setAgents(agents.includes(k) ? agents.filter((a) => a !== k) : [...agents, k])} />{v}</label>
          ))}
        </fieldset>
        <Button className="w-full" variant="secondary" onClick={() => window.print()}>Download proposal (PDF)</Button>
        <div className="space-y-2 border-t border-line pt-4">
          <p className="text-sm font-medium">Send it to the client</p>
          <div className="space-y-1"><Label htmlFor="to">Their email</Label><Input id="to" type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="owner@business.com" /></div>
          <div className="space-y-1"><Label htmlFor="pnote">A personal line (optional)</Label><Textarea id="pnote" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. As discussed, we'd start with missed calls." /></div>
          <Button className="w-full" disabled={pending || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to) || agents.length === 0} onClick={() => {
            if (!confirm(`Email this proposal to ${to}?`)) return;
            start(async () => {
              const res = await hqSendProposal({ email: to, note, snapshot, plan: plan(), demo_request_id: prefill?.request ?? null });
              setSent(res.ok ? { ok: true, text: "Sent. You'll get an email when they open it.", url: res.data.url } : { ok: false, text: res.error });
            });
          }}>Send proposal</Button>
          {sent && <p role={sent.ok ? "status" : "alert"} className={`text-sm ${sent.ok ? "text-success" : "text-danger"}`}>{sent.text}{sent.url && <> <a className="underline" href={sent.url} target="_blank" rel="noopener">Open their copy →</a></>}</p>}
        </div>
        <div className="space-y-2 border-t border-line pt-4">
          <Label htmlFor="apply">Signed? Apply this plan to a client</Label>
          <div className="flex gap-2">
            <Select id="apply" value={applyTo} onChange={(e) => setApplyTo(e.target.value)}><option value="">Choose client…</option>
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</Select>
            <Button variant="secondary" disabled={!applyTo || pending} onClick={() => start(async () => {
              const res = await hqSavePlan(applyTo, plan());
              setMsg(res.ok ? "Plan applied." : res.error);
            })}>Apply</Button>
          </div>
          {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
        </div>
      </Card>

      <Card className="p-8 sm:p-12 print:border-0 print:p-0 print:shadow-none">
        <ProposalDocument p={snapshot} />
      </Card>
    </div>
  );
}
