"use client";

import { Badge, Button, Card, Input, Select } from "@agentry/ui";
import { useState, useTransition } from "react";
import { teamCancelInvite, teamChangeRole, teamInvite, teamRemove } from "@/app/(app)/actions";
import type { PendingInvite, TeamMember } from "@/lib/clients";

export const ROLE_INFO: [key: string, label: string, does: string][] = [
  ["owner", "Owner", "Everything: settings, connections, team, billing. Gets urgent alerts and the daily digest."],
  ["manager", "Manager", "Day-to-day work and settings. Gets urgent alerts and the digest. No team or billing."],
  ["staff", "Front desk", "Reads conversations and approves or edits replies. Can turn on alerts for themselves."],
  ["finance", "Finance", "Billing, statements and invoices. No access to emails or chats."],
  ["viewer", "Viewer", "Sees the dashboard and reports only."],
];
const label = (r: string) => r.split(",").map((x) => ROLE_INFO.find(([k]) => k === x.trim())?.[1] ?? x).join(", ");

export function TeamManager({ members, invitations, me, canInvite, canChange, canRemove, canCancel }: {
  members: TeamMember[]; invitations: PendingInvite[]; me: string;
  canInvite: boolean; canChange: boolean; canRemove: boolean; canCancel: boolean;
}) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const [form, setForm] = useState({ name: "", email: "", role: "staff" });
  const run = (fn: () => Promise<{ ok: boolean; error?: string }>, done: string) => start(async () => {
    const r = await fn();
    setMsg(r.ok ? { ok: true, text: done } : { ok: false, text: r.error ?? "Something went wrong" });
  });

  return (
    <div className="space-y-6">
      {canInvite && (
        <Card className="p-5">
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => {
            const r = await teamInvite(form.email, form.name, form.role);
            if (r.ok) setForm({ name: "", email: "", role: form.role });
            return r;
          }, `Invitation sent to ${form.email}`); }}>
            <Input aria-label="Name" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-44" />
            <Input aria-label="Email" type="email" required placeholder="name@business.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="min-w-56 flex-1" />
            <Select aria-label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-40">
              {ROLE_INFO.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
            <Button type="submit" disabled={pending}>Invite</Button>
          </form>
          <p className="mt-2 text-xs text-muted">{ROLE_INFO.find(([k]) => k === form.role)?.[2]} They sign in with an emailed link, no password needed.</p>
        </Card>
      )}
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted">
            <tr><th className="px-5 py-3 font-medium">Name</th><th className="px-5 py-3 font-medium">Email</th><th className="px-5 py-3 font-medium">Role</th>
              {(canChange || canRemove || canCancel) && <th className="px-5 py-3" />}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {members.map((m) => (
              <tr key={m.id}>
                <td className="px-5 py-3 font-medium">{m.name || "—"}{m.email === me && <span className="ml-2 text-xs text-muted">(you)</span>}</td>
                <td className="px-5 py-3 text-muted">{m.email}</td>
                <td className="px-5 py-3">
                  {canChange && m.email !== me ? (
                    <Select aria-label={`Role for ${m.email}`} value={m.role} disabled={pending} className="w-40"
                      onChange={(e) => run(() => teamChangeRole(m.id, e.target.value), `${m.email} is now ${label(e.target.value)}`)}>
                      {ROLE_INFO.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      {!ROLE_INFO.some(([k]) => k === m.role) && <option value={m.role}>{label(m.role)}</option>}
                    </Select>
                  ) : <Badge tone={m.role.includes("owner") ? "lime" : "neutral"}>{label(m.role)}</Badge>}
                </td>
                {(canChange || canRemove || canCancel) && <td className="px-5 py-3 text-right">
                  {canRemove && m.email !== me && <button type="button" disabled={pending} className="text-sm text-danger hover:underline"
                    onClick={() => confirm(`Remove ${m.email}? They lose access immediately.`) && run(() => teamRemove(m.id), `${m.email} was removed`)}>Remove</button>}
                </td>}
              </tr>
            ))}
            {invitations.map((i) => (
              <tr key={i.id}>
                <td className="px-5 py-3 italic text-muted">Invited</td>
                <td className="px-5 py-3 text-muted">{i.email}</td>
                <td className="px-5 py-3"><Badge>{label(i.role)} · pending</Badge></td>
                {(canChange || canRemove || canCancel) && <td className="px-5 py-3 text-right">
                  {canCancel && <button type="button" disabled={pending} className="text-sm text-muted hover:text-ink hover:underline"
                    onClick={() => run(() => teamCancelInvite(i.id), `Invitation to ${i.email} cancelled`)}>Cancel invite</button>}
                </td>}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card className="p-5">
        <p className="text-sm font-semibold">What each role can do</p>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{ROLE_INFO.map(([k, l, d]) => (
          <div key={k}><dt className="font-medium">{l}</dt><dd className="text-muted">{d}</dd></div>))}</dl>
      </Card>
    </div>
  );
}
