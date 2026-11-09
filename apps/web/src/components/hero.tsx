"use client";

import { Button } from "@agentry/ui";
import { ArrowRight, Check } from "lucide-react";
import { useState } from "react";
import { catalog } from "@/lib/catalog";
import { BoringMachine } from "./boring-machine";

const PROOF = ["Live in about 7 days", "Approval mode first", "From your own WhatsApp and email", "Pay per result available"];

export function Hero() {
  const [site, setSite] = useState("");
  return (
    <section id="top" className="relative overflow-hidden">
      <div className="grain pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-4 pt-14 pb-10 sm:px-6 sm:pt-20">
        <p className="rise inline-flex items-center gap-2 rounded-full border-2 border-ink bg-card px-4 py-1.5 text-sm font-semibold">
          <span className="h-2 w-2 rounded-full bg-success" aria-hidden="true" /> {catalog.length} AI agents · built for Indian businesses
        </p>
        <h1 className="rise mt-5 max-w-4xl font-display text-5xl leading-[1.02] font-bold tracking-tight sm:text-7xl" style={{ animationDelay: "60ms" }}>
          Your AI workforce,{" "}
          <span className="highlight">done for you.</span>
        </h1>
        <p className="rise mt-6 max-w-2xl text-lg text-ink-soft sm:text-xl" style={{ animationDelay: "120ms" }}>
          AI agents that answer your WhatsApp and calls, follow up every lead, chase your invoices, post your content and
          prepare your tax season. We build them, run them, and you see the results.
        </p>
        <form
          className="mt-8 flex max-w-xl flex-col gap-3 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent("agentry:prefill", { detail: { website: site } }));
            document.getElementById("demo")?.scrollIntoView({ behavior: "smooth" });
          }}
        >
          <label htmlFor="hero-site" className="sr-only">Your website</label>
          <input
            id="hero-site" type="text" inputMode="url" placeholder="yourbusiness.com" value={site}
            onChange={(e) => setSite(e.target.value)}
            className="h-14 w-full rounded-2xl sm:flex-1 border-2 border-ink bg-card px-5 text-base text-ink placeholder:text-muted focus:outline-none"
          />
          <Button type="submit" size="lg" className="h-14 rounded-2xl px-6">
            Build my free demo <ArrowRight className="h-5 w-5" />
          </Button>
        </form>
        <p className="mt-3 text-sm text-muted">We build a demo with <em>your</em> business name and send you a 2-minute video. No call needed.</p>
        <ul className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm font-medium text-ink-soft">
          {PROOF.map((p) => <li key={p} className="inline-flex items-center gap-1.5"><Check aria-hidden="true" className="h-4 w-4 text-success" />{p}</li>)}
        </ul>

        <div className="marquee mt-12 -mx-4 overflow-hidden border-y-2 border-ink bg-lime py-3 text-lime-ink sm:mx-0 sm:rounded-full sm:border-2" aria-hidden="true">
          <div className="marquee-track flex w-max gap-8 font-display font-semibold">
            {[...catalog, ...catalog].map((a, i) => <span key={i} className="whitespace-nowrap">{a.name} ✦</span>)}
          </div>
        </div>

        <div className="mt-10 rounded-3xl border-2 border-ink bg-card p-4 shadow-[6px_6px_0_0_var(--ink)] sm:p-8">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-display text-lg font-semibold">The Boring Machine</span>
            <span className="font-hand text-xl text-muted">five agents, one calendar</span>
          </div>
          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <BoringMachine className="min-w-[680px]" />
          </div>
          <p className="mt-2 font-hand text-lg text-muted sm:hidden">swipe to see the whole machine →</p>
        </div>
      </div>
    </section>
  );
}
