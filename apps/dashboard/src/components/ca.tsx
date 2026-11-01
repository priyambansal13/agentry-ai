"use client";

import { Badge, Button, Input, Label, Select } from "@agentry/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import {
  caAddFiling, caChecklist, caDeleteClient, caDeleteFile, caDeleteFiling, caEditFiling, caImportClients, caPauseChase, caReadFile,
  caRebuildChecklist, caRefreshCalendar, caSaveClient, caSeason, caTrySamples, caUploadFile,
} from "@/app/(app)/actions";
import { day } from "@/lib/ca";

/** CA Firm pack (docs/PACKS.md): the firm's clients, the filing board, documents and the compliance calendar. */
export type CaMeta = { enabled: string[]; statuses: { key: string; label: string }[]; kinds: Record<string, string>; client_kinds: string[];
  profile_flags: Record<string, string>; items: Record<string, string>; team: { id: string; name: string; email: string; role: string }[];
  me: string; can_work: boolean };
export type CaClient = { id: string; name: string; kind: string; pan: string | null; gstin: string | null; phone: string | null; email: string | null;
  profile: Record<string, boolean>; assignee: string | null; notes?: string | null; open_filings?: number; files?: number };
export type Filing = { id: string; client_id: string; client: string; pan: string | null; kind: string; period: string; title: string; due_on: string | null;
  status: string; assignee: string | null; ack_no: string | null; filed_on: string | null; notes: string | null; source: string; missing: string[];
  overdue: boolean; files: number; checklist?: { key: string; label: string; status: string; file_ids: string[] }[]; chase?: { sent?: number; last_at?: string; paused?: boolean } };


function useRun() {
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
  return { err, pending, go, setErr };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);
const box = "h-4 w-4 accent-[var(--ink)]";

export function ClientForm({ meta, client, onDone }: { meta: CaMeta; client?: CaClient; onDone?: () => void }) {
  const [f, setF] = useState({ name: client?.name ?? "", kind: client?.kind ?? "individual", pan: client?.pan ?? "", gstin: client?.gstin ?? "",
    phone: client?.phone ?? "", email: client?.email ?? "", assignee: client?.assignee ?? "", notes: client?.notes ?? "" });
  const [profile, setProfile] = useState<Record<string, boolean>>(client?.profile ?? {});
  const { err, pending, go } = useRun();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go(() => caSaveClient({ ...f, assignee: f.assignee || null, profile }, client?.id),
      () => { if (!client) setF({ ...f, name: "", pan: "", phone: "", email: "", gstin: "" }); onDone?.(); }); }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1 sm:col-span-2"><Label htmlFor="cn">Name</Label><Input id="cn" required minLength={2} value={f.name} onChange={set("name")} placeholder="Priya Sharma" /></div>
        <div className="space-y-1"><Label htmlFor="ck">Type</Label><Select id="ck" value={f.kind} onChange={set("kind")}>
          {meta.client_kinds.map((k) => <option key={k} value={k}>{k === "huf" ? "HUF" : k === "llp" ? "LLP" : k[0]!.toUpperCase() + k.slice(1)}</option>)}</Select></div>
        <div className="space-y-1"><Label htmlFor="cp">PAN</Label><Input id="cp" value={f.pan} maxLength={10} onChange={(e) => setF({ ...f, pan: e.target.value.toUpperCase() })} placeholder="ABCPS1234K" /></div>
        <div className="space-y-1"><Label htmlFor="cw">WhatsApp / mobile</Label><Input id="cw" value={f.phone} onChange={set("phone")} placeholder="+91 98100 00011" /></div>
        <div className="space-y-1"><Label htmlFor="ce">Email</Label><Input id="ce" type="email" value={f.email} onChange={set("email")} /></div>
        <div className="space-y-1"><Label htmlFor="cg">GSTIN</Label><Input id="cg" value={f.gstin} maxLength={15} onChange={(e) => setF({ ...f, gstin: e.target.value.toUpperCase() })} /></div>
        <div className="space-y-1"><Label htmlFor="ca">Looked after by</Label><Select id="ca" value={f.assignee} onChange={set("assignee")}>
          <option value="">Nobody yet</option>{meta.team.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></div>
      </div>
      <fieldset><legend className="mb-1 text-sm font-semibold">What applies to them <span className="font-normal text-muted">(checklists and due dates follow this)</span></legend>
        <div className="grid gap-1.5 sm:grid-cols-3">
          {Object.entries(meta.profile_flags).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={!!profile[k]}
              onChange={(e) => setProfile({ ...profile, [k]: e.target.checked })} />{label}</label>))}
        </div></fieldset>
      <Err e={err} />
      <Button type="submit" disabled={pending}>{pending ? "Saving…" : client ? "Save client" : "Add client"}</Button>
    </form>
  );
}

