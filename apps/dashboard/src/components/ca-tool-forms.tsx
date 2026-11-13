"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { caBankLine, caBookRecurring, caLedgerLine, caDeleteRecurring, caDeleteWork, caItr, caConfirmReply, caConfirmSend, caConfirmSet, caSaveRecurring, caTaxOpening, caTool } from "@/app/(app)/actions";

/** Forms for the CA agents that work on files (GST, capital gains, bank, notices, TDS, 3CD, Excel desk) and the ITR computation. */
function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => {
      const r = await f();
      if (!r.ok) return setErr(r.error ?? "failed");
      after?.(r.data);
      router.refresh();
    });
  };
  return { err, pending, go, router };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);
const workId = (d: unknown) => { const x = d as { id?: string; work_id?: string }; return x.work_id ?? x.id; };

export type ToolSpec = { key: string; path: string; files: { name: string; label: string; accept: string }[]; extra?: "period" | "fy" | "columns" | "question" | "tolerance" | "standardise_names" | "as_of";
  sample?: boolean; hint: string; button: string };

export function ToolForm({ spec, clientId }: { spec: ToolSpec; clientId?: string }) {
  const { err, pending, go, router } = useGo();
  const [minBal, setMinBal] = useState("0");
  const [extra, setExtra] = useState(spec.extra === "as_of" ? "2026-03-31" : spec.extra === "fy" ? "2025" : spec.extra === "period" ? "" : spec.extra === "tolerance" ? "1" : spec.extra === "standardise_names" ? "false" : "");
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const ready = spec.files.every((f) => files[f.name]) && (!["period", "question"].includes(spec.extra ?? "") || extra.trim().length > 1);
  const open = (d: unknown) => { const id = workId(d); if (id) router.push(`/ca-work/${id}`); };
  return (
    <form className="space-y-2" onSubmit={(e) => {
      e.preventDefault();
      const fd = new FormData();
      spec.files.forEach((f) => fd.append(f.name, files[f.name]!));
      if (spec.extra) fd.append(spec.extra, extra);
      if (spec.extra === "as_of") fd.append("min_balance", minBal.replace(/,/g, "") || "0");
      go(() => caTool(spec.path, fd, clientId), open);
    }}>
      <p className="text-sm text-muted">{spec.hint}</p>
      <div className="flex flex-wrap items-end gap-2">
        {spec.files.map((f) => (
          <div key={f.name} className="space-y-1"><Label htmlFor={`${spec.key}-${f.name}`}>{f.label}</Label>
            <input id={`${spec.key}-${f.name}`} type="file" accept={f.accept} className="block text-sm" onChange={(e) => setFiles({ ...files, [f.name]: e.target.files?.[0] ?? null })} /></div>))}
        {spec.extra === "period" && <div className="space-y-1"><Label htmlFor={`${spec.key}-p`}>Period</Label><Input id={`${spec.key}-p`} className="w-36" placeholder="Oct 2026" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>}
        {spec.extra === "fy" && <div className="space-y-1"><Label htmlFor={`${spec.key}-fy`}>Financial year starting</Label><Input id={`${spec.key}-fy`} className="w-24" inputMode="numeric" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>}
        {spec.extra === "as_of" && <><div className="space-y-1"><Label htmlFor={`${spec.key}-d`}>Balances as at</Label><Input id={`${spec.key}-d`} type="date" className="w-40" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor={`${spec.key}-m`}>Ask parties with at least (₹)</Label><Input id={`${spec.key}-m`} className="w-32" inputMode="decimal" value={minBal} onChange={(e) => setMinBal(e.target.value)} /></div></>}
        {spec.extra === "columns" && <div className="space-y-1"><Label htmlFor={`${spec.key}-c`}>Your columns (optional)</Label><Input id={`${spec.key}-c`} className="w-72" placeholder="Date, Party, Invoice, Amount" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>}
        {spec.extra === "question" && <div className="min-w-64 flex-1 space-y-1"><Label htmlFor={`${spec.key}-q`}>Question</Label><Input id={`${spec.key}-q`} placeholder="Total amount by party, top 5" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>}
        {spec.extra === "tolerance" && <div className="space-y-1"><Label htmlFor={`${spec.key}-t`}>Equal within (₹)</Label><Input id={`${spec.key}-t`} className="w-24" inputMode="decimal" value={extra} onChange={(e) => setExtra(e.target.value)} /></div>}
        {spec.extra === "standardise_names" && <label className="flex h-10 items-center gap-2 text-sm"><input type="checkbox" checked={extra === "true"} onChange={(e) => setExtra(String(e.target.checked))} />
          Use one spelling for similar party names</label>}
        <Button type="submit" disabled={pending || !ready}>{pending ? "Working…" : spec.button}</Button>
        {spec.sample && <Button type="button" variant="secondary" disabled={pending} onClick={() => go(() => caTool(`${spec.path}/sample`, null, clientId), open)}>Try the sample</Button>}
      </div>
      <Err e={err} />
    </form>
  );
}

