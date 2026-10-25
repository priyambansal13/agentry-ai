"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addLeadSource, importOldLeads, startReactivation } from "@/app/(app)/actions";

export function OldLeadsImport() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      const r = await importOldLeads(fd);
      if (!r.ok) return setMsg({ ok: false, text: r.error });
      const d = r.data as { leads_created: number; leads_updated: number; opted_out: number; contacts_merged: number; eligible_now: number };
      setMsg({ ok: true, text: `${d.leads_created} new, ${d.leads_updated} updated, ${d.contacts_merged} duplicates merged, ${d.opted_out} opted out · ${d.eligible_now} can be contacted now` });
      router.refresh();
    }); }}>
      <div><Label htmlFor="ol-file">Upload old leads (CSV or Excel: name, phone, email, last_interest, consent)</Label>
        <input id="ol-file" type="file" accept=".csv,.xlsx" className="block text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
      <Button type="submit" variant="secondary" disabled={!file || pending}>Upload</Button>
      {msg && <p role="status" className={`w-full text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </form>
  );
}

export function StartCampaign({ eligible }: { eligible: number }) {
  const router = useRouter();
  const [name, setName] = useState("Checking in");
  const [perHour, setPerHour] = useState(20);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const hours = eligible / perHour;
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault();
      if (!confirm(`Start messaging ${eligible} people, ${perHour} per hour?`)) return;
      start(async () => {
        const r = await startReactivation(name, perHour);
        setMsg(r.ok ? { ok: true, text: `Started: ${r.data.enrolled} people, finishing around ${new Date(r.data.finishes_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}` } : { ok: false, text: r.error });
        router.refresh();
      });
    }}>
      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <div><Label htmlFor="c-name">Campaign name</Label><Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></div>
        <div><Label htmlFor="c-rate">Messages per hour</Label><Input id="c-rate" type="number" min={1} max={200} value={perHour} onChange={(e) => setPerHour(Number(e.target.value))} /></div>
      </div>
      <p className="text-sm text-muted">One by one, never a blast: {eligible} people over about {hours < 1 ? `${Math.ceil(hours * 60)} minutes` : `${hours.toFixed(1)} hours`}. Anyone who replies is handed to your assistant and drops out of the campaign.</p>
      <Button type="submit" disabled={pending || eligible === 0}>Start campaign</Button>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </form>
  );
}

export function AddLeadForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => { await addLeadSource(name); setName(""); router.refresh(); }); }}>
      <div><Label htmlFor="ls-name">New lead form</Label><Input id="ls-name" placeholder="e.g. Meta ads (via Zapier)" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></div>
      <Button type="submit" variant="secondary" disabled={pending}>Create link</Button>
    </form>
  );
}