export function ImportClients() {
  const { err, pending, go } = useRun();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted">A CSV or Excel file with a header row: Name, PAN, Mobile, Email, GSTIN, Type. Rows with a PAN that&apos;s already here update that client.</p>
      <input type="file" accept=".csv,.xlsx" disabled={pending} className="text-sm" onChange={(e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file);
        go(() => caImportClients(fd), (d) => {
          const r = d as { added: number; updated: number; errors: string[] };
          setMsg(`${r.added} added, ${r.updated} updated${r.errors.length ? `; ${r.errors.length} rows skipped: ${r.errors.slice(0, 3).join("; ")}` : ""}`);
        });
      }} />
      {msg && <p className="text-sm">{msg}</p>}<Err e={err} />
    </div>
  );
}

export function DeleteClient({ id, name }: { id: string; name: string }) {
  const router = useRouter();
  const { err, pending, go } = useRun();
  return <><Button variant="secondary" disabled={pending} onClick={() => {
    if (confirm(`Delete ${name}, their filings and every file they sent? This can't be undone.`)) go(() => caDeleteClient(id), () => router.push("/ca-clients"));
  }}>Delete client</Button><Err e={err} /></>;
}

export function NewFiling({ meta, clients, clientId }: { meta: CaMeta; clients?: { id: string; name: string }[]; clientId?: string }) {
  const [f, setF] = useState({ client_id: clientId ?? "", kind: "itr", period: "AY 2026-27", due_on: "", assignee: "" });
  const { err, pending, go } = useRun();
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => caAddFiling({ ...f, due_on: f.due_on || null, assignee: f.assignee || null })); }}>
      {!clientId && <div className="space-y-1"><Label htmlFor="fc">Client</Label><Select id="fc" required value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}>
        <option value="">Choose…</option>{clients?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></div>}
      <div className="space-y-1"><Label htmlFor="fk">Filing</Label><Select id="fk" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
        {Object.entries(meta.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
      <div className="space-y-1"><Label htmlFor="fp">Period</Label><Input id="fp" required className="w-36" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} /></div>
      <div className="space-y-1"><Label htmlFor="fd">Due</Label><Input id="fd" type="date" value={f.due_on} onChange={(e) => setF({ ...f, due_on: e.target.value })} /></div>
      <div className="space-y-1"><Label htmlFor="fa">Owner</Label><Select id="fa" value={f.assignee} onChange={(e) => setF({ ...f, assignee: e.target.value })}>
        <option value="">Client&apos;s owner</option>{meta.team.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></div>
      <Button type="submit" disabled={pending}>{pending ? "Adding…" : "Add filing"}</Button><Err e={err} />
    </form>
  );
}