/** The upload hub: many files or a zip for one client; each file recognised, filed, ticked and its agent run. */
export function HubForm({ clientId }: { clientId: string }) {
  const { err, pending, go, router } = useGo();
  const [files, setFiles] = useState<File[]>([]);
  const open = (d: unknown) => { const id = workId(d); if (id) router.push(`/ca-work/${id}`); };
  return (
    <form className="space-y-2" onSubmit={(e) => {
      e.preventDefault();
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      go(() => caTool(`/org/ca/clients/${clientId}/hub`, fd, clientId), open);
    }}>
      <p className="text-sm text-muted">Everything the client sent, at once (up to 40 files or a zip, 100 MB). Each file is recognised, filed, ticked off the
        checklist, and the right agent run: bank statements classified, broker P&amp;L to capital gains, TDS registers checked, registers and day books
        scanned for anomalies, a GSTR-2B with the purchase register reconciled, Form 16 / AIS read, notices answered.</p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label htmlFor="hub-files">Files or a zip</Label>
          <input id="hub-files" type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.csv,.xlsx,.json,.txt,.zip" className="block text-sm"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))} /></div>
        <Button type="submit" disabled={pending || !files.length}>{pending ? "Working…" : files.length > 1 ? `Take ${files.length} files` : "Take it"}</Button>
        <Button type="button" variant="secondary" disabled={pending} onClick={() => go(() => caTool(`/org/ca/clients/${clientId}/hub/sample`, null, clientId), open)}>Try a sample zip</Button>
      </div>
      <Err e={err} />
    </form>
  );
}

type Field = Record<string, string>;
export function ItrForm({ clientId, fields, inputs, from }: { clientId: string; fields: Field; inputs: Record<string, number>; from: { documents: number; capital_gains: boolean } }) {
  const { err, pending, go, router } = useGo();
  const [v, setV] = useState<Record<string, string>>(Object.fromEntries(Object.keys(fields).map((k) => [k, inputs[k] ? String(inputs[k]) : ""])));
  const [age, setAge] = useState("below60");
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go(() => caItr(clientId, { age, inputs: Object.fromEntries(Object.entries(v).filter(([, x]) => x !== "").map(([k, x]) => [k, Number(x.replace(/,/g, ""))])) }),
      (d) => router.push(`/ca-work/${workId(d)}`)); }}>
      <p className="text-sm text-muted">{from.documents ? `Filled in from ${from.documents} tax document${from.documents === 1 ? "" : "s"}` : "No tax documents read yet: type the figures"}
        {from.capital_gains ? " and the latest capital gains computation" : ""}. Check every figure; both regimes are worked out.</p>
      <div className="flex items-end gap-2"><div className="space-y-1"><Label htmlFor="age">Age</Label><Select id="age" value={age} onChange={(e) => setAge(e.target.value)}>
        <option value="below60">Below 60</option><option value="60to80">60 to 80</option><option value="above80">Above 80</option></Select></div></div>
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(fields).map(([k, label]) => (
          <div key={k} className="space-y-0.5"><Label htmlFor={`itr-${k}`} className="text-xs">{label}</Label>
            <Input id={`itr-${k}`} inputMode="decimal" className={`h-9 ${inputs[k] ? "border-ink" : ""}`} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></div>))}
      </div>
      <Button type="submit" disabled={pending}>{pending ? "Computing…" : "Compute both regimes"}</Button><Err e={err} />
    </form>
  );
}

