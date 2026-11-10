"use client";

import { Button, Input, Label } from "@agentry/ui";
import { AlertTriangle, ArrowRight, Check, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { track, trackDemoRequest } from "./analytics";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

type Named = { name: string; position: number; said: string; who: string | null };
type Issue = { severity: "high" | "medium" | "low"; issue: string; fix: string };
type Audit = {
  id: string; url: string; domain: string; city: string; service: string; status: "queued" | "running" | "done" | "failed";
  score: number | null; unlocked: boolean; waiting: boolean; ahead: number; name?: string; site_read?: boolean; engines?: string[];
  problems?: { severity: string; title: string; detail: string }[];
  parts?: {
    assistants: { points: number; of: number; asked: number; named: number; rate: number; named_instead: { name: string; mentions: number }[]; sources?: { site: string; times: number }[] };
    reach: { points: number; of: number; chat: boolean; whatsapp: boolean; booking: boolean; phone: boolean };
    website: { points: number; of: number; score: number; issues: number | Issue[] };
  };
  answers?: { engine: string; question: string; answer: string; named: Named[]; error: string | null }[];
};
const LABEL: Record<string, string> = { chatgpt: "ChatGPT", gemini: "Gemini", perplexity: "Perplexity" };
const rupees = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export function AuditReport({ id }: { id: string }) {
  const [a, setA] = useState<Audit | null>(null);
  const [missing, setMissing] = useState(false);
  const load = useCallback(async () => {
    const r = await fetch(`${API}/public/audits/${id}`, { cache: "no-store" });
    if (r.status === 404) return setMissing(true);
    if (r.ok) setA(await r.json());
  }, [id]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!a || a.status === "done" || a.status === "failed") return;
    const t = setInterval(() => void load(), a.waiting ? 30000 : 3000);
    return () => clearInterval(t);
  }, [a, load]);

  if (missing) return <Empty title="This report isn't available" body="Reports are kept for 30 days. Run a new audit; it only takes a minute." />;
  if (!a) return <Loading text="Opening your report…" />;
  if (a.status === "failed") return <Empty title="We couldn't finish this audit" body="Something went wrong on our side. Please try again in a few minutes." />;
  if (a.status !== "done") {
    return a.waiting
      ? <Empty title="You're in the queue" body={`Lots of businesses are checking today. Yours runs as soon as there's room${a.ahead ? ` (${a.ahead} ahead of you)` : ""}; keep this page open or bookmark it.`} />
      : <Loading text={`Checking ${a.domain}: reading your website and asking AI assistants about ${a.service} in ${a.city}…`} />;
  }
  return <Report a={a} reload={load} />;
}

