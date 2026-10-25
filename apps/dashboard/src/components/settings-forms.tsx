"use client";

import { Button, Input, Label, PasswordInput } from "@agentry/ui";
import { useState, useTransition } from "react";
import { savePassword, saveNotificationPrefs, saveWhatsAppNumber } from "@/app/(app)/actions";

const LABELS: Record<string, string> = { urgent: "Urgent emails, and chats or WhatsApps that need a person",
  escalation: "Urgent emails still unanswered after the set time (a second alert)", digest: "Daily inbox digest",
  weekly: "Monday summary of last week (emails sorted, urgent caught, time saved)",
                                         billing: "New statements from Agentry", reports: "Monthly results report (2nd of each month)" };

export function WhatsAppNumberForm({ number }: { number: string | null }) {
  const [v, setV] = useState(number ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="mb-5 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await saveWhatsAppNumber(v.trim());
      setMsg(r.ok ? { ok: true, text: r.data.whatsapp_to ? `Saved: ${r.data.whatsapp_to}` : "Removed" } : { ok: false, text: r.error });
    }); }}>
      <div className="space-y-1"><Label htmlFor="wa-to">Your WhatsApp number for alerts</Label>
        <Input id="wa-to" inputMode="tel" placeholder="98765 43210" value={v} onChange={(e) => setV(e.target.value)} className="w-56" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>Save number</Button>
      {msg && <span role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
    </form>
  );
}

export function NotificationPrefs({ prefs, channels }: { prefs: Record<string, string[]>; channels: string[] }) {
  const [p, setP] = useState(prefs);
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const toggle = (k: string, c: string) => setP((x) => ({ ...x, [k]: x[k]?.includes(c) ? x[k]!.filter((y) => y !== c) : [...(x[k] ?? []), c] }));
  return (
    <form onSubmit={(e) => { e.preventDefault(); start(async () => { const r = await saveNotificationPrefs(p); setMsg(r.ok ? "Saved" : r.error); }); }}>
      <table className="w-full text-sm">
        <thead className="text-muted"><tr><th className="pb-2 text-left font-medium">Tell me about</th>{channels.map((c) => <th key={c} className="pb-2 font-medium capitalize">{c}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{Object.keys(prefs).filter((k) => LABELS[k]).map((k) => (
          <tr key={k}><td className="py-2.5">{LABELS[k]}</td>{channels.map((c) => (
            <td key={c} className="text-center"><input type="checkbox" aria-label={`${LABELS[k]} by ${c}`} className="h-4 w-4 accent-[var(--ink)]"
              checked={p[k]?.includes(c) ?? false} onChange={() => toggle(k, c)} /></td>
          ))}</tr>
        ))}</tbody>
      </table>
      <div className="mt-4 flex items-center gap-3"><Button type="submit" disabled={pending}>Save</Button>{msg && <span role="status" className="text-sm text-success">{msg}</span>}</div>
    </form>
  );
}

export function PasswordForm({ hasPassword }: { hasPassword: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const has = hasPassword;
  return (
    <form className="max-w-md space-y-3" onSubmit={(e) => {
      e.preventDefault();
      if (next !== again) return setMsg({ ok: false, text: "The two new passwords don't match" });
      start(async () => {
        const r = await savePassword(next, has ? current : undefined);
        if (!r.ok) return setMsg({ ok: false, text: r.error });
        // saving renews the session cookie, which re-renders the page: carry the confirmation in the URL
        window.location.replace(`/settings/account?saved=${has ? "password-changed" : "password-set"}`);
      });
    }}>
      {!has && <p className="text-sm text-muted">You sign in with emailed links. Add a password if you'd like to sign in without checking your email.</p>}
      {has && <div className="space-y-1"><Label htmlFor="pw-cur">Current password</Label>
        <PasswordInput id="pw-cur" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></div>}
      <div className="space-y-1"><Label htmlFor="pw-new">New password</Label>
        <PasswordInput id="pw-new" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></div>
      <div className="space-y-1"><Label htmlFor="pw-again">New password again</Label>
        <PasswordInput id="pw-again" autoComplete="new-password" required minLength={10} value={again} onChange={(e) => setAgain(e.target.value)} /></div>
      <p className="text-xs text-muted">At least 10 characters.</p>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending}>{has ? "Change password" : "Set password"}</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </form>
  );
}