export function BankLineCategory({ wid, row, category, categories }: { wid: string; row: number; category: string; categories: string[] }) {
  const { err, pending, go } = useGo();
  const [learn, setLearn] = useState(true);
  return (
    <span className="flex items-center gap-1.5">
      <Select aria-label="Category" className="h-8 w-48 text-xs" value={category} disabled={pending}
        onChange={(e) => go(() => caBankLine(wid, { row, category: e.target.value, learn }))}>{categories.map((c) => <option key={c}>{c}</option>)}</Select>
      <label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />learn</label>
      <Err e={err} />
    </span>
  );
}

/** Place (or move) a trial-balance ledger in a Schedule III line; "learn" keeps it for the firm's later trial balances. */
export function LedgerLine({ wid, ledger, line, lines }: { wid: string; ledger: string; line: string | null; lines: [string, string][] }) {
  const { err, pending, go } = useGo();
  const [learn, setLearn] = useState(true);
  return (
    <span className="flex items-center gap-1.5">
      <Select aria-label={`Line for ${ledger}`} className="h-8 w-56 text-xs" value={line ?? ""} disabled={pending}
        onChange={(e) => e.target.value && go(() => caLedgerLine(wid, { ledger, line: e.target.value, learn }))}>
        {!line && <option value="">Not placed: choose…</option>}{lines.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
      <label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />learn</label>
      <Err e={err} />
    </span>
  );
}

/** Last year's closing tax WDV by block (from the tax computation): the blocks and deferred tax are worked out again. */
export function TaxOpening({ wid, blocks }: { wid: string; blocks: { key: string; label: string; opening: number; opening_from: string }[] }) {
  const { err, pending, go } = useGo();
  const [v, setV] = useState<Record<string, string>>(Object.fromEntries(blocks.map((b) => [b.key, String(b.opening)])));
  const num = (k: string) => Number((v[k] ?? "").replace(/,/g, ""));
  const changed = blocks.filter((b) => (v[b.key] ?? "").trim() !== "" && num(b.key) !== b.opening);
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      go(() => caTaxOpening(wid, Object.fromEntries(changed.map((b) => [b.key, num(b.key)]))));
    }}>
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">{blocks.map((b) => (
        <div key={b.key} className="space-y-0.5"><Label htmlFor={`op-${b.key}`} className="text-xs">{b.label} <span className="text-muted">({b.opening_from})</span></Label>
          <Input id={`op-${b.key}`} inputMode="decimal" className="h-9" value={v[b.key] ?? ""} onChange={(e) => setV({ ...v, [b.key]: e.target.value })} /></div>))}</div>
      <Button type="submit" disabled={pending || !changed.length || changed.some((b) => !Number.isFinite(num(b.key)) || num(b.key) < 0)}>
        {pending ? "Working out…" : "Use these opening figures"}</Button><Err e={err} />
    </form>
  );
}