function Report({ a, reload }: { a: Audit; reload: () => Promise<void> }) {
  const p = a.parts!;
  const tone = (a.score ?? 0) >= 70 ? "text-success" : (a.score ?? 0) >= 45 ? "text-warning" : "text-danger";
  return (
    <div className="space-y-10">
      <header>
        <p className="font-hand text-2xl text-muted">your audit · {a.service} in {a.city}</p>
        <h1 className="mt-1 font-display text-4xl font-bold tracking-tight sm:text-5xl">{a.name ?? a.domain}</h1>
        <p className="mt-1 text-muted">{a.domain}</p>
        <div className="mt-6 flex flex-wrap items-end gap-6 rounded-3xl border-2 border-ink bg-card p-6 shadow-[6px_6px_0_0_var(--ink)]">
          <p><span className={`font-display text-7xl font-bold tabular-nums ${tone}`}>{a.score}</span><span className="text-2xl text-muted">/100</span></p>
          <ul className="grid flex-1 gap-2 text-sm sm:grid-cols-3">
            <Part label="AI assistants" pts={p.assistants.points} of={p.assistants.of} />
            <Part label="Reaching you" pts={p.reach.points} of={p.reach.of} />
            <Part label="Website basics" pts={p.website.points} of={p.website.of} />
          </ul>
        </div>
      </header>

      {a.problems && a.problems.length > 0 && (
        <section aria-labelledby="problems">
          <h2 id="problems" className="font-display text-3xl font-bold tracking-tight">The biggest problems</h2>
          <ol className="mt-5 space-y-3">{a.problems.map((x) => (
            <li key={x.title} className="flex gap-3 rounded-2xl border-2 border-ink bg-card p-4">
              <AlertTriangle aria-hidden="true" className={`mt-0.5 h-5 w-5 shrink-0 ${x.severity === "high" ? "text-danger" : "text-warning"}`} />
              <div><p className="font-semibold">{x.title}</p><p className="text-ink-soft">{x.detail}</p></div>
            </li>))}</ol>
        </section>
      )}

      <section aria-labelledby="ai" className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-3xl border-2 border-ink bg-ink p-6 text-paper">
          <h2 id="ai" className="font-display text-2xl font-bold">When customers ask AI</h2>
          <p className="mt-3 text-paper/80">We asked {a.engines?.join(" and ") || "AI assistants"} {p.assistants.asked} times who to go to for {a.service} in {a.city}.</p>
          <p className="mt-4 font-display text-5xl font-bold text-lime">{p.assistants.named} <span className="text-2xl text-paper/70">of {p.assistants.asked} answers named you</span></p>
          {p.assistants.named_instead.length > 0 && <>
            <p className="mt-5 text-sm font-semibold uppercase tracking-wide text-paper/60">Named instead</p>
            <ul className="mt-2 space-y-1">{p.assistants.named_instead.map((n) => <li key={n.name} className="flex justify-between gap-3"><span>{n.name}</span><span className="text-paper/60">{n.mentions}×</span></li>)}</ul>
          </>}
        </div>
        <div className="rounded-3xl border-2 border-ink bg-card p-6">
          <h2 className="font-display text-2xl font-bold">What an evening visitor finds</h2>
          <ul className="mt-4 space-y-3">
            <Has ok={p.reach.chat} yes="Instant answers (chat) on the website" no="No chat: questions after hours go unanswered" />
            <Has ok={p.reach.whatsapp} yes="A WhatsApp link" no="No WhatsApp link" />
            <Has ok={p.reach.booking} yes="Online booking" no="No way to book online" />
            <Has ok={p.reach.phone} yes="A phone number" no="No phone number on the site" />
          </ul>
          {!a.site_read && <p className="mt-4 text-sm text-warning">We couldn&apos;t read your website, so this part may be incomplete.</p>}
        </div>
      </section>

      <MoneyAtRisk reach={p.reach} />

      {a.unlocked ? <Full a={a} /> : <Unlock id={a.id} onDone={reload} issues={typeof p.website.issues === "number" ? p.website.issues : p.website.issues.length} />}

      <section className="rounded-3xl border-2 border-ink bg-lime p-6 text-lime-ink sm:p-8">
        <h2 className="font-display text-3xl font-bold">Want this fixed for you?</h2>
        <p className="mt-2 max-w-2xl">We set up an AI assistant that answers your website and WhatsApp from your own facts, day and night, and we check every month
          whether ChatGPT names you, with the fixes done for you.</p>
        <a href="#demo" className="mt-5 inline-flex h-12 items-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90">
          Build my free demo <ArrowRight aria-hidden="true" className="h-5 w-5" /></a>
      </section>
    </div>
  );
}

function Part({ label, pts, of }: { label: string; pts: number; of: number }) {
  return (
    <li><p className="font-semibold">{label}</p>
      <p className="tabular-nums text-muted">{pts} of {of}</p>
      <span className="mt-1 block h-2 overflow-hidden rounded-full bg-paper" aria-hidden="true"><span className="block h-full rounded-full bg-ink" style={{ width: `${Math.max(3, (100 * pts) / of)}%` }} /></span></li>
  );
}

