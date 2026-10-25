"use client";

import { Button, Input, Label, Select, Textarea } from "@agentry/ui";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

function normaliseUrl(s: string): string | undefined {
  const t = s.trim();
  if (!t) return undefined;
  return /^https?:\/\//i.test(t) ? t : `https://${t}`;
}

export function DemoForm() {
  const [form, setForm] = useState({ name: "", email: "", phone: "", company: "", website: "", niche: "", message: "", company_url: "" });
  const [state, setState] = useState<{ kind: "idle" | "sending" | "done" | "error"; message?: string }>({ kind: "idle" });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    const onPrefill = (e: Event) => setForm((f) => ({ ...f, website: (e as CustomEvent<{ website: string }>).detail.website }));
    window.addEventListener("agentry:prefill", onPrefill);
    return () => window.removeEventListener("agentry:prefill", onPrefill);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState({ kind: "sending" });
    try {
      const res = await fetch(`${API}/public/demo-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          phone: form.phone || undefined, company: form.company || undefined, message: form.message || undefined,
          niche: form.niche || undefined, website: normaliseUrl(form.website), company_url: form.company_url || undefined,
        }),
      });
      if (res.status === 429) throw new Error("Too many requests. Please try again in a few minutes.");
      if (!res.ok) throw new Error("Please check the highlighted details and try again.");
      setState({ kind: "done" });
    } catch (err) {
      setState({ kind: "error", message: err instanceof Error ? err.message : "Something went wrong." });
    }
  }

  return (
    <section id="demo" className="scroll-mt-20 border-t-2 border-ink bg-ink text-paper">
      <div className="mx-auto grid max-w-6xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.2fr]">
        <div>
          <p className="font-hand text-2xl text-lime">no call needed</p>
          <h2 className="mt-1 font-display text-4xl font-bold tracking-tight sm:text-5xl">Get a demo built with your business name</h2>
          <p className="mt-5 text-lg text-paper/75">Within one working day you get a short video of your own AI agent answering your customers, using your services and FAQs.</p>
        </div>
        {state.kind === "done" ? (
          <div role="status" className="flex flex-col justify-center rounded-3xl border-2 border-lime p-8">
            <p className="font-hand text-3xl text-lime">got it!</p>
            <p className="mt-2 font-display text-2xl font-bold">We&apos;re building your demo.</p>
            <p className="mt-2 text-paper/75">Check your inbox: we&apos;ve sent a confirmation, and your video follows within one working day.</p>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4 rounded-3xl bg-paper p-6 text-ink sm:grid-cols-2 sm:p-8">
            <div><Label htmlFor="d-name">Your name</Label><Input id="d-name" required minLength={2} value={form.name} onChange={set("name")} autoComplete="name" /></div>
            <div><Label htmlFor="d-email">Work email</Label><Input id="d-email" type="email" required value={form.email} onChange={set("email")} autoComplete="email" /></div>
            <div><Label htmlFor="d-company">Business name</Label><Input id="d-company" value={form.company} onChange={set("company")} autoComplete="organization" /></div>
            <div><Label htmlFor="d-site">Website</Label><Input id="d-site" inputMode="url" placeholder="yourbusiness.com" value={form.website} onChange={set("website")} /></div>
            <div><Label htmlFor="d-phone">Phone / WhatsApp</Label><Input id="d-phone" type="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" /></div>
            <div>
              <Label htmlFor="d-niche">Type of business</Label>
              <Select id="d-niche" value={form.niche} onChange={set("niche")}>
                <option value="">Choose…</option>
                <option value="agency_or_firm">Agency or professional firm</option>
                <option value="clinic_or_appointments">Clinic or appointment business</option>
                <option value="home_services">Home services</option>
                <option value="other">Something else</option>
              </Select>
            </div>
            <div className="sm:col-span-2"><Label htmlFor="d-msg">What would you like the agents to handle? (optional)</Label><Textarea id="d-msg" value={form.message} onChange={set("message")} /></div>
            {/* Honeypot for bots: hidden from people and screen readers. */}
            <input tabIndex={-1} autoComplete="off" aria-hidden="true" className="absolute -left-[9999px]" value={form.company_url} onChange={set("company_url")} name="company_url" />
            <div className="sm:col-span-2">
              <Button type="submit" size="lg" className="w-full" disabled={state.kind === "sending"}>{state.kind === "sending" ? "Sending…" : "Build my demo"}</Button>
              {state.kind === "error" && <p role="alert" className="mt-3 text-sm text-danger">{state.message}</p>}
              <p className="mt-3 text-xs text-muted">We only use your details to build your demo and get back to you.</p>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