/** Send the drafted confirmation requests, or reminders to parties who haven't replied in a week. */
export function ConfirmSend({ wid, drafts, remind }: { wid: string; drafts: number; remind: number }) {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  const [byHand, setByHand] = useState<{ party: string; subject: string; body: string }[]>([]);
  const done = (d: unknown) => {
    const r = d as { sent: number; failed: unknown[]; messages: { party: string; via: string; subject?: string; body?: string }[] };
    setByHand(r.messages.filter((m) => m.via === "recorded" && m.body).map((m) => ({ party: m.party, subject: m.subject ?? "", body: m.body ?? "" })));
    const recorded = r.messages.filter((m) => m.via === "recorded").length;
    setMsg(`${r.sent} sent${recorded ? ` (${recorded} recorded only: no mailbox connected, or a test address; copy the text below to send by hand)` : ""}${r.failed.length ? `, ${r.failed.length} failed` : ""}.`);
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" disabled={pending || !drafts} onClick={() => confirm(`Email ${drafts} confirmation request${drafts === 1 ? "" : "s"} from the firm's mailbox?`) && go(() => caConfirmSend(wid, false), done)}>
        {pending ? "Sending…" : `Send ${drafts} request${drafts === 1 ? "" : "s"}`}</Button>
      {remind > 0 && <Button type="button" variant="secondary" disabled={pending} onClick={() => confirm(`Send ${remind} reminder${remind === 1 ? "" : "s"}?`) && go(() => caConfirmSend(wid, true), done)}>
        Remind {remind} (no reply in a week)</Button>}
      {msg && <span className="text-sm text-muted">{msg}</span>}<Err e={err} />
      {byHand.length > 0 && <details className="w-full rounded-xl border-2 border-line p-3 text-sm"><summary className="cursor-pointer font-semibold">To send by hand ({byHand.length})</summary>
        <ul className="mt-2 space-y-3">{byHand.map((m) => <li key={m.party}><p className="font-medium">{m.party}: {m.subject} <CopyText text={`${m.subject}\n\n${m.body}`} /></p>
          <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-paper p-2 text-xs">{m.body}</pre></li>)}</ul>
        <p className="mt-2 text-xs text-muted">Each link is private to that party; it works for 60 days.</p></details>}
    </div>
  );
}

/** One party: paste their email reply (read for you), set the result by hand, or add an email address. */
export function ConfirmParty({ wid, pid, status, email }: { wid: string; pid: string; status: string; email: string | null }) {
  const { err, pending, go } = useGo();
  const [mode, setMode] = useState<"" | "reply" | "set" | "email">("");
  const [txt, setTxt] = useState("");
  const [res, setRes] = useState("agreed");
  const [fig, setFig] = useState("");
  const close = () => { setMode(""); setTxt(""); setFig(""); };
  if (!mode) return (
    <span className="flex flex-wrap gap-2 text-xs">
      {["sent", "unclear", "differs", "agreed"].includes(status) && <button type="button" className="underline" onClick={() => setMode("reply")}>paste reply</button>}
      {status !== "not_selected" && status !== "draft" && status !== "no_email" && <button type="button" className="underline" onClick={() => setMode("set")}>set result</button>}
      {(status === "no_email" || status === "not_selected" || status === "draft") && <button type="button" className="underline" onClick={() => setMode("email")}>{email ? "change email" : "add email"}</button>}
    </span>);
  return (
    <form className="min-w-64 space-y-1.5" onSubmit={(e) => {
      e.preventDefault();
      if (mode === "reply") go(() => caConfirmReply(wid, pid, txt), close);
      else if (mode === "email") go(() => caConfirmSet(wid, pid, { email: txt }), close);
      else go(() => caConfirmSet(wid, pid, { status: res, their_balance: res === "differs" ? Number(fig.replace(/,/g, "")) : null, note: txt || null }), close);
    }}>
      {mode === "reply" && <textarea aria-label="The party's reply" className="w-full rounded-lg border-2 border-line p-2 text-xs" rows={3} value={txt} onChange={(e) => setTxt(e.target.value)} placeholder="Paste the email reply" />}
      {mode === "email" && <Input aria-label="Email" className="h-8 text-xs" value={txt} onChange={(e) => setTxt(e.target.value)} placeholder="accounts@party.com" />}
      {mode === "set" && <div className="flex flex-wrap gap-1.5">
        <Select aria-label="Result" className="h-8 w-28 text-xs" value={res} onChange={(e) => setRes(e.target.value)}><option value="agreed">Agreed</option><option value="differs">Differs</option><option value="unclear">Unclear</option></Select>
        {res === "differs" && <Input aria-label="Their balance" className="h-8 w-28 text-xs" inputMode="decimal" placeholder="Their figure" value={fig} onChange={(e) => setFig(e.target.value)} />}
        <Input aria-label="Note" className="h-8 w-40 text-xs" placeholder="Note (letter, call…)" value={txt} onChange={(e) => setTxt(e.target.value)} /></div>}
      <span className="flex gap-2"><Button type="submit" className="h-8 text-xs" disabled={pending || (mode !== "set" && txt.trim().length < 2) || (mode === "set" && res === "differs" && !Number.isFinite(Number(fig.replace(/,/g, ""))) )}>
        {pending ? "Saving…" : mode === "reply" ? "Read it" : "Save"}</Button><button type="button" className="text-xs underline" onClick={close}>cancel</button></span>
      <Err e={err} />
    </form>
  );
}

export function DeleteWork({ wid, clientId }: { wid: string; clientId?: string }) {
  const { err, pending, go, router } = useGo();
  return <><button type="button" className="text-sm text-muted underline" disabled={pending}
    onClick={() => confirm("Delete this result?") && go(() => caDeleteWork(wid, clientId), () => router.push(clientId ? `/ca-clients/${clientId}` : "/excel"))}>Delete</button><Err e={err} /></>;
}

export function CopyText({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return <button type="button" className="text-xs underline" onClick={() => { void navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}>{done ? "copied" : "copy"}</button>;
}

export type Recurring = { id: string; name: string; vendor: string; category: string; amount: number; gst_rate: number; frequency: string; next_on: string;
  ends_on: string | null; active: boolean; booked: number };

export function RecurringForm({ entry, categories }: { entry?: Recurring; categories: string[] }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ name: entry?.name ?? "", vendor: entry?.vendor ?? "", category: entry?.category ?? categories[0] ?? "Rent", amount: String(entry?.amount ?? ""),
    gst_rate: String(entry?.gst_rate ?? 0), frequency: entry?.frequency ?? "monthly", next_on: entry?.next_on ?? "", ends_on: entry?.ends_on ?? "", active: entry?.active ?? true });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => caSaveRecurring({ ...f, amount: Number(f.amount), gst_rate: Number(f.gst_rate), ends_on: f.ends_on || null }, entry?.id),
      () => { if (!entry) setF({ ...f, name: "", vendor: "", amount: "" }); }); }}>
      <div className="space-y-1"><Label htmlFor="rn">What</Label><Input id="rn" required value={f.name} onChange={set("name")} placeholder="Office rent" /></div>
      <div className="space-y-1"><Label htmlFor="rv">Paid to</Label><Input id="rv" required value={f.vendor} onChange={set("vendor")} placeholder="Sunrise Properties" /></div>
      <div className="space-y-1"><Label htmlFor="rc">Category</Label><Select id="rc" value={f.category} onChange={set("category")}>{categories.map((c) => <option key={c}>{c}</option>)}</Select></div>
      <div className="space-y-1"><Label htmlFor="ra">Amount (₹, before GST)</Label><Input id="ra" required className="w-32" inputMode="decimal" value={f.amount} onChange={set("amount")} /></div>
      <div className="space-y-1"><Label htmlFor="rg">GST %</Label><Select id="rg" value={f.gst_rate} onChange={set("gst_rate")}>{["0", "5", "12", "18", "28"].map((g) => <option key={g}>{g}</option>)}</Select></div>
      <div className="space-y-1"><Label htmlFor="rf">Every</Label><Select id="rf" value={f.frequency} onChange={set("frequency")}>
        <option value="weekly">week</option><option value="monthly">month</option><option value="quarterly">quarter</option><option value="yearly">year</option></Select></div>
      <div className="space-y-1"><Label htmlFor="rx">Next on</Label><Input id="rx" required type="date" value={f.next_on} onChange={set("next_on")} /></div>
      <div className="space-y-1"><Label htmlFor="re">Ends (optional)</Label><Input id="re" type="date" value={f.ends_on} onChange={set("ends_on")} /></div>
      {entry && <label className="flex items-center gap-1.5 pb-2 text-sm"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />active</label>}
      <Button type="submit" disabled={pending}>{pending ? "Saving…" : entry ? "Save" : "Add"}</Button>
      {entry && <button type="button" className="pb-2 text-sm text-muted underline" disabled={pending} onClick={() => confirm(`Delete ${entry.name}? Entries already booked stay in the books.`) && go(() => caDeleteRecurring(entry.id))}>delete</button>}
      <Err e={err} />
    </form>
  );
}

export function BookNow() {
  const { err, pending, go } = useGo();
  const [msg, setMsg] = useState<string | null>(null);
  return <span className="flex items-center gap-2"><Button variant="secondary" disabled={pending} onClick={() => go(() => caBookRecurring(), (d) => setMsg(`${(d as { booked: number }).booked} booked`))}>
    {pending ? "Booking…" : "Book what's due now"}</Button>{msg && <span className="text-sm">{msg}</span>}<Err e={err} /></span>;
}
