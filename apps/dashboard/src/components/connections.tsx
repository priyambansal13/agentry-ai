"use client";

import { Badge, Button, Card, Input, Label } from "@agentry/ui";
import { Mail, MessageCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { connectWhatsApp, disconnect, setAlertTemplate, setInboxRouting, startGmail, startOutlook, syncGmail, syncOutlook, testWhatsApp } from "@/app/(app)/actions";
import { timeAgo } from "@/lib/format";

export type Connection = {
  id: string; provider: "gmail" | "whatsapp" | "outlook" | "razorpay" | "stripe" | "phone"; account_ref: string; display_name: string | null;
  status: "connected" | "error"; last_sync_at: string | null; last_error: string | null; created_at: string;
  assign_to?: string | null; baseline_minutes?: number | null;
};

function Msg({ m }: { m: { ok: boolean; text: string } | null }) {
  return m ? <p role="status" className={`text-sm ${m.ok ? "text-success" : "text-danger"}`}>{m.text}</p> : null;
}

function Status({ c }: { c: Connection }) {
  return c.status === "connected"
    ? <Badge tone="success">Connected</Badge>
    : <Badge tone="danger">Needs attention</Badge>;
}

export function GmailCard({ conn, available, canManage }: { conn?: Connection; available: boolean; canManage: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <Card className="p-6">
      <div className="flex items-start gap-4">
        <Mail className="mt-1 h-6 w-6 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><h2 className="font-display text-xl font-bold">Gmail</h2>{conn && <Status c={conn} />}</div>
          <p className="mt-1 text-sm text-muted">Inbox triage reads new mail, adds Agentry labels and writes reply drafts in the thread. Replies are only sent when you approve them. Nothing is ever deleted.</p>
          {conn ? (
            <div className="mt-4 space-y-1 text-sm">
              <p><span className="text-muted">Account:</span> <strong>{conn.account_ref}</strong></p>
              <p><span className="text-muted">Last checked:</span> {conn.last_sync_at ? timeAgo(conn.last_sync_at) : "not yet"}</p>
              {conn.last_error && <p className="text-danger">{conn.last_error}</p>}
            </div>
          ) : !available ? (
            <p className="mt-4 text-sm text-warning">Gmail isn&apos;t enabled on this Agentry server yet. Ask your account manager.</p>
          ) : null}
          {canManage && (
            <div className="mt-5 flex flex-wrap gap-2">
              {!conn && available && (
                <Button disabled={pending} onClick={() => start(async () => {
                  const r = await startGmail();
                  if (r.ok) window.location.href = r.data.url; else setMsg({ ok: false, text: r.error });
                })}>Connect Gmail</Button>
              )}
              {conn && (
                <>
                  <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
                    const r = await syncGmail();
                    setMsg(r.ok ? { ok: true, text: `Checked now: ${r.data.new_emails} new email${r.data.new_emails === 1 ? "" : "s"}` } : { ok: false, text: r.error });
                    router.refresh();
                  })}>Check for new mail now</Button>
                  {conn.status !== "connected" && available && (
                    <Button disabled={pending} onClick={() => start(async () => { const r = await startGmail(); if (r.ok) window.location.href = r.data.url; })}>Reconnect</Button>
                  )}
                  <Button variant="ghost" disabled={pending} onClick={() => confirm("Disconnect Gmail? Triage stops reading this inbox.") && start(async () => {
                    const r = await disconnect(conn.id);
                    setMsg(r.ok ? { ok: true, text: "Disconnected" } : { ok: false, text: r.error });
                    router.refresh();
                  })}>Disconnect</Button>
                </>
              )}
            </div>
          )}
          <div className="mt-3"><Msg m={msg} /></div>
        </div>
      </div>
    </Card>
  );
}

/** Several Gmail inboxes per client (#16): each syncs on its own, replies go out from the inbox the email came to,
 *  and each can send its cards to one person (e.g. accounts@ → finance). */