export function StartSeason({ meta }: { meta: CaMeta }) {
  const [f, setF] = useState({ kind: "itr", period: "AY 2026-27", due_on: "2026-07-31", client_kinds: ["individual", "huf"], flag: "" });
  const { err, pending, go } = useRun();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go(() => caSeason({ ...f, due_on: f.due_on || null, flag: f.flag || null }),
      (d) => { const r = d as { created: number; already_there: number }; setMsg(`${r.created} cards created${r.already_there ? `, ${r.already_there} were already there` : ""}.`); }); }}>
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label htmlFor="sk">Filing</Label><Select id="sk" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {Object.entries(meta.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
        <div className="space-y-1"><Label htmlFor="sp">Period</Label><Input id="sp" className="w-36" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="sd">Due</Label><Input id="sd" type="date" value={f.due_on} onChange={(e) => setF({ ...f, due_on: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="sf">Only clients who</Label><Select id="sf" value={f.flag} onChange={(e) => setF({ ...f, flag: e.target.value })}>
          <option value="">(anyone)</option>{Object.entries(meta.profile_flags).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
      </div>
      <div className="flex flex-wrap gap-3 text-sm">{meta.client_kinds.map((k) => (
        <label key={k} className="flex items-center gap-1.5"><input type="checkbox" className={box} checked={f.client_kinds.includes(k)}
          onChange={() => setF({ ...f, client_kinds: f.client_kinds.includes(k) ? f.client_kinds.filter((x) => x !== k) : [...f.client_kinds, k] })} />{k}</label>))}</div>
      <Button type="submit" disabled={pending || !f.client_kinds.length}>{pending ? "Creating…" : "Create a card for each client"}</Button>
      {msg && <p className="text-sm">{msg}</p>}<Err e={err} />
    </form>
  );
}

export function FilingControls({ f, meta, clientId }: { f: Filing; meta: CaMeta; clientId?: string }) {
  const { err, pending, go } = useRun();
  const [ack, setAck] = useState(f.ack_no ?? "");
  if (!meta.can_work) return null;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Select aria-label="Status" className="h-8 w-auto text-sm" value={f.status} disabled={pending}
          onChange={(e) => go(() => caEditFiling(f.id, { status: e.target.value }, clientId))}>
          {meta.statuses.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
        <Select aria-label="Owner" className="h-8 w-auto text-sm" value={f.assignee ?? ""} disabled={pending}
          onChange={(e) => go(() => caEditFiling(f.id, { assignee: e.target.value || null }, clientId))}>
          <option value="">No owner</option>{meta.team.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
        {["filed", "verified", "review"].includes(f.status) && (
          <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); go(() => caEditFiling(f.id, { ack_no: ack || null }, clientId)); }}>
            <Input aria-label="Acknowledgement number" className="h-8 w-40 text-sm" placeholder="Ack. number" value={ack} onChange={(e) => setAck(e.target.value)} />
            <Button size="sm" variant="secondary" disabled={pending}>Save</Button></form>)}
        <button type="button" className="text-xs text-muted underline" disabled={pending}
          onClick={() => confirm(`Delete ${f.title} for ${f.client}?`) && go(() => caDeleteFiling(f.id, clientId))}>delete</button>
      </div>
      <Err e={err} />
    </div>
  );
}

export function Checklist({ f, clientId, canWork }: { f: Filing; clientId: string; canWork: boolean }) {
  const { err, pending, go } = useRun();
  const [label, setLabel] = useState("");
  const items = f.checklist ?? [];
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {items.map((i) => (
          <li key={i.key} className="flex flex-wrap items-center gap-2 text-sm">
            <input type="checkbox" className={box} disabled={!canWork || pending} checked={i.status === "received"}
              onChange={(e) => go(() => caChecklist(f.id, { key: i.key, status: e.target.checked ? "received" : "missing" }, clientId))} />
            <span className={i.status === "not_needed" ? "text-muted line-through" : ""}>{i.label}</span>
            {i.file_ids.length > 0 && i.file_ids.map((id, n) => <a key={id} href={`/api/ca/files/${id}`} className="text-xs underline">file {n + 1}</a>)}
            {canWork && i.status === "missing" && <button type="button" className="text-xs text-muted underline" disabled={pending}
              onClick={() => go(() => caChecklist(f.id, { key: i.key, status: "not_needed" }, clientId))}>not needed</button>}
          </li>))}
      </ul>
      {canWork && <div className="flex flex-wrap items-center gap-2">
        <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (label.trim()) go(() => caChecklist(f.id,
          { key: `custom_${Date.now()}`, status: "missing", label }, clientId), () => setLabel("")); }}>
          <Input aria-label="Add a document" className="h-8 w-56 text-sm" placeholder="Add a document to ask for" value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button size="sm" variant="secondary" disabled={pending}>Add</Button></form>
        <button type="button" className="text-xs underline" disabled={pending} onClick={() => go(() => caRebuildChecklist(f.id, clientId))}>rebuild from profile</button>
        <button type="button" className="text-xs underline" disabled={pending} onClick={() => go(() => caPauseChase(f.id, !f.chase?.paused, clientId))}>
          {f.chase?.paused ? "resume reminders" : "pause reminders"}</button>
        <span className="text-xs text-muted">{f.chase?.sent ? `${f.chase.sent} reminder${f.chase.sent === 1 ? "" : "s"} sent` : "no reminders yet"}</span>
      </div>}
      <Err e={err} />
    </div>
  );
}

