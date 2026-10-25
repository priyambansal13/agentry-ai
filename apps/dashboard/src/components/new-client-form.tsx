"use client";

import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";
import { hqCreateClient, hqUpdateDemoRequest } from "@/app/(app)/actions";
import { EMPTY, formFromPlan, PlanFields, planFromForm, type PlanForm, planSections } from "@/components/hq-billing";

export type CatalogItem = { key: string; name: string; description: string; available: boolean; pages: string[]; connections: string[]; note?: string | null };

const COUNTRIES: Record<string, { label: string; currency: string; timezone: string }> = {
  IN: { label: "India", currency: "INR", timezone: "Asia/Kolkata" }, US: { label: "United States", currency: "USD", timezone: "America/New_York" },
  GB: { label: "United Kingdom", currency: "GBP", timezone: "Europe/London" }, AE: { label: "UAE", currency: "AED", timezone: "Asia/Dubai" },
  SG: { label: "Singapore", currency: "USD", timezone: "Asia/Singapore" }, AU: { label: "Australia", currency: "USD", timezone: "Australia/Sydney" },
  CA: { label: "Canada", currency: "USD", timezone: "America/Toronto" },
};
const PAGE_LABEL: Record<string, string> = { "needs-you": "Needs you", conversations: "Conversations", leads: "Leads", knowledge: "Knowledge",
  calendar: "Calendar", invoices: "Invoices", campaigns: "Campaigns" };
const CONN_LABEL: Record<string, string> = { gmail: "Gmail", whatsapp: "WhatsApp", gateways: "Razorpay / Stripe" };

/** Suggested starting prices per automation (docs/PRICING.md); every number stays editable. */
function suggested(automations: string[], currency: string): PlanForm {
  const inr = currency === "INR";
  const monthly: Record<string, number> = inr
    ? { inbox_triage: 4999, invoice_follow_up: 4999, website_chat: 2999, whatsapp_assistant: 2999, speed_to_lead: 2999, lead_reactivation: 0 }
    : { inbox_triage: 79, invoice_follow_up: 79, website_chat: 49, whatsapp_assistant: 49, speed_to_lead: 49, lead_reactivation: 0 };
  const f = formFromPlan({ ...EMPTY, currency, tax_rate: inr ? 0.18 : 0 });
  f.setup_fee = String((inr ? 5000 : 99) * Math.max(1, automations.length));
  f.retainer = String(automations.reduce((n, a) => n + (monthly[a] ?? 0), 0));
  const s = planSections(automations);
  if (s.bookings) { f.booking_mode = "fixed"; f.booking_price = inr ? "1000" : "50"; }
  if (s.recovery) { f.rs_basis = "overdue_only"; f.rs_pct = "2"; f.rs_cap = inr ? "25000" : "500"; }
  return f;
}

export type Prefill = { request: string; name: string; website: string; owner: { name: string; email: string }; automations: string[] };

