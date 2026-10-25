"use client";

import { Badge, Button, Input, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { hqAssignPhone, hqInvite, hqSwitchAutomation, hqUnassignPhone, openClientPortal } from "@/app/(app)/actions";
import type { CatalogItem } from "@/components/new-client-form";
import { statusLabels } from "@/lib/format";

export function AutomationSwitches({ orgId, catalog, current }: { orgId: string; catalog: CatalogItem[]; current: { template_key: string; status: string }[] }) {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const status = Object.fromEntries(current.map((a) => [a.template_key, a.status]));
  return (
    <div className="space-y-2">
      <ul className="divide-y divide-line">
        {catalog.map((c) => {
          const on = c.key in status;
          return (
            <li key={c.key} className="flex items-center justify-between gap-3 py-2.5">
              <div className={!c.available && !on ? "opacity-50" : ""}>
                <span className="font-medium">{c.name}</span>
                {on && <Badge className="ml-2" tone={statusLabels[status[c.key]!]?.tone ?? "neutral"}>{statusLabels[status[c.key]!]?.label ?? status[c.key]}</Badge>}
                {!c.available && <Badge className="ml-2">coming soon</Badge>}
                {c.note && <p className="text-xs text-muted">{c.note}</p>}
              </div>
              <button type="button" role="switch" aria-checked={on} aria-label={`${c.name} ${on ? "on" : "off"}`}
                disabled={pending || (!c.available && !on)}
                onClick={() => {
                  if (on && !confirm(`Switch off ${c.name}? It stops working and its sections disappear for the client. Its history is kept.`)) return;
                  start(async () => {
                    const r = await hqSwitchAutomation(orgId, c.key, !on);
                    setErr(r.ok ? null : r.error);
                    router.refresh();
                  });
                }}
                className={`relative h-6 w-11 shrink-0 rounded-full border-2 border-ink transition-colors disabled:opacity-40 ${on ? "bg-lime" : "bg-card"}`}>
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-ink transition-all ${on ? "left-5" : "left-0.5"}`} />
              </button>
            </li>
          );
        })}
      </ul>
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      <p className="text-xs text-muted">Switching one on for a live client starts it in approval mode: nothing is sent without a person approving it.</p>
    </div>
  );
}

export function OpenPortal({ orgId, to = "/home", label = "Open their portal", primary = false }: { orgId: string; to?: string; label?: string; primary?: boolean }) {
  const [pending, start] = useTransition();
  return <Button variant={primary ? "primary" : "secondary"} disabled={pending} onClick={() => start(() => openClientPortal(orgId, to))}>{label}</Button>;
}

const ROLES = [["owner", "Owner"], ["manager", "Manager"], ["staff", "Front desk"], ["finance", "Finance"], ["viewer", "Viewer"]];

export function InviteMember({ orgId, orgName }: { orgId: string; orgName: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("owner");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await hqInvite(orgId, orgName, email, role, name);
      setMsg(r.ok ? { ok: true, text: r.data === "added" ? `${email} already had a login and was added.` : `Invitation sent to ${email}.` } : { ok: false, text: r.error });
      if (r.ok) { setEmail(""); setName(""); router.refresh(); }
    }); }}>
      <Input aria-label="Name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} className="w-40" />
      <Input aria-label="Email" type="email" required placeholder="name@business.com" value={email} onChange={(e) => setEmail(e.target.value)} className="min-w-56 flex-1" />
      <Select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} className="w-36">{ROLES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
      <Button type="submit" variant="secondary" disabled={pending}>Invite</Button>
      {msg && <p role="status" className={`w-full text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </form>
  );
}

export type PhoneNumber = { id: string; number: string; locality: string | null; status: string; client: { org_id: string; name: string } | null };

export function PhoneAssign({ orgId, numbers }: { orgId: string; numbers: PhoneNumber[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const mine = numbers.filter((n) => n.client?.org_id === orgId);
  const free = numbers.filter((n) => !n.client);
  const [pick, setPick] = useState(free[0]?.number ?? "");
  const run = (fn: () => Promise<{ ok: boolean; error?: string }>) => start(async () => {
    const r = await fn();
    setErr(r.ok ? null : r.error ?? "Something went wrong");
    router.refresh();
  });
  return (
    <div className="space-y-3 text-sm">
      {mine.map((n) => (
        <div key={n.id} className="flex flex-wrap items-center gap-2">
          <span className="font-mono font-semibold">{n.number}</span>
          <Badge tone="success">answering calls</Badge>
          {n.locality && <span className="text-muted">{n.locality}</span>}
          <Button variant="secondary" size="sm" className="ml-auto" disabled={pending}
            onClick={() => confirm(`Stop answering ${n.number} for this client?`) && run(() => hqUnassignPhone(orgId, n.number))}>Unassign</Button>
        </div>
      ))}
      {mine.length === 0 && (free.length ? (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); run(() => hqAssignPhone(orgId, pick)); }}>
          <Select aria-label="Phone number" value={pick} onChange={(e) => setPick(e.target.value)} className="w-56">
            {free.map((n) => <option key={n.id} value={n.number}>{n.number}{n.locality ? ` · ${n.locality}` : ""}</option>)}
          </Select>
          <Button type="submit" disabled={pending || !pick}>Assign</Button>
        </form>
      ) : <p className="text-muted">No free numbers: rent one in LiveKit Cloud → Telephony → Phone numbers.</p>)}
      {err && <p role="alert" className="text-danger">{err}</p>}
    </div>
  );
}
