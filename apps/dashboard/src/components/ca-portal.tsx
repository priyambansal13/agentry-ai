"use client";

import { Badge, Button, Input, Label } from "@agentry/ui";
import { Check, Copy, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { caPortalLink, caPortalRevoke, caPortalSettings } from "@/app/(app)/actions";

/** CA client portal (backend automations/ca/portal.py): the firm's settings and each client's private link. */
export type PortalSettings = { enabled: boolean; title: string; color: string; logo_url: string | null; welcome: string; firm: string };
export type PortalLink = { created_at: string; expires_at: string; last_used_at: string | null; uses: number } | null;

function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => { const r = await f(); if (!r.ok) return setErr(r.error ?? "failed"); after?.(r.data); router.refresh(); });
  };
  return { err, pending, go };
}

const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export function PortalSettingsForm({ s, canEdit }: { s: PortalSettings; canEdit: boolean }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ enabled: s.enabled, title: s.title, color: s.color, logo_url: s.logo_url ?? "", welcome: s.welcome });
  const [saved, setSaved] = useState(false);
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go(() => caPortalSettings({ ...f, logo_url: f.logo_url || undefined }), () => { setSaved(true); setTimeout(() => setSaved(false), 1500); }); }}>
      <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" disabled={!canEdit} checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} className="h-4 w-4" />
        Give clients a private portal: their filings, what&apos;s still needed, due dates, and document uploads</label>
      <div className="grid gap-3 sm:grid-cols-[1fr_9rem_1fr]">
        <div className="space-y-1"><Label htmlFor="pt-t">Portal name</Label><Input id="pt-t" disabled={!canEdit} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="pt-c">Colour</Label><Input id="pt-c" type="color" disabled={!canEdit} value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} className="h-11 p-1" /></div>
        <div className="space-y-1"><Label htmlFor="pt-l">Logo (https address)</Label><Input id="pt-l" disabled={!canEdit} value={f.logo_url} onChange={(e) => setF({ ...f, logo_url: e.target.value })} placeholder="https://yourfirm.in/logo.png" /></div>
      </div>
      <div className="space-y-1"><Label htmlFor="pt-w">Welcome line</Label><Input id="pt-w" disabled={!canEdit} value={f.welcome} onChange={(e) => setF({ ...f, welcome: e.target.value })} /></div>
      {canEdit && <div className="flex items-center gap-3"><Button type="submit" disabled={pending}>{pending ? "Saving…" : "Save"}</Button>
        {saved && <span className="text-sm text-success">Saved</span>}{err && <span role="alert" className="text-sm text-danger">{err}</span>}</div>}
      <p className="text-xs text-muted">Clients see your name and colours; each client who uses it in a month is billed as a portal client on your statement.</p>
    </form>
  );
}

export function ClientPortalCard({ cid, link, settings, canWork }: { cid: string; link: PortalLink; settings: PortalSettings; canWork: boolean }) {
  const { err, pending, go } = useGo();
  const [url, setUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  if (!settings.enabled) return <p className="text-sm text-muted">The client portal is off. Switch it on in <a href="/ca-clients" className="underline">Clients → Client portal</a>.</p>;
  return (
    <div className="space-y-3 text-sm">
      <p>{link ? <>Link active until {day(link.expires_at)} · {link.last_used_at ? <>last opened {day(link.last_used_at)} <Badge tone="success">in use</Badge></> : "not opened yet"}</> : "No link yet."}</p>
      {canWork && <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={pending} onClick={() => go(() => caPortalLink(cid, true), (d) => {
          const r = d as { url: string; sent?: string; channel?: string }; setUrl(r.url);
          setMsg(r.sent === "sent" ? `Sent on ${r.channel}.` : "Couldn't send it automatically: copy the link and send it yourself.");
        })}><Send aria-hidden="true" className="mr-1 h-4 w-4" />{link ? "Send a new link" : "Send the link"}</Button>
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => go(() => caPortalLink(cid, false), (d) => { setUrl((d as { url: string }).url); setMsg("A new link: the old one stops working."); })}>Get a link to copy</Button>
        {link && <Button size="sm" variant="secondary" disabled={pending} onClick={() => { if (confirm("Stop this client's link?")) go(() => caPortalRevoke(cid), () => { setUrl(null); setMsg("Stopped."); }); }}>Stop the link</Button>}
      </div>}
      {url && <div className="flex flex-wrap items-center gap-2"><code className="min-w-0 flex-1 break-all rounded-lg bg-paper px-2 py-1 text-xs">{url}</code>
        <Button size="sm" variant="secondary" onClick={() => { void navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check aria-hidden="true" className="h-4 w-4" /> : <Copy aria-hidden="true" className="h-4 w-4" />}</Button></div>}
      {msg && <p className="text-muted">{msg}</p>}{err && <p role="alert" className="text-danger">{err}</p>}
    </div>
  );
}
