"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { importInvoices, invoiceReminders, invoiceStatus, recordPayment } from "@/app/(app)/actions";

type Preview = { ok: boolean; rows?: number; valid?: number; issues?: string[]; mapping?: Record<string, string>; mapped_by?: string;
                 missing?: string[]; created?: number; updated?: number; reminders_started?: number; contacts_merged?: number };

export function InvoiceImport() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const send = (commit: boolean) => start(async () => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("commit", String(commit));
    const r = await importInvoices(fd);
    if (!r.ok) return setError(r.error);
    setError(null);
    setPreview(r.data as Preview);
    if (commit) router.refresh();
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label htmlFor="inv-file">Import invoices (CSV or Excel: Google Sheet, Tally, QuickBooks, Zoho exports)</Label>
          <input ref={input} id="inv-file" type="file" accept=".csv,.xlsx" className="block text-sm"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
        </div>
        <Button variant="secondary" disabled={!file || pending} onClick={() => send(false)}>Preview</Button>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {preview && (
        <div className="rounded-xl border border-line bg-paper p-4 text-sm">
          {preview.ok === false ? (
            <p className="text-danger">Couldn&apos;t find these columns: {preview.missing?.join(", ")}</p>
          ) : preview.created !== undefined ? (
            <p className="text-success">✓ {preview.created} new, {preview.updated} updated · reminders started for {preview.reminders_started} · {preview.contacts_merged} duplicate contacts merged</p>
          ) : (
            <>
              <p><strong>{preview.valid}</strong> of {preview.rows} rows ready (columns matched by {preview.mapped_by}).</p>
              <p className="mt-1 text-muted">{Object.entries(preview.mapping ?? {}).map(([k, v]) => `${k} ← "${v}"`).join(" · ")}</p>
              {preview.issues && preview.issues.length > 0 && <p className="mt-1 text-warning">{preview.issues.slice(0, 3).join("; ")}</p>}
              <Button className="mt-3" disabled={pending} onClick={() => send(true)}>Import {preview.valid} invoices</Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function InvoiceActions({ id, balance, reminders, status }: { id: string; balance: number; reminders: string | null; status?: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState(String(balance));
  const [ref, setRef] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {reminders === "active" && <Button size="sm" variant="ghost" disabled={pending} onClick={() => start(async () => { await invoiceReminders(id, "pause"); router.refresh(); })}>Pause</Button>}
      {reminders === "paused" && <Button size="sm" variant="ghost" disabled={pending} onClick={() => start(async () => { await invoiceReminders(id, "resume"); router.refresh(); })}>Resume</Button>}
      {balance > 0 && <Button size="sm" variant="secondary" onClick={() => setOpen((v) => !v)}>Paid?</Button>}
      {status === "disputed" && <>
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => start(async () => {
          const r = await invoiceStatus(id, "reopen"); setMsg(r.ok ? "Reopened: reminders start again" : r.error); router.refresh(); })}>Dispute resolved: reopen</Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => confirm("Write this invoice off? Reminders stop for good.") && start(async () => {
          const r = await invoiceStatus(id, "write_off"); setMsg(r.ok ? "Written off" : r.error); router.refresh(); })}>Write off</Button>
      </>}
      {["open", "partially_paid", "disputed"].includes(status ?? "") && balance > 0 && (
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => confirm("Void this invoice (sent by mistake)? Reminders stop.") && start(async () => {
          const r = await invoiceStatus(id, "void"); setMsg(r.ok ? "Voided" : r.error); router.refresh(); })}>Void</Button>
      )}
      {open && (
        <form className="mt-2 flex w-full flex-wrap justify-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
          const r = await recordPayment(id, Number(amount), ref);
          setMsg(r.ok ? "Recorded; reminders stop" : r.error);
          if (r.ok) { setOpen(false); router.refresh(); }
        }); }}>
          <Input aria-label="Amount" className="h-9 w-28" type="number" min={1} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Input aria-label="Reference (UTR, cheque no.)" className="h-9 w-44" placeholder="UTR / cheque no." required value={ref} onChange={(e) => setRef(e.target.value)} />
          <Button size="sm" type="submit" disabled={pending}>Record payment</Button>
        </form>
      )}
      {msg && <span className="w-full text-right text-xs text-muted">{msg}</span>}
    </div>
  );
}
