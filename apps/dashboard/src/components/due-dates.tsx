"use client";

import { Badge, Button, Input, Label, Select } from "@agentry/ui";
import { CheckCircle2, ExternalLink, RefreshCw, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { caCheckDueDates, hqDueDateAdd, hqDueDateDecide, hqDueDatesCheck } from "@/app/(app)/actions";
import { day } from "@/lib/ca";

/** Official due-date changes (backend automations/ca/due_dates.py): where a firm's dates come from, and HQ's review. */
export type Sync = { id: string; trigger: string; status: "running" | "done" | "failed"; found: number; proposed: number; error: string | null;
  sources: { name: string; url: string | null; ok: boolean; note: string | null }[]; started_at: string; finished_at: string | null; cost_usd?: string };
export type Update = { id: string; kind: string; period: string; original_on: string | null; due_on: string; title: string; source: string; source_url: string | null;
  quote: string | null; status: "proposed" | "active" | "rejected" | "withdrawn"; found_by: "staff" | "sync"; cards: number; decided_by: string | null; decided_at: string | null;
  created_at: string; checks: { official?: boolean; opened?: boolean; date_on_page?: boolean; quote_on_page?: boolean; note?: string | null } };
export type FirmUpdates = { active: Omit<Update, "id" | "checks" | "status" | "found_by" | "cards" | "decided_by" | "quote" | "created_at">[]; pending: number;
  last_check: Sync | null; sources: { name: string; url: string }[]; searched: string[] };

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "never");

function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => { const r = await f(); if (!r.ok) return setErr(r.error ?? "failed"); after?.(r.data); router.refresh(); });
  };
  return { err, pending, go, router };
}

function Poll({ on }: { on: boolean }) {
  const router = useRouter();
  useEffect(() => { if (!on) return; const t = setInterval(() => router.refresh(), 6000); return () => clearInterval(t); }, [on, router]);
  return null;
}

