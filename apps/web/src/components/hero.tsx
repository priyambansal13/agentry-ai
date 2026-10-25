"use client";

import { Button } from "@agentry/ui";
import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { BoringMachine } from "./boring-machine";

export function Hero() {
  const [site, setSite] = useState("");
  return (
    <section id="top" className="relative overflow-hidden">
      <div className="grain pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-4 pt-14 pb-10 sm:px-6 sm:pt-20">
        <p className="font-hand text-2xl text-muted">the boring work, done for you</p>
        <h1 className="mt-2 max-w-4xl font-display text-5xl leading-[1.02] font-bold tracking-tight sm:text-7xl">
          Your AI workforce,{" "}
          <span className="highlight">done for you.</span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-ink-soft sm:text-xl">
          AI agents that answer your calls, follow up every lead, chase your invoices and fill your calendar while
          you sleep. We build them, run them, and you only see the results.
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

        <div className="mt-14 rounded-3xl border-2 border-ink bg-card p-4 shadow-[6px_6px_0_0_var(--ink)] sm:p-8">
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