export function GmailInboxes({ conns, available, canManage, people }: { conns: Connection[]; available: boolean; canManage: boolean;
                                                                       people: { id: string; name: string }[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (conns.length === 0) return <GmailCard available={available} canManage={canManage} />;
  return (
    <div className="space-y-3">
      {conns.map((c) => (
        <div key={c.id} className="space-y-2">
          <GmailCard conn={c} available={available} canManage={canManage} />
          {canManage && people.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-2 text-sm">
              <label htmlFor={`route-${c.id}`} className="text-muted">Cards from {c.account_ref} go to</label>
              <select id={`route-${c.id}`} className="h-9 rounded-lg border-2 border-line bg-card px-2" defaultValue={c.assign_to ?? ""} disabled={pending}
                onChange={(e) => start(async () => {
                  const r = await setInboxRouting(c.id, e.target.value || null);
                  setMsg(r.ok ? { ok: true, text: "Routing saved" } : { ok: false, text: r.error });
                  router.refresh();
                })}>
                <option value="">Anyone (no one in particular)</option>
                {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}
        </div>
      ))}
      {canManage && available && (
        <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
          const r = await startGmail();
          if (r.ok) window.location.href = r.data.url; else setMsg({ ok: false, text: r.error });
        })}>+ Connect another Gmail inbox (e.g. accounts@, sales@)</Button>
      )}
      <Msg m={msg} />
    </div>
  );
}

/** Outlook / Microsoft 365 inboxes (#6): the same job as Gmail. */
export function OutlookInboxes({ conns, available, canManage }: { conns: Connection[]; available: boolean; canManage: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const connect = () => start(async () => { const r = await startOutlook(); if (r.ok) window.location.href = r.data.url; else setMsg({ ok: false, text: r.error }); });
  return (
    <Card className="p-6">
      <div className="flex items-start gap-4">
        <Mail className="mt-1 h-6 w-6 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-xl font-bold">Outlook / Microsoft 365</h2>
          <p className="mt-1 text-sm text-muted">For businesses on Outlook instead of Gmail: the same sorting, categories, alerts and reply drafts. Some company accounts need their Microsoft 365 admin to approve Agentry once.</p>
          {conns.map((c) => (
            <div key={c.id} className="mt-4 space-y-1 text-sm">
              <p className="flex flex-wrap items-center gap-2"><strong>{c.account_ref}</strong><Status c={c} /></p>
              <p className="text-muted">Last checked: {c.last_sync_at ? timeAgo(c.last_sync_at) : "not yet"}</p>
              {c.last_error && <p className="text-danger">{c.last_error}</p>}
              {canManage && <Button size="sm" variant="ghost" disabled={pending} onClick={() => confirm(`Disconnect ${c.account_ref}?`) && start(async () => {
                const r = await disconnect(c.id); setMsg(r.ok ? { ok: true, text: "Disconnected" } : { ok: false, text: r.error }); router.refresh();
              })}>Disconnect</Button>}
            </div>
          ))}
          {!available && <p className="mt-4 text-sm text-warning">Outlook isn&apos;t enabled on this Agentry server yet. Ask your account manager.</p>}
          {canManage && available && (
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant={conns.length ? "secondary" : "primary"} disabled={pending} onClick={connect}>{conns.length ? "+ Connect another Outlook inbox" : "Connect Outlook"}</Button>
              {conns.length > 0 && <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
                const r = await syncOutlook();
                setMsg(r.ok ? { ok: true, text: `Checked now: ${r.data.new_emails} new email${r.data.new_emails === 1 ? "" : "s"}` } : { ok: false, text: r.error });
                router.refresh();
              })}>Check for new mail now</Button>}
            </div>
          )}
          <div className="mt-3"><Msg m={msg} /></div>
        </div>
      </div>
    </Card>
  );
}