export function NewClientForm({ catalog, prefill }: { catalog: CatalogItem[]; prefill?: Prefill }) {
  const router = useRouter();
  const start0 = prefill?.automations.length ? prefill.automations : ["inbox_triage"];
  const [name, setName] = useState(prefill?.name ?? "");
  const [website, setWebsite] = useState(prefill?.website ?? "");
  const [country, setCountry] = useState("IN");
  const [currency, setCurrency] = useState("INR");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [chosen, setChosen] = useState<string[]>(start0);
  const [owner, setOwner] = useState(prefill?.owner ?? { name: "", email: "" });
  const [withPlan, setWithPlan] = useState(true);
  const [plan, setPlan] = useState<PlanForm>(() => suggested(start0, "INR"));
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const visible = useMemo(() => {
    const items = catalog.filter((c) => chosen.includes(c.key));
    return { pages: [...new Set(items.flatMap((c) => c.pages))], connections: [...new Set(items.flatMap((c) => c.connections))] };
  }, [catalog, chosen]);

  function toggle(key: string) {
    const next = chosen.includes(key) ? chosen.filter((k) => k !== key) : [...chosen, key];
    setChosen(next);
    setPlan(suggested(next, currency));
  }
  function pickCountry(c: string) {
    setCountry(c);
    setCurrency(COUNTRIES[c]!.currency);
    setTimezone(COUNTRIES[c]!.timezone);
    setPlan(suggested(chosen, COUNTRIES[c]!.currency));
  }

  return (
    <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); setError(null); start(async () => {
      const r = await hqCreateClient({ name, country, timezone, currency, website, automations: chosen,
        owner: owner.email ? owner : null, plan: withPlan ? planFromForm({ ...plan, currency }) : null });
      if (!r.ok) return setError(r.error);
      if (prefill) await hqUpdateDemoRequest(prefill.request, { client_org_id: r.data.orgId });
      router.push(`/hq/${r.data.orgId}?created=1${r.data.invite ? `&invite=${r.data.invite}` : ""}`);
    }); }}>
      <Card>
        <CardHeader><CardTitle>1. The business</CardTitle></CardHeader>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="name">Business name</Label>
            <Input id="name" required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Mehta & Co Chartered Accountants" /></div>
          <div className="space-y-1"><Label htmlFor="web">Website</Label>
            <Input id="web" type="url" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://mehtaco.in" /></div>
          <div className="space-y-1"><Label htmlFor="country">Country</Label>
            <Select id="country" value={country} onChange={(e) => pickCountry(e.target.value)}>
              {Object.entries(COUNTRIES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select></div>
          <div className="space-y-1"><Label htmlFor="cur">Currency</Label>
            <Select id="cur" value={currency} onChange={(e) => { setCurrency(e.target.value); setPlan(suggested(chosen, e.target.value)); }}>
              {["INR", "USD", "EUR", "GBP", "AED"].map((c) => <option key={c}>{c}</option>)}</Select></div>
          <div className="space-y-1"><Label htmlFor="tz">Timezone</Label>
            <Input id="tz" required value={timezone} onChange={(e) => setTimezone(e.target.value)} /></div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>2. Automations they bought</CardTitle><span className="text-sm text-muted">only these are visible to the client</span></CardHeader>
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {catalog.map((c) => (
              <label key={c.key} className={`flex gap-3 rounded-xl border-2 p-4 ${!c.available ? "cursor-not-allowed opacity-50" : "cursor-pointer"} ${chosen.includes(c.key) ? "border-ink bg-lime-soft" : "border-line"}`}>
                <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--ink)]" disabled={!c.available} checked={chosen.includes(c.key)} onChange={() => toggle(c.key)} />
                <span><span className="font-semibold">{c.name}</span>{!c.available && <Badge className="ml-2">coming soon</Badge>}
                  <span className="mt-0.5 block text-sm text-muted">{c.description}</span>
                  {c.note && <span className="mt-0.5 block text-xs text-warning">{c.note}</span>}</span>
              </label>
            ))}
          </div>
          <div className="rounded-xl bg-paper p-4 text-sm">
            <p className="font-semibold">The client will see</p>
            <p className="mt-1 text-ink-soft">Home, Automations, {visible.pages.map((p) => PAGE_LABEL[p]).filter(Boolean).join(", ")}{visible.pages.length ? ", " : ""}Reports, Team, Billing
              {visible.connections.length ? ` · Connections: ${visible.connections.map((c) => CONN_LABEL[c]).join(", ")}` : ""}</p>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>3. Owner login</CardTitle><span className="text-sm text-muted">they get an email invitation (no password needed)</span></CardHeader>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="oname">Owner&apos;s name</Label>
            <Input id="oname" value={owner.name} onChange={(e) => setOwner({ ...owner, name: e.target.value })} placeholder="Rajesh Mehta" /></div>
          <div className="space-y-1"><Label htmlFor="oemail">Owner&apos;s email</Label>
            <Input id="oemail" type="email" value={owner.email} onChange={(e) => setOwner({ ...owner, email: e.target.value })} placeholder="rajesh@mehtaco.in" /></div>
          <p className="text-xs text-muted sm:col-span-2">Leave empty to invite them later from the client page. The owner can then invite their own team (manager, front desk, finance, viewer).</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>4. Pricing plan</CardTitle>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={withPlan} onChange={(e) => setWithPlan(e.target.checked)} className="h-4 w-4 accent-[var(--ink)]" />Set now</label></CardHeader>
        {withPlan && <CardBody className="space-y-3">
          <p className="text-sm text-muted">Suggested prices for the chosen automations; change anything.</p>
          <PlanFields f={{ ...plan, currency }} setF={setPlan} show={planSections(chosen)} lockCurrency />
        </CardBody>}
      </Card>

      {error && <p role="alert" className="rounded-xl border-2 border-danger px-4 py-3 text-sm text-danger">{error}</p>}
      <div className="flex items-center gap-3">
        <Button type="submit" size="lg" disabled={pending || !chosen.length}>{pending ? "Creating…" : "Create client"}</Button>
        <span className="text-sm text-muted">Automations start switched off (setup). They go live, in approval mode, when onboarding is finished.</span>
      </div>
    </form>
  );
}
