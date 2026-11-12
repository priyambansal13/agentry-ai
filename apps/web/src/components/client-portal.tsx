"use client";

import { CheckCircle2, Clock, FileUp, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

type Need = { key: string; label: string };
type Filing = { id: string; title: string; status: string; due_on: string | null; filed_on: string | null; ack_no: string | null;
  extension: { label: string; url: string | null; was: string } | null; needed: Need[]; received: string[] };
type View = { firm: { firm: string; title: string; color: string; logo_url: string | null; welcome: string }; client: { name: string };
  status_labels: Record<string, string>; filings: Filing[]; due: { title: string; due_on: string; source: { type: string; label: string; url: string | null } }[];
  files: { filename: string; created_at: string }[] };

const day = (d: string | null) => (d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");
const STEPS = ["docs_pending", "in_prep", "review", "filed", "verified"];

function textOn(hex: string): string {
  const h = hex.replace("#", "");
  const f = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(f.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b! > 0.4 ? "#111" : "#fff";
}

/** A CA firm's client portal (backend automations/ca/portal.py): their filings, what's still needed, due dates, and uploads. */
export function ClientPortal({ token }: { token: string }) {
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    const r = await fetch(`${API}/public/portal/${token}`, { cache: "no-store" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return setErr(typeof body.detail === "string" ? body.detail : "This link isn't working.");
    setV(body);
  }, [token]);
  useEffect(() => { void load(); }, [load]);

  if (err) return <div className="mx-auto max-w-md py-24 text-center"><h1 className="font-display text-2xl font-bold">This link isn&apos;t working</h1><p className="mt-2 text-ink-soft">{err}</p></div>;
  if (!v) return <div className="flex min-h-[50vh] items-center justify-center gap-2"><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> Opening…</div>;
  const fg = textOn(v.firm.color);
  const open = v.filings.filter((f) => !["filed", "verified"].includes(f.status));
  const done = v.filings.filter((f) => ["filed", "verified"].includes(f.status));
  const needs = open.reduce((n, f) => n + f.needed.length, 0);
  return (
    <div className="min-h-screen bg-paper">
      <header style={{ background: v.firm.color, color: fg }}>
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-5">
          {v.firm.logo_url && /* eslint-disable-next-line @next/next/no-img-element */ <img src={v.firm.logo_url} alt="" className="h-10 w-10 rounded-lg bg-white object-contain p-1" />}
          <div><p className="font-display text-xl font-bold leading-tight">{v.firm.title}</p><p className="text-sm opacity-80">for {v.client.name}</p></div>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
        <p className="text-ink-soft">{v.firm.welcome}</p>
        {needs > 0 ? <p className="rounded-2xl border-2 border-ink bg-lime-soft p-4 font-semibold">We still need {needs} document{needs === 1 ? "" : "s"} from you. Tap a document below to send it: a photo is fine.</p>
          : open.length > 0 && <p className="flex items-center gap-2 rounded-2xl border-2 border-success bg-card p-4 font-semibold"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" /> We have everything we need for now. Thank you!</p>}

        {open.map((f) => <FilingCard key={f.id} f={f} labels={v.status_labels} token={token} color={v.firm.color} onDone={load} />)}

        <section aria-labelledby="send-other" className="rounded-2xl border-2 border-line bg-card p-4">
          <h2 id="send-other" className="font-semibold">Something else to send?</h2>
          <p className="text-sm text-muted">Notices, bills, statements: we&apos;ll put it in the right place.</p>
          <div className="mt-3"><UploadButton token={token} label="Send a file" onDone={load} color={v.firm.color} /></div>
        </section>

        {v.due.length > 0 && <section aria-labelledby="due" className="rounded-2xl border-2 border-line bg-card p-4">
          <h2 id="due" className="font-semibold">Coming up</h2>
          <ul className="mt-2 divide-y divide-line text-sm">{v.due.map((d) => (
            <li key={`${d.title}${d.due_on}`} className="py-2"><div className="flex justify-between gap-3"><span>{d.title}</span><span className="shrink-0 font-semibold">{day(d.due_on)}</span></div>
              {d.source.type === "extension" && <p className="text-xs text-success">Extended: {d.source.url ? <a href={d.source.url} target="_blank" rel="noreferrer" className="underline">{d.source.label}</a> : d.source.label}</p>}</li>))}</ul>
        </section>}

        {done.length > 0 && <section aria-labelledby="done" className="rounded-2xl border-2 border-line bg-card p-4">
          <h2 id="done" className="font-semibold">Done recently</h2>
          <ul className="mt-2 space-y-1 text-sm">{done.map((f) => <li key={f.id} className="flex justify-between gap-3"><span>{f.title}</span>
            <span className="text-muted">{v.status_labels[f.status]}{f.filed_on ? ` ${day(f.filed_on)}` : ""}{f.ack_no ? ` · ack ${f.ack_no}` : ""}</span></li>)}</ul>
        </section>}

        {v.files.length > 0 && <p className="text-xs text-muted">Last files you sent: {v.files.slice(0, 3).map((f) => f.filename).join(", ")}.</p>}
        <footer className="pt-6 text-center text-xs text-muted">This private link is just for you: please don&apos;t share it. {v.firm.firm} · powered by Agentry</footer>
      </main>
    </div>
  );
}

function FilingCard({ f, labels, token, color, onDone }: { f: Filing; labels: Record<string, string>; token: string; color: string; onDone: () => void }) {
  const at = Math.max(0, STEPS.indexOf(f.status));
  return (
    <section aria-label={f.title} className="rounded-2xl border-2 border-ink bg-card p-4 shadow-[4px_4px_0_0_var(--ink)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="font-display text-lg font-bold">{f.title}</h2>
        {f.due_on && <span className="text-sm text-ink-soft">due {day(f.due_on)}{f.extension && <span className="text-success"> (extended)</span>}</span>}</div>
      <ol className="mt-3 grid grid-cols-5 gap-1" aria-label="Progress">{STEPS.map((s, i) => (
        <li key={s} className="text-center"><div className="h-1.5 rounded-full" style={{ background: i <= at ? color : "var(--line)" }} />
          <span className={`mt-1 block text-[10px] leading-tight sm:text-xs ${i === at ? "font-semibold" : "text-muted"}`}>{labels[s]}</span></li>))}</ol>
      {f.needed.length > 0 && <div className="mt-4">
        <p className="text-sm font-semibold">Still needed</p>
        <ul className="mt-2 space-y-2">{f.needed.map((n) => (
          <li key={n.key} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-paper px-3 py-2 text-sm"><span className="flex items-center gap-2"><Clock aria-hidden="true" className="h-4 w-4 text-muted" />{n.label}</span>
            <UploadButton token={token} filing={f.id} label="Send" onDone={onDone} color={color} /></li>))}</ul></div>}
      {f.received.length > 0 && <p className="mt-3 text-xs text-muted">Received: {f.received.join(", ")}</p>}
    </section>
  );
}

function UploadButton({ token, filing, label, onDone, color }: { token: string; filing?: string; label: string; onDone: () => void; color: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<{ busy: boolean; msg: string | null; bad: boolean }>({ busy: false, msg: null, bad: false });
  async function send(file: File) {
    setState({ busy: true, msg: null, bad: false });
    const form = new FormData();
    form.append("file", file);
    if (filing) form.append("filing_id", filing);
    const r = await fetch(`${API}/public/portal/${token}/files`, { method: "POST", body: form });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return setState({ busy: false, msg: typeof body.detail === "string" ? body.detail : "Couldn't send it: try again.", bad: true });
    setState({ busy: false, msg: body.matched ? `Got it: ${body.matched}` : "Got it: we'll put it in the right place.", bad: false });
    onDone();
  }
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <input ref={input} type="file" accept="image/*,application/pdf,.csv,.xlsx" className="sr-only" aria-label={label}
        onChange={(e) => { const file = e.target.files?.[0]; if (file) void send(file); e.target.value = ""; }} />
      <button type="button" onClick={() => input.current?.click()} disabled={state.busy} style={{ background: color, color: textOn(color) }}
        className="inline-flex h-10 items-center gap-1.5 rounded-xl px-4 text-sm font-semibold disabled:opacity-60">
        {state.busy ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : filing ? <Upload aria-hidden="true" className="h-4 w-4" /> : <FileUp aria-hidden="true" className="h-4 w-4" />}
        {state.busy ? "Sending…" : label}</button>
      {state.msg && <span role="status" className={`text-xs ${state.bad ? "text-danger" : "text-success"}`}>{state.msg}</span>}
    </span>
  );
}
