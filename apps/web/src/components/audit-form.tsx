"use client";

import { Button } from "@agentry/ui";
import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { attribution, track } from "./analytics";
import { useTurnstile } from "./turnstile";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";
const SERVICES = ["dentist", "dental clinic", "skin clinic", "physiotherapist", "diagnostic lab", "CA firm", "lawyer", "AC repair",
  "plumber", "pest control", "interior designer", "digital marketing agency", "coaching classes", "salon", "gym", "real estate agent"];

/** The free audit: website + city + what you do -> /audit/r/{id}. Cloudflare Turnstile when its site key is set. */
export function AuditForm({ service = "", site = "", compact = false, dark = false }: { service?: string; site?: string; compact?: boolean; dark?: boolean }) {
  const router = useRouter();
  const [f, setF] = useState({ url: site, city: "", service, company_url: "" });
  const [state, setState] = useState<{ kind: "idle" | "sending" | "error"; message?: string }>({ kind: "idle" });
  const captcha = useTurnstile(dark);
  const token = captcha.token;

  useEffect(() => { if (site) setF((x) => ({ ...x, url: site })); }, [site]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (captcha.enabled && !token) return setState({ kind: "error", message: "Please complete the quick human check." });
    setState({ kind: "sending" });
    try {
      const src = Object.entries(attribution()).map(([k, v]) => `${k}=${v}`).join("; ");
      const res = await fetch(`${API}/public/audits`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: f.url, city: f.city, service: f.service, token: token ?? undefined, source: src || undefined, company_url: f.company_url || undefined }) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Please check the details and try again.");
      track("audit_start", { service: f.service });
      router.push(`/audit/r/${body.id}`);
    } catch (err) {
      setState({ kind: "error", message: err instanceof Error ? err.message : "Something went wrong." });
      captcha.reset();
    }
  }

  const field = `h-12 w-full rounded-xl border-2 px-4 text-base placeholder:text-muted focus:outline-none ${dark ? "border-paper/40 bg-paper text-ink" : "border-ink bg-card text-ink"}`;
  return (
    <form onSubmit={submit} className={compact ? "grid gap-3 sm:grid-cols-[1.3fr_1fr_1fr_auto] sm:items-end" : "grid gap-4"}>
      {captcha.script}
      <div><label htmlFor="a-url" className="mb-1 block text-sm font-semibold">Your website</label>
        <input id="a-url" required inputMode="url" placeholder="yourbusiness.in" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} className={field} /></div>
      <div><label htmlFor="a-city" className="mb-1 block text-sm font-semibold">City</label>
        <input id="a-city" required minLength={2} placeholder="Pune" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} className={field} autoComplete="address-level2" /></div>
      <div><label htmlFor="a-service" className="mb-1 block text-sm font-semibold">What you do</label>
        <input id="a-service" required minLength={2} list="a-services" placeholder="dentist" value={f.service} onChange={(e) => setF({ ...f, service: e.target.value })} className={field} />
        <datalist id="a-services">{SERVICES.map((s) => <option key={s} value={s} />)}</datalist></div>
      <input type="text" name="company_url" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden" value={f.company_url} onChange={(e) => setF({ ...f, company_url: e.target.value })} />
      <Button type="submit" size="lg" className="h-12 rounded-xl px-6" disabled={state.kind === "sending"}>
        {state.kind === "sending" ? "Starting…" : <>Check my business <ArrowRight aria-hidden="true" className="h-5 w-5" /></>}
      </Button>
      {captcha.enabled && <div ref={captcha.box} className={compact ? "sm:col-span-4" : ""} />}
      {state.kind === "error" && <p role="alert" className={`text-sm ${dark ? "text-lime" : "text-danger"} ${compact ? "sm:col-span-4" : ""}`}>{state.message}</p>}
    </form>
  );
}