export function AlertTemplateForm({ conn }: { conn: Connection & { alert_template?: string | null } }) {
  const [t, setT] = useState(conn.alert_template ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4 text-sm" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await setAlertTemplate(conn.id, t.trim(), "en");
      setMsg(r.ok ? { ok: true, text: t ? "Alerts can now go to WhatsApp" : "WhatsApp alerts off" } : { ok: false, text: r.error });
    }); }}>
      <div className="space-y-1"><Label htmlFor={`tpl-${conn.id}`}>Alert template (approved in Meta, body: {"{{1}}"} then {"{{2}}"})</Label>
        <Input id={`tpl-${conn.id}`} value={t} onChange={(e) => setT(e.target.value)} placeholder="agentry_alert" className="w-64" /></div>
      <Button type="submit" size="sm" variant="secondary" disabled={pending}>Save</Button>
      <Msg m={msg} />
    </form>
  );
}

export function WhatsAppCard({ conn, available, canManage }: { conn?: Connection; available: boolean; canManage: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState({ phone_number_id: "", waba_id: "", access_token: "" });
  const [to, setTo] = useState("");
  return (
    <Card className="p-6">
      <div className="flex items-start gap-4">
        <MessageCircle className="mt-1 h-6 w-6 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><h2 className="font-display text-xl font-bold">WhatsApp</h2>{conn && <Status c={conn} />}</div>
          <p className="mt-1 text-sm text-muted">Your AI assistant answers customers on your WhatsApp Business number, books appointments and hands over to you when needed. It starts in approval mode.</p>
          {!available && <p className="mt-4 text-sm text-warning">WhatsApp isn&apos;t enabled on this Agentry server yet. Ask your account manager.</p>}
          {conn ? (
            <div className="mt-4 space-y-3 text-sm">
              <p><span className="text-muted">Number:</span> <strong>{conn.display_name ?? conn.account_ref}</strong></p>
              {conn.last_error && <p className="text-danger">{conn.last_error}</p>}
              {canManage && (
                <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
                  const r = await testWhatsApp(to);
                  setMsg(r.ok ? { ok: true, text: `Test message sent to ${to}` } : { ok: false, text: r.error });
                }); }}>
                  <div><Label htmlFor="wa-to">Send a test message to</Label><Input id="wa-to" value={to} onChange={(e) => setTo(e.target.value)} placeholder="+91 90000 00000" /></div>
                  <Button type="submit" variant="secondary" disabled={pending || !to}>Send test</Button>
                  <Button type="button" variant="ghost" disabled={pending} onClick={() => confirm("Disconnect WhatsApp?") && start(async () => { await disconnect(conn.id); router.refresh(); })}>Disconnect</Button>
                </form>
              )}
            </div>
          ) : available && canManage ? (
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
              const r = await connectWhatsApp(form.phone_number_id.trim(), form.waba_id.trim(), form.access_token.trim());
              setMsg(r.ok ? { ok: true, text: `Connected ${r.data.display} (${r.data.verified_name})` } : { ok: false, text: r.error });
              if (r.ok) router.refresh();
            }); }}>
              <div><Label htmlFor="wa-pn">Phone number ID</Label><Input id="wa-pn" inputMode="numeric" required value={form.phone_number_id} onChange={(e) => setForm({ ...form, phone_number_id: e.target.value })} /></div>
              <div><Label htmlFor="wa-waba">WhatsApp Business Account ID</Label><Input id="wa-waba" inputMode="numeric" required value={form.waba_id} onChange={(e) => setForm({ ...form, waba_id: e.target.value })} /></div>
              <div className="sm:col-span-2"><Label htmlFor="wa-tok">Access token</Label><Input id="wa-tok" type="password" autoComplete="off" required value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} />
                <p className="mt-1 text-xs text-muted">Stored encrypted; never shown again. Your account manager usually does this step.</p></div>
              <div className="sm:col-span-2"><Button type="submit" disabled={pending}>{pending ? "Checking with Meta…" : "Connect WhatsApp"}</Button></div>
            </form>
          ) : null}
          <div className="mt-3"><Msg m={msg} /></div>
        </div>
      </div>
    </Card>
  );
}
