"use client";

import { ArrowRight, Check, Copy, Loader2, Minus, Plus, ShieldCheck, Sparkles } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { track } from "../analytics";
import { useTurnstile } from "../turnstile";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Any = any;

export async function getSample(kind: string): Promise<Any> {
  const r = await fetch(`${API}/public/playground/${kind}/sample`);
  if (!r.ok) throw new Error("couldn't load the sample");
  return r.json();
}

export function useSample<T = Any>(kind: string): T | null {
  const [s, setS] = useState<T | null>(null);
  useEffect(() => { getSample(kind).then(setS).catch(() => setS(null)); }, [kind]);
  return s;
}

/** Runs a try-it box against the agent's real engine. Live (AI) boxes carry the Turnstile token. */
export function useRun<T = Any>(kind: string, live: boolean) {
  const captcha = useTurnstile();
  const [state, setState] = useState<{ busy: boolean; error: string | null; result: T | null }>({ busy: false, error: null, result: null });
  async function run(input: Any) {
    if (live && captcha.enabled && !captcha.token) return setState((s) => ({ ...s, error: "Please complete the quick human check first." }));
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      const r = await fetch(`${API}/public/playground/${kind}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input, token: live ? captcha.token ?? undefined : undefined }) });
      const body = await r.json().catch(() => ({}));
      if (live) captcha.reset();
      if (!r.ok) return setState({ busy: false, result: null, error: typeof body.detail === "string" ? body.detail : "Something went wrong: try again." });
      setState({ busy: false, error: null, result: body });
      track("agent_try", { kind });
    } catch {
      setState({ busy: false, result: null, error: "Couldn't reach the server: check your connection." });
    }
  }
  return { ...state, run, captcha, live, reset: () => setState({ busy: false, error: null, result: null }) };
}

/** Which agent page a box is on (set by Playground), so every box can show its source of truth. */
export const AgentSlug = createContext<string | null>(null);

type Sources = { basis: string; official: boolean; checked_at: string | null;
  items: { label: string; value: string | null; source: string; url: string | null; updated: boolean }[] };

/** What the box's answer rests on: the official figures and dates with links (and the last check against official
 *  sources), or the visitor's own input. */
export function SourceOfTruth({ slug }: { slug: string }) {
  const [s, setS] = useState<Sources | null>(null);
  useEffect(() => { fetch(`${API}/public/sources/${slug}`).then((r) => (r.ok ? r.json() : null)).then(setS).catch(() => setS(null)); }, [slug]);
  if (!s) return null;
  const many = s.items.length > 6;
  const plain = s.items.filter((i) => !i.updated);
  const shared = plain.length > 1 && plain.every((i) => i.source === plain[0]!.source) ? plain[0]! : null;  // one source for all: say it once
  const link = (i: { source: string; url: string | null }) => (i.url ? <a href={i.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{i.source}</a> : i.source);
  const list = (
    <ul className="mt-3 grid gap-x-8 text-sm sm:grid-cols-2">{s.items.map((i) => (
      <li key={`${i.label}${i.value}`} className="border-b border-line py-1.5">
        <div className="flex items-baseline justify-between gap-3"><span>{i.label}</span>
          <span className="flex shrink-0 items-baseline gap-1.5">{i.updated && <span className="rounded-full bg-lime px-1.5 text-[11px] font-bold text-lime-ink">updated</span>}
            {i.value && <span className="font-semibold tabular-nums">{i.value}</span>}</span></div>
        {(!shared || i.updated) && <p className="text-xs text-muted">{link(i)}</p>}
      </li>))}</ul>);
  return (
    <div className="mt-6 rounded-2xl border-2 border-dashed border-ink/40 bg-card p-4">
      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold"><ShieldCheck aria-hidden="true" className="h-4 w-4" /> Source of truth
        {s.official && <span className="text-xs font-normal text-muted">{s.checked_at ? `checked against official sources ${new Date(s.checked_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : "checked against official sources every morning"}</span>}</p>
      <p className="mt-1 text-sm text-ink-soft">{s.basis}{shared && <> Source: {link(shared)}.</>}</p>
      {s.items.length > 0 && (many ? <details className="mt-1"><summary className="cursor-pointer text-sm font-semibold underline underline-offset-4">See all {s.items.length} figures and their sources</summary>{list}</details> : list)}
    </div>
  );
}

/** The frame every box sits in: what it is, the box, its source of truth, and the line that sells the full agent. */
export function TryShell({ title, intro, children, sell, live = false }: { title: string; intro: string; children: React.ReactNode; sell: string; live?: boolean }) {
  const slug = useContext(AgentSlug);
  return (
    <section aria-label={title} className="mt-16 rounded-3xl border-2 border-ink bg-lime-soft p-5 sm:p-8">
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-hand text-2xl text-muted">try it now</p>
        <span className="inline-flex items-center gap-1 rounded-full border-2 border-ink bg-card px-3 py-0.5 text-xs font-semibold">
          {live ? <><Sparkles aria-hidden="true" className="h-3.5 w-3.5" /> Real AI, same as the portal</> : <><ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" /> The real engine, no AI guesswork</>}
        </span>
        <span className="text-xs text-muted">Nothing is saved or sent.</span>
      </div>
      <h2 className="mt-2 font-display text-3xl font-bold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-3xl text-ink-soft">{intro}</p>
      <div className="mt-6">{children}</div>
      {slug && <SourceOfTruth slug={slug} />}
      <div className="mt-8 flex flex-col gap-3 rounded-2xl border-2 border-ink bg-ink p-5 text-paper sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-2xl text-sm sm:text-base">{sell}</p>
        <span className="flex shrink-0 flex-wrap items-center gap-3">
          <a href={slug?.startsWith("ca-") ? "/start?plan=ca-firm" : "/start"} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-lime px-5 font-semibold text-lime-ink hover:opacity-90">
            Start now <ArrowRight aria-hidden="true" className="h-4 w-4" /></a>
          <a href="#demo" className="text-sm font-semibold underline underline-offset-4">or get a demo</a></span>
      </div>
    </section>
  );
}

export function RunButton({ r, label, input, disabled }: { r: ReturnType<typeof useRun>; label: string; input: () => Any; disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      {r.captcha.script}
      {r.live && r.captcha.enabled && <div ref={r.captcha.box} />}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={r.busy || disabled} onClick={() => void r.run(input())}
          className="inline-flex h-12 items-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90 disabled:opacity-50">
          {r.busy ? <><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> Working…</> : <>{label} <ArrowRight aria-hidden="true" className="h-5 w-5" /></>}
        </button>
        {r.live && <span className="text-xs text-muted">A few AI tries a day per visitor.</span>}
      </div>
      {r.error && <p role="alert" className="text-sm font-medium text-danger">{r.error}</p>}
    </div>
  );
}

export const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

export const fmtDate = (d: string | null | undefined) =>
  d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "–";

const input = "h-11 w-full rounded-xl border-2 border-ink bg-card px-3 text-base focus:outline-none focus:ring-2 focus:ring-ink/30";

export function Field({ id, label, value, onChange, type = "text", placeholder, hint }: { id: string; label: string; value: string | number; onChange: (v: string) => void; type?: string; placeholder?: string; hint?: string }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold">{label}</label>
      <input id={id} type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={input} />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Area({ id, label, value, onChange, rows = 6, placeholder }: { id: string; label: string; value: string; onChange: (v: string) => void; rows?: number; placeholder?: string }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold">{label}</label>
      <textarea id={id} rows={rows} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border-2 border-ink bg-card p-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-ink/30" />
    </div>
  );
}

export function Select({ id, label, value, onChange, options }: { id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={input}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

/** On/off chips for a client's profile ("has GST", "salaried"…). */
export function Chips({ options, value, onChange, label }: { options: [string, string][]; value: Record<string, boolean>; onChange: (v: Record<string, boolean>) => void; label: string }) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(([k, l]) => (
          <button key={k} type="button" aria-pressed={!!value[k]} onClick={() => onChange({ ...value, [k]: !value[k] })}
            className={`inline-flex items-center gap-1.5 rounded-full border-2 px-3 py-1.5 text-sm font-medium ${value[k] ? "border-ink bg-ink text-paper" : "border-ink/30 bg-card hover:border-ink"}`}>
            {value[k] && <Check aria-hidden="true" className="h-4 w-4" />}{l}</button>))}
      </div>
    </fieldset>
  );
}

/** Pick one of a few ready-made inputs. */
export function Presets<T>({ items, onPick, label = "Try a sample" }: { items: { label: string; value: T }[]; onPick: (v: T) => void; label?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-semibold text-muted">{label}:</span>
      {items.map((it) => <button key={it.label} type="button" onClick={() => onPick(it.value)}
        className="rounded-full border-2 border-ink bg-card px-3 py-1 text-sm hover:bg-lime">{it.label}</button>)}
    </div>
  );
}

/** A small spreadsheet the visitor can edit: the first row is the headings. */
export function SheetEditor({ rows, onChange, caption, maxRows = 40 }: { rows: string[][]; onChange: (r: string[][]) => void; caption: string; maxRows?: number }) {
  const [head, ...body] = rows;
  if (!head) return null;
  const set = (i: number, j: number, v: string) => onChange(rows.map((r, a) => (a === i + 1 ? r.map((c, b) => (b === j ? v : c)) : r)));
  return (
    <div>
      <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead><tr>{head.map((h, j) => <th key={j} scope="col" className="border-b-2 border-ink bg-paper px-2 py-2 text-left text-xs font-semibold whitespace-nowrap">{h}</th>)}<th className="border-b-2 border-ink bg-paper" /></tr></thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                {head.map((h, j) => (
                  <td key={j} className="p-0.5"><input aria-label={`${h}, row ${i + 1}`} value={r[j] ?? ""} onChange={(e) => set(i, j, e.target.value)}
                    className="w-full min-w-[5.5rem] rounded-md bg-transparent px-1.5 py-1.5 focus:bg-lime-soft focus:outline-none" /></td>))}
                <td className="px-1"><button type="button" aria-label={`Remove row ${i + 1}`} onClick={() => onChange(rows.filter((_, a) => a !== i + 1))}
                  className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-paper hover:text-danger"><Minus aria-hidden="true" className="h-4 w-4" /></button></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {body.length < maxRows && <button type="button" onClick={() => onChange([...rows, head.map(() => "")])}
        className="mt-2 inline-flex items-center gap-1 text-sm font-semibold underline-offset-4 hover:underline"><Plus aria-hidden="true" className="h-4 w-4" /> Add a row</button>}
      <p className="mt-1 text-xs text-muted">Edit any cell, add or remove rows: the check runs on what you see.</p>
    </div>
  );
}