export function UploadFile({ clientId, filings, reader }: { clientId: string; filings: Filing[]; reader: boolean }) {
  const { err, pending, go } = useRun();
  const [filing, setFiling] = useState("");
  const [docType, setDocType] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label htmlFor="uf">For</Label><Select id="uf" value={filing} onChange={(e) => setFiling(e.target.value)}>
          <option value="">Any open filing (matched automatically)</option>{filings.map((f) => <option key={f.id} value={f.id}>{f.title}</option>)}</Select></div>
        {reader && <div className="space-y-1"><Label htmlFor="ut">It is</Label><Select id="ut" value={docType} onChange={(e) => setDocType(e.target.value)}>
          <option value="">(work it out)</option><option value="form16">Form 16</option><option value="ais">AIS</option><option value="tis">TIS</option>
          <option value="26as">Form 26AS</option><option value="form16a">Form 16A</option></Select></div>}
        <input type="file" disabled={pending} className="text-sm" accept=".pdf,.jpg,.jpeg,.png,.webp,.csv,.xlsx,.json,.txt" onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          const fd = new FormData();
          fd.append("file", file);
          if (filing) fd.append("filing_id", filing);
          if (docType) fd.append("doc_type", docType);
          go(() => caUploadFile(clientId, fd), (d) => {
            const r = d as { label?: string; item?: string | null; still_missing?: string[] };
            setMsg(r.item ? `Filed as: ${r.label}.${r.still_missing?.length ? ` Still missing: ${r.still_missing.join(", ")}` : " Nothing missing now."}` : "Saved.");
          });
          e.target.value = "";
        }} />
      </div>
      {pending && <p className="text-sm text-muted">Reading the file…</p>}
      {msg && <p className="text-sm">{msg}</p>}<Err e={err} />
    </div>
  );
}

export function FileActions({ id, clientId, canRead, read }: { id: string; clientId: string; canRead: boolean; read: boolean }) {
  const { err, pending, go } = useRun();
  return (
    <span className="flex items-center gap-2 text-xs">
      <a href={`/api/ca/files/${id}`} className="underline">download</a>
      {canRead && <button type="button" className="underline" disabled={pending} onClick={() => go(() => caReadFile(id, clientId))}>{pending ? "reading…" : read ? "read again" : "read"}</button>}
      <button type="button" className="text-muted underline" disabled={pending} onClick={() => confirm("Delete this file?") && go(() => caDeleteFile(id, clientId))}>delete</button>
      <Err e={err} />
    </span>
  );
}

export function TrySamples({ clientId }: { clientId: string }) {
  const { err, pending, go } = useRun();
  return <><Button variant="secondary" disabled={pending} onClick={() => go(() => caTrySamples(clientId))}>{pending ? "Reading…" : "Try a sample Form 16 + AIS"}</Button><Err e={err} /></>;
}

export function RefreshCalendar() {
  const { err, pending, go } = useRun();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="flex items-center gap-2">
      <Button variant="secondary" disabled={pending} onClick={() => go(() => caRefreshCalendar(), (d) => setMsg(`${(d as { created: number }).created} new due dates on the board`))}>
        {pending ? "Checking…" : "Check due dates now"}</Button>
      {msg && <span className="text-sm">{msg}</span>}<Err e={err} />
    </span>
  );
}

export function BoardCard({ f, meta, who }: { f: Filing; meta: CaMeta; who: Record<string, string> }) {
  return (
    <li className={`space-y-1.5 rounded-xl border-2 bg-card p-3 ${f.overdue ? "border-danger" : "border-line"}`}>
      <div className="flex items-start justify-between gap-2">
        <Link href={`/ca-clients/${f.client_id}`} className="font-semibold hover:underline">{f.client}</Link>
        {f.overdue && <Badge tone="danger">overdue</Badge>}
      </div>
      <p className="text-sm">{f.title}{f.due_on && <span className="text-muted"> · due {day(f.due_on)}</span>}</p>
      {f.missing.length > 0 && <p className="text-xs text-warning">Waiting for: {f.missing.slice(0, 3).join(", ")}{f.missing.length > 3 ? ` +${f.missing.length - 3}` : ""}</p>}
      {f.ack_no && <p className="text-xs text-muted">Ack. {f.ack_no}</p>}
      <p className="text-xs text-muted">{f.assignee ? who[f.assignee] ?? "someone" : "no owner"}{f.files ? ` · ${f.files} file${f.files === 1 ? "" : "s"}` : ""}</p>
      <FilingControls f={f} meta={meta} />
    </li>
  );
}