function Has({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return <li className="flex gap-2">{ok ? <Check aria-hidden="true" className="h-5 w-5 shrink-0 text-success" /> : <X aria-hidden="true" className="h-5 w-5 shrink-0 text-danger" />}
    <span>{ok ? yes : no}<span className="sr-only">{ok ? " (yes)" : " (missing)"}</span></span></li>;
}

/** An estimate the visitor controls: every number is theirs to change. */
function MoneyAtRisk({ reach }: { reach: { chat: boolean; whatsapp: boolean } }) {
  const [v, setV] = useState({ visits: 600, ask: 5, value: 3000 });
  const after = 0.4; // share of visits outside office hours
  const unanswered = reach.chat ? 0.1 : reach.whatsapp ? 0.6 : 0.9; // share of after-hours questions that never get an answer
  const lost = v.visits * (v.ask / 100) * after * unanswered;
  const money = lost * 0.3 * v.value; // about 3 in 10 answered enquiries become customers
  return (
    <section aria-labelledby="money" className="rounded-3xl border-2 border-dashed border-ink p-6">
      <h2 id="money" className="font-display text-2xl font-bold">What it may be costing you</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Num id="m-v" label="Website visits a month" value={v.visits} onChange={(n) => setV({ ...v, visits: n })} />
        <Num id="m-a" label="% who have a question" value={v.ask} onChange={(n) => setV({ ...v, ask: n })} />
        <Num id="m-c" label="A new customer is worth (₹)" value={v.value} onChange={(n) => setV({ ...v, value: n })} />
      </div>
      <p className="mt-5 text-lg">About <strong>{Math.round(lost)}</strong> questions a month arrive after hours and go unanswered: roughly{" "}
        <strong className="font-display text-2xl">{rupees(money)}</strong> a month in customers who went elsewhere.</p>
      <p className="mt-2 text-sm text-muted">Assumes 4 in 10 visits are outside office hours and 3 in 10 answered questions become customers. Change the numbers to yours.</p>
    </section>
  );
}

function Num({ id, label, value, onChange }: { id: string; label: string; value: number; onChange: (n: number) => void }) {
  return <div><Label htmlFor={id}>{label}</Label><Input id={id} type="number" min={0} value={value} onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))} /></div>;
}

function Unlock({ id, onDone, issues }: { id: string; onDone: () => Promise<void>; issues: number }) {
  const [f, setF] = useState({ name: "", email: "", phone: "", company_url: "" });
  const [state, setState] = useState<{ kind: "idle" | "sending" | "error"; message?: string }>({ kind: "idle" });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState({ kind: "sending" });
    const r = await fetch(`${API}/public/audits/${id}/report`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...f, phone: f.phone || undefined, company_url: f.company_url || undefined }) });
    if (!r.ok) return setState({ kind: "error", message: r.status === 422 ? "Please check your name and email." : "Please try again in a minute." });
    trackDemoRequest("audit");
    track("audit_report_unlocked");
    await onDone();
  }
  return (
    <section aria-labelledby="unlock" className="rounded-3xl border-2 border-ink bg-card p-6 sm:p-8">
      <h2 id="unlock" className="font-display text-3xl font-bold tracking-tight">Get the full report</h2>
      <p className="mt-2 max-w-2xl text-ink-soft">Every AI answer word for word, who was named for each question, the {issues} website fix{issues === 1 ? "" : "es"} in order, and
        what to do first. We&apos;ll also email you the link.</p>
      <form onSubmit={submit} className="mt-5 grid gap-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
        <div><Label htmlFor="u-name">Your name</Label><Input id="u-name" required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" /></div>
        <div><Label htmlFor="u-email">Email</Label><Input id="u-email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></div>
        <div><Label htmlFor="u-phone">WhatsApp (optional)</Label><Input id="u-phone" type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} autoComplete="tel" /></div>
        <input type="text" name="company_url" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden" value={f.company_url} onChange={(e) => setF({ ...f, company_url: e.target.value })} />
        <Button type="submit" size="lg" className="h-10" disabled={state.kind === "sending"}>{state.kind === "sending" ? "Opening…" : "Show me"}</Button>
      </form>
      {state.kind === "error" && <p role="alert" className="mt-2 text-sm text-danger">{state.message}</p>}
      <p className="mt-3 text-xs text-muted">No newsletters. One person from our team may reply to your report. <a href="/privacy" className="underline">Privacy</a></p>
    </section>
  );
}

