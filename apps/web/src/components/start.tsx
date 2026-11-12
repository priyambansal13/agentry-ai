"use client";

import { ArrowRight, Check, Loader2, MailCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { attribution, track } from "./analytics";
import { useTurnstile } from "./turnstile";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";
type Plan = { key: string; name: string; tagline: string; audience: string; highlights: string[]; agents: string[]; optional: string[]; currency: string;
  monthly: string; setup: string; tax_rate: number; first_payment: string; included_messages: number | null };

const money = (v: string, c: string) => (c === "INR" ? "₹" : "$") + Number(v).toLocaleString(c === "INR" ? "en-IN" : "en-US", { maximumFractionDigits: 2 });

/** Website /start (backend agentry/signups.py): pick a plan, your details, pay the first month; the account link comes by email. */
export function StartFlow({ plan: initial, site }: { plan?: string; site?: string }) {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [pick, setPick] = useState(initial ?? "");
  const [f, setF] = useState({ business: "", website: site ?? "", name: "", email: "", phone: "", country: "IN", company_url: "" });
  const [state, setState] = useState<{ kind: "idle" | "sending" | "error" | "handoff"; message?: string }>({ kind: "idle" });
  const captcha = useTurnstile();
  useEffect(() => {
    fetch(`${API}/public/plans?currency=${f.country === "IN" ? "INR" : "USD"}`).then((r) => r.json()).then((d) => {
      setPlans(d.plans); if (!pick && d.plans[0]) setPick(d.plans[0].key);
    }).catch(() => setPlans([]));
  }, [f.country]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = plans?.find((p) => p.key === pick);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (captcha.enabled && !captcha.token) return setState({ kind: "error", message: "Please complete the quick human check." });
    setState({ kind: "sending" });
    const src = Object.entries(attribution()).map(([k, v]) => `${k}=${v}`).join("; ");
    const r = await fetch(`${API}/public/signups`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...f, pack: pick, website: f.website || undefined, phone: f.phone || undefined, company_url: f.company_url || undefined,
        token: captcha.token ?? undefined, source: src || undefined }) });
    const body = await r.json().catch(() => ({}));
    captcha.reset();
    if (!r.ok) return setState({ kind: "error", message: typeof body.detail === "string" ? body.detail : "Please check your details and try again." });
    track("begin_checkout", { plan: pick });
    if (body.pay_url) { window.location.href = body.pay_url; return; }
    setState({ kind: "handoff" });
  }

  const field = "h-12 w-full rounded-xl border-2 border-ink bg-card px-4 text-base focus:outline-none focus:ring-2 focus:ring-ink/30";
  if (state.kind === "handoff") return (
    <div className="rounded-3xl border-2 border-ink bg-lime p-8 text-lime-ink">
      <h2 className="font-display text-3xl font-bold">Thank you, {f.name.split(" ")[0]}!</h2>
      <p className="mt-2 text-lg">We&apos;ll call you today to take the first payment and switch {f.business} on. You&apos;ll also get an email from us.</p>
    </div>);
  return (
    <div className="space-y-10">
      <section aria-label="Plans">
        {plans === null ? <p className="flex items-center gap-2 text-muted"><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> Loading plans…</p> : (
          <div className="grid gap-5 lg:grid-cols-3">{plans.map((p) => {
            const on = p.key === pick;
            return (
              <button key={p.key} type="button" onClick={() => setPick(p.key)} aria-pressed={on}
                className={`flex h-full flex-col rounded-3xl border-2 p-6 text-left transition ${on ? "border-ink bg-lime-soft shadow-[6px_6px_0_0_var(--ink)]" : "border-ink/30 bg-card hover:border-ink"}`}>
                <span className="flex items-center justify-between"><span className="font-display text-2xl font-bold">{p.name}</span>
                  {on && <span className="grid h-7 w-7 place-items-center rounded-full bg-ink text-paper"><Check aria-hidden="true" className="h-4 w-4" /></span>}</span>
                <span className="mt-1 text-ink-soft">{p.tagline}</span>
                <span className="mt-4"><span className="font-display text-4xl font-bold">{money(p.monthly, p.currency)}</span><span className="text-muted"> / month</span></span>
                <span className="text-xs text-muted">{Number(p.setup) > 0 ? `+ ${money(p.setup, p.currency)} one-time setup · ` : "No setup fee · "}{p.tax_rate ? `+ ${p.tax_rate * 100}% GST` : ""}</span>
                <ul className="mt-4 space-y-1.5 text-sm">{p.highlights.map((h) => <li key={h} className="flex gap-2"><Check aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-success" />{h}</li>)}</ul>
                {p.included_messages && <span className="mt-auto pt-4 text-xs text-muted">{p.included_messages.toLocaleString("en-IN")} messages a month included</span>}
              </button>);
          })}</div>)}
      </section>

      <form onSubmit={submit} className="rounded-3xl border-2 border-ink bg-card p-6 shadow-[6px_6px_0_0_var(--ink)] sm:p-8">
        {captcha.script}
        <h2 className="font-display text-2xl font-bold">Your details</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div><label htmlFor="s-b" className="mb-1 block text-sm font-semibold">Business name</label><input id="s-b" required minLength={2} value={f.business} onChange={(e) => setF({ ...f, business: e.target.value })} className={field} /></div>
          <div><label htmlFor="s-w" className="mb-1 block text-sm font-semibold">Website <span className="font-normal text-muted">(we&apos;ll read it for you)</span></label><input id="s-w" inputMode="url" placeholder="yourbusiness.in" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} className={field} /></div>
          <div><label htmlFor="s-n" className="mb-1 block text-sm font-semibold">Your name</label><input id="s-n" required minLength={2} autoComplete="name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={field} /></div>
          <div><label htmlFor="s-e" className="mb-1 block text-sm font-semibold">Email <span className="font-normal text-muted">(your account link goes here)</span></label><input id="s-e" type="email" required autoComplete="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} className={field} /></div>
          <div><label htmlFor="s-p" className="mb-1 block text-sm font-semibold">WhatsApp / mobile</label><input id="s-p" type="tel" autoComplete="tel" placeholder="+91 98100 00011" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className={field} /></div>
          <div><label htmlFor="s-c" className="mb-1 block text-sm font-semibold">Country</label><select id="s-c" value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })} className={field}>
            {[["IN", "India"], ["AE", "UAE"], ["SG", "Singapore"], ["GB", "United Kingdom"], ["US", "United States"], ["AU", "Australia"], ["CA", "Canada"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        </div>
        <input type="text" name="company_url" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden" value={f.company_url} onChange={(e) => setF({ ...f, company_url: e.target.value })} />
        {captcha.enabled && <div ref={captcha.box} className="mt-4" />}
        <div className="mt-6 flex flex-col gap-3 border-t-2 border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm">{chosen ? <>Today: <strong className="font-display text-xl">{money(chosen.first_payment, chosen.currency)}</strong> <span className="text-muted">
            ({Number(chosen.setup) > 0 ? "setup + " : ""}first month{chosen.tax_rate ? " + GST" : ""}). Then {money(chosen.monthly, chosen.currency)} a month; cancel any time.</span></> : "Pick a plan above."}</p>
          <button type="submit" disabled={!chosen || state.kind === "sending"} className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90 disabled:opacity-50">
            {state.kind === "sending" ? <><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> One moment…</> : <>Continue to payment <ArrowRight aria-hidden="true" className="h-5 w-5" /></>}</button>
        </div>
        {state.kind === "error" && <p role="alert" className="mt-3 text-sm text-danger">{state.message}</p>}
        <p className="mt-3 text-xs text-muted">Secure payment by Razorpay (UPI, cards, net banking). Your assistant starts in approval mode: nothing goes to a customer until you&apos;ve seen it.</p>
      </form>
    </div>
  );
}

/** After paying: Razorpay sends the visitor here; the webhook may land a moment later, so this waits for it. */
export function StartDone({ id }: { id: string }) {
  const [s, setS] = useState<{ status: string; business: string; email: string } | null>(null);
  useEffect(() => {
    let n = 0;
    const tick = async () => {
      const r = await fetch(`${API}/public/signups/${id}`, { cache: "no-store" }).catch(() => null);
      const d = r && r.ok ? await r.json() : null;
      if (d) setS(d);
      if ((!d || d.status === "pending_payment") && n++ < 40) setTimeout(tick, 3000);
      else if (d && d.status !== "pending_payment") track("purchase", { value: "1" });
    };
    void tick();
  }, [id]);
  if (!s || s.status === "pending_payment") return (
    <div className="flex flex-col items-center gap-3 py-16 text-center"><Loader2 aria-hidden="true" className="h-8 w-8 animate-spin" />
      <p className="text-lg">Confirming your payment…</p><p className="text-sm text-muted">This usually takes a few seconds. If you closed the payment page, nothing was charged.</p></div>);
  return (
    <div className="rounded-3xl border-2 border-ink bg-lime p-8 text-center text-lime-ink">
      <MailCheck aria-hidden="true" className="mx-auto h-12 w-12" />
      <h1 className="mt-3 font-display text-3xl font-bold">Payment received. Check your email.</h1>
      <p className="mt-2 text-lg">We sent the link to open {s.business}&apos;s account to <strong>{s.email}</strong>. One click signs you in.</p>
      <p className="mt-4 text-sm">Then: connect WhatsApp, check your services and prices, and try a conversation. Most businesses are live the same day.</p>
    </div>);
}