export function Panel({ title, children, tone = "card", action }: { title?: React.ReactNode; children: React.ReactNode; tone?: "card" | "warn" | "good"; action?: React.ReactNode }) {
  const t = tone === "warn" ? "border-danger bg-card" : tone === "good" ? "border-success bg-card" : "border-ink bg-card";
  return (
    <div className={`rounded-2xl border-2 ${t} p-4 sm:p-5`}>
      {(title || action) && <div className="mb-3 flex items-start justify-between gap-3">{title && <h3 className="font-display text-lg font-bold">{title}</h3>}{action}</div>}
      {children}
    </div>
  );
}

export function Stat({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  return (
    <div className="rounded-2xl border-2 border-ink bg-card p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 font-display text-2xl font-bold">{value}</p>
      {note && <p className="mt-1 text-xs text-ink-soft">{note}</p>}
    </div>
  );
}

export function Copyable({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
      className="inline-flex items-center gap-1 rounded-lg border-2 border-ink bg-card px-2 py-1 text-xs font-semibold hover:bg-lime">
      {done ? <Check aria-hidden="true" className="h-3.5 w-3.5" /> : <Copy aria-hidden="true" className="h-3.5 w-3.5" />}{done ? "Copied" : label}</button>
  );
}

/** A WhatsApp-style bubble for a message the agent would send. */
export function Bubble({ children, meta, from = "us" }: { children: React.ReactNode; meta?: string; from?: "us" | "them" }) {
  return (
    <div className={`flex ${from === "us" ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[92%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-line shadow-[2px_2px_0_0_var(--ink)] ${from === "us" ? "border-2 border-ink bg-lime text-lime-ink" : "border-2 border-ink bg-card"}`}>
        {children}{meta && <span className="mt-1 block text-right text-[11px] opacity-70">{meta}</span>}
      </div>
    </div>
  );
}

/** Just enough Markdown for drafted documents: headings, lists, checkboxes, bold, paragraphs. */
export function Markdown({ text }: { text: string }) {
  const bold = (s: string) => s.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p.length > 2 && p.startsWith("*") && p.endsWith("*") ? <em key={i}>{p.slice(1, -1)}</em> : p);
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: [string, number][] } | null = null;
  const flush = () => {
    if (!list) return;
    const L = list;
    blocks.push(L.ordered ? <ol key={blocks.length} className="ml-5 list-decimal space-y-1">{L.items.map(([x, n], i) => <li key={i} value={n}>{bold(x)}</li>)}</ol>
      : <ul key={blocks.length} className="ml-5 list-disc space-y-1">{L.items.map(([x], i) => <li key={i}>{bold(x.replace(/^\[[ x]\]\s*/i, "☐ "))}</li>)}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    const ol = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    if (ul || ol) {
      const ordered = !!ol;
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push(ol ? [ol[2]!, Number(ol[1])] : [ul![1]!, 0]);
      continue;
    }
    flush();
    if (h) blocks.push(<p key={blocks.length} className={`font-display font-bold ${h[1]!.length <= 2 ? "mt-4 text-lg" : "mt-3"}`}>{bold(h[2]!)}</p>);
    else if (line.trim()) blocks.push(<p key={blocks.length}>{bold(line)}</p>);
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed">{blocks}</div>;
}

/** Reads a chosen photo or PDF as a data URL (shrinks big photos so they fit the 4 MB limit). */
export async function fileToDataUrl(f: File): Promise<string> {
  const raw = await new Promise<string>((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = bad; r.readAsDataURL(f); });
  if (!f.type.startsWith("image/") || f.size < 1.5 * 1024 * 1024) return raw;
  const img = new Image();
  await new Promise((ok) => { img.onload = ok; img.src = raw; });
  const scale = Math.min(1, 1800 / Math.max(img.width, img.height));
  const c = document.createElement("canvas");
  c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
  c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

export function Severity({ level }: { level: "high" | "medium" | "low" | "error" | "warning" | string }) {
  const hi = level === "high" || level === "error";
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${hi ? "bg-danger text-paper" : "bg-warning text-ink"}`}>{hi ? "Fix" : "Check"}</span>;
}
