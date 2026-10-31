"use client";

import { Badge, Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { openClientPortal, reviewDocument, trySampleDocuments, uploadDocument } from "@/app/(app)/actions";
import { authClient } from "@/lib/auth-client";

type Msg = { ok: boolean; text: string } | null;
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;
const READ_AS: Record<string, string> = { ready: "Filed", needs_review: "Read, but needs a check", rejected: "Already received: not filed twice", failed: "Couldn't read it" };

/** Upload photos or PDFs of receipts (several at once), or try the three samples. */
export function AddDocuments({ empty }: { empty: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  function send(files: FileList | null) {
    if (!files?.length) return;
    start(async () => {
      const out: string[] = [];
      for (const [i, f] of [...files].entries()) {
        setMsg({ ok: true, text: `Reading ${i + 1} of ${files.length}…` });
        const fd = new FormData();
        fd.append("file", f);
        const r = await uploadDocument(fd);
        out.push(r.ok ? `${f.name}: ${READ_AS[r.data.status] ?? r.data.status}` : `${f.name}: ${r.error}`);
      }
      setMsg({ ok: true, text: out.join(" · ") });
      router.refresh();
    });
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <label className={`inline-flex h-10 cursor-pointer items-center rounded-xl border-2 border-ink bg-lime px-4 text-sm font-semibold ${pending ? "opacity-60" : ""}`}>
          Upload receipts or bills
          <input type="file" className="sr-only" accept="image/jpeg,image/png,image/webp,application/pdf" multiple disabled={pending}
                 onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
        </label>
        {empty && (
          <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
            setMsg({ ok: true, text: "Reading three sample receipts…" });
            const r = await trySampleDocuments();
            setMsg(r.ok ? { ok: true, text: "Done: two filed, one needs a check." } : { ok: false, text: r.error });
            router.refresh();
          })}>Try 3 sample receipts</Button>
        )}
      </div>
      <p className="text-xs text-muted">Photos (JPG, PNG, WEBP) or PDFs, up to 10 MB each. Staff can also send them to your WhatsApp or Telegram.</p>
      <Status msg={msg} />
    </div>
  );
}

type Field = { value: string | number | null; confidence: number; checked?: boolean };
type Spec = { name: string; type: string; required: boolean };
const LABEL: Record<string, string> = { vendor_gstin: "Vendor GSTIN", cgst: "CGST", sgst: "SGST", igst: "IGST", bill_number: "Bill number",
  payment_method: "Paid by" };
const label = (n: string) => LABEL[n] ?? n.charAt(0).toUpperCase() + n.slice(1).replace(/_/g, " ");

/** Every field with how sure the reading was; fix any, then Accept (files it) or Reject. */
export function ReviewDocument({ id, fields, specs, categories, threshold, canAct, status, flagged }: {
  id: string; fields: Record<string, Field>; specs: Spec[]; categories: string[]; threshold: number; canAct: boolean; status: string; flagged: string[];
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  const [vals, setVals] = useState<Record<string, string>>(Object.fromEntries(specs.map((s) => [s.name, fields[s.name]?.value == null ? "" : String(fields[s.name]?.value)])));
  const changed = () => Object.fromEntries(specs.filter((s) => vals[s.name] !== (fields[s.name]?.value == null ? "" : String(fields[s.name]?.value)))
    .map((s) => [s.name, vals[s.name] === "" ? null : vals[s.name]]));
  const act = (action: "accept" | "reject") => start(async () => {
    const r = await reviewDocument(id, action, action === "accept" ? changed() : undefined);
    setMsg(r.ok ? { ok: true, text: action === "accept" ? "Filed." : "Rejected." } : { ok: false, text: r.error });
    if (r.ok) router.refresh();
  });
  const editable = canAct && ["needs_review", "ready"].includes(status);
  return (
    <form onSubmit={(e) => { e.preventDefault(); act("accept"); }} className="space-y-3">
      {specs.map((s) => {
        const f = fields[s.name];
        const unsure = !f?.checked && (f?.confidence ?? 0) < threshold && (s.required || f?.value != null);
        return (
          <div key={s.name} className={`grid items-center gap-2 sm:grid-cols-[9rem_1fr_6rem] ${unsure || flagged.includes(s.name) ? "rounded-lg bg-warning/10 p-1" : ""}`}>
            <Label htmlFor={`f-${s.name}`}>{label(s.name)}{s.required ? " *" : ""}</Label>
            {s.name === "category" ? (
              <Select id={`f-${s.name}`} value={vals[s.name]} disabled={!editable} onChange={(e) => setVals({ ...vals, [s.name]: e.target.value })}>
                <option value="">—</option>
                {[...new Set([...categories, vals[s.name]].filter(Boolean))].map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            ) : (
              <Input id={`f-${s.name}`} value={vals[s.name]} disabled={!editable} type={s.type === "date" ? "date" : "text"}
                     inputMode={s.type === "money" ? "decimal" : undefined} onChange={(e) => setVals({ ...vals, [s.name]: e.target.value })} />
            )}
            <span className="text-xs text-muted">
              {f?.checked ? <Badge tone="success">checked</Badge> : f?.value == null && !s.required ? "—" : <Badge tone={unsure ? "warning" : "neutral"}>{Math.round((f?.confidence ?? 0) * 100)}% sure</Badge>}
            </span>
          </div>
        );
      })}
      {editable && (
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button type="submit" disabled={pending}>{status === "ready" ? "Save changes" : "Accept and file"}</Button>
          <Button type="button" variant="ghost" disabled={pending} onClick={() => act("reject")}>Reject</Button>
          <Status msg={msg} />
        </div>
      )}
    </form>
  );
}

/** Open one client's books: members switch their active business; Agentry staff open the client's portal (audited). */
export function OpenClientBooks({ id, staff }: { id: string; staff: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button size="sm" variant="secondary" disabled={pending} onClick={() => start(async () => {
      if (staff) { await openClientPortal(id, "/bookkeeping"); return; }
      await authClient.organization.setActive({ organizationId: id });
      router.push("/bookkeeping");
      router.refresh();
    })}>Open</Button>
  );
}