function Full({ a }: { a: Audit }) {
  const issues = Array.isArray(a.parts!.website.issues) ? a.parts!.website.issues : [];
  const byQ = new Map<string, NonNullable<Audit["answers"]>>();
  for (const x of a.answers ?? []) byQ.set(x.question, [...(byQ.get(x.question) ?? []), x]);
  return (
    <div className="space-y-10">
      <section aria-labelledby="answers">
        <h2 id="answers" className="font-display text-3xl font-bold tracking-tight">Every AI answer</h2>
        <div className="mt-5 space-y-4">{[...byQ.entries()].map(([q, xs]) => (
          <div key={q} className="rounded-2xl border-2 border-ink bg-card p-5">
            <p className="font-semibold">“{q}”</p>
            {xs.map((x) => (
              <details key={x.engine} className="mt-3 border-t border-line pt-3">
                <summary className="cursor-pointer text-sm"><span className="font-semibold">{LABEL[x.engine] ?? x.engine}:</span>{" "}
                  {x.error ? <span className="text-muted">didn&apos;t answer</span> : x.named.length === 0 ? <span className="text-muted">named no business</span>
                    : x.named.map((n) => <span key={n.name} className={n.who === "me" ? "font-bold text-success" : ""}>{n.position}. {n.name}{" "}</span>)}</summary>
                {x.answer && <p className="mt-2 whitespace-pre-line text-sm text-ink-soft">{x.answer}</p>}
              </details>))}
          </div>))}</div>
        {a.parts!.assistants.sources && a.parts!.assistants.sources.length > 0 && (
          <p className="mt-4 text-sm text-muted">The assistants looked at: {a.parts!.assistants.sources.slice(0, 6).map((s) => s.site).join(", ")}. Being listed there,
            with the same name, address and phone as your website, helps them find you.</p>)}
      </section>
      <section aria-labelledby="fixes">
        <h2 id="fixes" className="font-display text-3xl font-bold tracking-tight">Website fixes, in order</h2>
        {issues.length === 0 ? <p className="mt-4 text-success">Nothing to fix on the basics. Nice.</p> : (
          <ol className="mt-5 space-y-3">{issues.map((i) => (
            <li key={i.issue} className="rounded-2xl border-2 border-line bg-card p-4">
              <p className="font-semibold"><span className={`mr-2 rounded-full px-2 py-0.5 text-xs uppercase ${i.severity === "high" ? "bg-danger text-white" : i.severity === "medium" ? "bg-warning text-ink" : "bg-paper"}`}>{i.severity}</span>{i.issue}</p>
              <p className="mt-1 text-ink-soft">{i.fix}</p>
            </li>))}</ol>)}
      </section>
    </div>
  );
}

function Loading({ text }: { text: string }) {
  return <div role="status" className="flex min-h-[40vh] flex-col items-center justify-center gap-4 text-center">
    <Loader2 aria-hidden="true" className="h-10 w-10 animate-spin" /><p className="max-w-md text-lg">{text}</p>
    <p className="text-sm text-muted">This takes about a minute.</p></div>;
}

function Empty({ title, body }: { title: string; body: string }) {
  return <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-center">
    <h1 className="font-display text-3xl font-bold">{title}</h1><p className="max-w-md text-ink-soft">{body}</p>
    <a href="/audit" className="mt-2 inline-flex h-12 items-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper">Run an audit <ArrowRight aria-hidden="true" className="h-5 w-5" /></a></div>;
}
