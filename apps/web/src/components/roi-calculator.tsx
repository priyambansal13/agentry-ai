"use client";

import { cn } from "@agentry/ui";
import { useId, useState } from "react";

const CURRENCIES = {
  INR: { symbol: "₹", value: 8000, max: 100000, step: 500, locale: "en-IN" },
  USD: { symbol: "$", value: 500, max: 5000, step: 50, locale: "en-US" },
} as const;
type Cur = keyof typeof CURRENCIES;

/** "What is it worth?" leads × % missed × close rate × customer value = money lost per month (docs/PRICING.md §2). */
export function RoiCalculator() {
  const [cur, setCur] = useState<Cur>("INR");
  const [leads, setLeads] = useState(100);
  const [missed, setMissed] = useState(20);
  const [close, setClose] = useState(20);
  const [value, setValue] = useState<number>(CURRENCIES.INR.value);
  const c = CURRENCIES[cur];
  const fmt = (n: number) => `${c.symbol}${Math.round(n).toLocaleString(c.locale)}`;
  const lostCustomers = leads * (missed / 100) * (close / 100);
  const lost = lostCustomers * value;

  return (
    <section id="calculator" className="scroll-mt-20 border-y-2 border-ink bg-card">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2">
        <div>
          <p className="font-hand text-2xl text-muted">what is it worth?</p>
          <h2 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-5xl">Work out what missed leads cost you</h2>
          <div className="mt-6 inline-flex rounded-full border-2 border-ink p-1" role="group" aria-label="Currency">
            {(Object.keys(CURRENCIES) as Cur[]).map((k) => (
              <button key={k} type="button" aria-pressed={cur === k}
                onClick={() => { setCur(k); setValue(CURRENCIES[k].value); }}
                className={cn("rounded-full px-4 py-1.5 text-sm font-semibold", cur === k ? "bg-ink text-paper" : "text-ink")}>{k}</button>
            ))}
          </div>
          <div className="mt-8 space-y-6">
            <Slider label="Leads per month" value={leads} min={10} max={1000} step={10} onChange={setLeads} display={`${leads}`} />
            <Slider label="Missed or never followed up" value={missed} min={5} max={60} step={1} onChange={setMissed} display={`${missed}%`} />
            <Slider label="Would have bought" value={close} min={5} max={60} step={1} onChange={setClose} display={`${close}%`} />
            <Slider label="Value of one customer" value={value} min={c.step} max={c.max} step={c.step} onChange={setValue} display={fmt(value)} />
          </div>
        </div>
        <div className="flex flex-col justify-center rounded-3xl border-2 border-ink bg-lime p-8 text-lime-ink shadow-[6px_6px_0_0_var(--ink)]">
          <p className="font-hand text-2xl">you're losing about</p>
          <p className="mt-1 font-sans text-6xl font-bold tracking-tight sm:text-7xl" aria-live="polite">{fmt(lost)}</p>
          <p className="mt-1 text-lg font-semibold">every month ({lostCustomers.toFixed(1)} customers)</p>
          <dl className="mt-8 grid gap-4 border-t-2 border-lime-ink/20 pt-6 sm:grid-cols-2">
            <div>
              <dt className="text-sm font-medium opacity-75">Pay per booked appointment</dt>
              <dd className="mt-1 text-2xl font-bold">{fmt(value * 0.1)}–{fmt(value * 0.2)}</dd>
              <dd className="text-sm opacity-75">10–20% of what a customer is worth</dd>
            </div>
            <div>
              <dt className="text-sm font-medium opacity-75">Or a monthly retainer around</dt>
              <dd className="mt-1 text-2xl font-bold">{fmt(lost * 0.2)}–{fmt(lost * 0.3)}</dd>
              <dd className="text-sm opacity-75">a slice of what we win back</dd>
            </div>
          </dl>
          <a href="#demo" className="mt-8 inline-flex h-12 items-center justify-center rounded-2xl border-2 border-lime-ink bg-lime-ink px-6 font-semibold text-lime transition-transform hover:-translate-y-0.5">
            Get this back →
          </a>
        </div>
      </div>
    </section>
  );
}

function Slider({ label, value, min, max, step, onChange, display }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; display: string;
}) {
  const id = useId();
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="font-medium">{label}</label>
        <span className="font-display text-xl font-bold">{display}</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[var(--ink)]" />
    </div>
  );
}
