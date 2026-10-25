"use client";

import { cn } from "@agentry/ui";
import { useState } from "react";
import { niches } from "@/lib/content";

export function Niches() {
  const [active, setActive] = useState(0);
  const n = niches[active]!;
  return (
    <section id="for-you" className="scroll-mt-20 border-y-2 border-ink bg-lime-soft">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <p className="font-hand text-2xl text-muted">start small, then grow</p>
        <h2 className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">Built for businesses like yours</h2>
        <div role="tablist" aria-label="Business type" className="mt-10 flex flex-wrap gap-2">
          {niches.map((x, i) => (
            <button key={x.key} role="tab" aria-selected={i === active} aria-controls={`niche-${x.key}`} onClick={() => setActive(i)}
              className={cn("rounded-full border-2 border-ink px-5 py-2.5 text-sm font-semibold transition-colors",
                i === active ? "bg-ink text-paper" : "bg-card text-ink hover:bg-lime")}>
              {x.label}
            </button>
          ))}
        </div>
        <div id={`niche-${n.key}`} role="tabpanel" className="mt-8 grid gap-8 rounded-3xl border-2 border-ink bg-card p-6 sm:p-10 lg:grid-cols-[1fr_1.3fr]">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-muted">For</p>
            <p className="mt-1 text-lg">{n.who}</p>
            <p className="mt-6 text-sm font-semibold uppercase tracking-wide text-muted">The problem</p>
            <p className="mt-1 text-lg">{n.pain}</p>
          </div>
          <ol className="flex flex-col gap-3">
            {n.ladder.map((step, i) => (
              <li key={step} className="flex items-center gap-4">
                <span className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-full border-2 border-ink font-display font-bold", i === 0 ? "bg-lime text-lime-ink" : "bg-card")}>{i + 1}</span>
                <div className="flex-1 rounded-2xl border-2 border-dashed border-line px-4 py-3">
                  <div className="font-semibold">{step}</div>
                  <div className="font-hand text-lg text-muted">{i === 0 ? "start here: live in a week" : i === 1 ? "add once it's paying for itself" : "the full machine"}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