/** The compliance calendar's "where these dates come from": changes in force, the last check, and "check for updates". */
export function DueDateSources({ data, canWork }: { data: FirmUpdates; canWork: boolean }) {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  const last = data.last_check;
  const running = last?.status === "running";
  return (
    <section aria-labelledby="dd-src" className="rounded-2xl border-2 border-line bg-card p-5">
      <Poll on={running} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="dd-src" className="font-display text-lg font-bold">Where these dates come from</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted">Each date is the standard due date in the law, unless the government has extended it. Official sources are
            checked every morning; a change is verified on the official page and approved by Agentry before it moves any date. Your open cards and reminders then follow it.</p>
        </div>
        {canWork && <div className="flex flex-col items-end gap-1">
          <Button variant="secondary" disabled={pending || running} onClick={() => go(() => caCheckDueDates(), (d) => {
            const r = d as { reused: boolean; status: string };
            setMsg(r.reused && r.status !== "running" ? "Checked within the last hour: showing that check." : "Checking the official sources: this takes about a minute.");
          })}><RefreshCw aria-hidden="true" className={`mr-1.5 h-4 w-4 ${running ? "animate-spin" : ""}`} />{running ? "Checking…" : "Check for updates now"}</Button>
          {msg && <span className="text-xs text-muted">{msg}</span>}{err && <span role="alert" className="text-xs text-danger">{err}</span>}
        </div>}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <p className="text-sm font-semibold">Extensions in force</p>
          {data.active.length === 0 ? <p className="mt-1 text-sm text-muted">None right now: every date is the standard one.</p> : (
            <ul className="mt-2 space-y-2">{data.active.map((a) => (
              <li key={`${a.kind}${a.period}${a.due_on}`} className="rounded-xl bg-lime-soft px-3 py-2 text-sm">
                <span className="font-semibold">{a.title}</span>
                <span className="block text-xs text-ink-soft">{a.source_url ? <a href={a.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline">{a.source}<ExternalLink aria-hidden="true" className="h-3 w-3" /></a> : a.source}</span>
              </li>))}</ul>)}
          {data.pending > 0 && <p className="mt-2 text-xs text-muted">{data.pending} possible change{data.pending === 1 ? " is" : "s are"} being verified by Agentry.</p>}
        </div>
        <div className="text-sm">
          <p className="font-semibold">Last check: <span className="font-normal">{running ? "running now" : when(last?.finished_at ?? last?.started_at)}</span>
            {last?.status === "failed" && <Badge tone="danger">failed</Badge>}</p>
          {last && last.sources.length > 0 && <ul className="mt-2 space-y-1">{last.sources.map((s) => (
            <li key={s.name} className="flex items-start gap-1.5 text-xs">{s.ok ? <CheckCircle2 aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : <ShieldAlert aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />}
              <span>{s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="underline">{s.name}</a> : s.name}{s.note ? `: ${s.note}` : ""}</span></li>))}</ul>}
          <p className="mt-2 text-xs text-muted">Also searched: {data.searched.join(", ")}.</p>
        </div>
      </div>
    </section>
  );
}

/* ---------- Agentry HQ ---------- */

export function HqCheckNow({ running }: { running: boolean }) {
  const { err, pending, go } = useGo();
  return (
    <span className="flex items-center gap-2">
      <Poll on={running} />
      <Button disabled={pending || running} onClick={() => go(() => hqDueDatesCheck())}>
        <RefreshCw aria-hidden="true" className={`mr-1.5 h-4 w-4 ${running ? "animate-spin" : ""}`} />{running ? "Checking official sources…" : "Check official sources now"}</Button>
      {err && <span role="alert" className="text-sm text-danger">{err}</span>}
    </span>
  );
}

export function Decide({ u }: { u: Update }) {
  const { err, pending, go } = useGo();
  const [done, setDone] = useState<string | null>(null);
  return (
    <span className="flex flex-wrap items-center gap-2">
      {u.status === "proposed" && <>
        <Button size="sm" disabled={pending} onClick={() => go(() => hqDueDateDecide(u.id, "approve"), (d) => setDone(`Applied: ${(d as { cards: number }).cards} card(s) moved`))}>Approve and apply</Button>
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => go(() => hqDueDateDecide(u.id, "reject"))}>Reject</Button></>}
      {u.status === "active" && <Button size="sm" variant="secondary" disabled={pending}
        onClick={() => { if (confirm("Withdraw this change? Cards it moved go back to the standard date.")) go(() => hqDueDateDecide(u.id, "withdraw")); }}>Withdraw</Button>}
      {done && <span className="text-xs text-success">{done}</span>}{err && <span role="alert" className="text-xs text-danger">{err}</span>}
    </span>
  );
}

export function AddUpdate({ kinds }: { kinds: Record<string, string> }) {
  const { err, pending, go } = useGo();
  const empty = { kind: "itr", period: "", original_on: "", due_on: "", source: "", source_url: "", quote: "" };
  const [f, setF] = useState(empty);
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); go(() => hqDueDateAdd(f), () => setF(empty)); }}>
      <div className="space-y-1"><Label htmlFor="du-k">Filing</Label><Select id="du-k" value={f.kind} onChange={set("kind")}>{Object.entries(kinds).filter(([k]) => !["notice_reply", "other"].includes(k)).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
      <div className="space-y-1"><Label htmlFor="du-p">Period, as on the calendar</Label><Input id="du-p" required value={f.period} onChange={set("period")} placeholder="AY 2026-27 · 2026-10 · Q3 FY 2026-27" /></div>
      <div className="space-y-1"><Label htmlFor="du-o">Standard date it replaces</Label><Input id="du-o" type="date" required value={f.original_on} onChange={set("original_on")} /></div>
      <div className="space-y-1"><Label htmlFor="du-n">New due date</Label><Input id="du-n" type="date" required value={f.due_on} onChange={set("due_on")} /></div>
      <div className="space-y-1 lg:col-span-2"><Label htmlFor="du-s">Notification / circular</Label><Input id="du-s" required minLength={4} value={f.source} onChange={set("source")} placeholder="Circular No. 07/2026 dated 28 Sep 2026" /></div>
      <div className="space-y-1 lg:col-span-2"><Label htmlFor="du-u">Link to it (official site)</Label><Input id="du-u" type="url" value={f.source_url} onChange={set("source_url")} placeholder="https://www.incometax.gov.in/…" /></div>
      <div className="flex items-center gap-3 lg:col-span-4"><Button type="submit" disabled={pending}>{pending ? "Applying…" : "Add and apply to every firm"}</Button>
        {err && <span role="alert" className="text-sm text-danger">{err}</span>}</div>
    </form>
  );
}

export function Checks({ c }: { c: Update["checks"] }) {
  const item = (ok: boolean | undefined, label: string) => <li className={`flex items-center gap-1 ${ok ? "text-success" : "text-muted"}`}>{ok ? "✓" : "✗"} {label}</li>;
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
      {item(c.official, "government site")}{item(c.opened, "page opened")}{item(c.date_on_page, "new date on the page")}{item(c.quote_on_page, "quoted words on the page")}
      {c.note && <li className="basis-full text-warning">{c.note}</li>}
    </ul>
  );
}

export { day };
