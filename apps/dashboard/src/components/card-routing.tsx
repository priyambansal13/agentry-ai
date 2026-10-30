"use client";

import { Badge, Button, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { type RoutingRule, setCardRouting } from "@/app/(app)/actions";
import type { Assignee } from "@/components/approval-card";

type Msg = { ok: boolean; text: string } | null;

function done(r: Awaited<ReturnType<typeof setCardRouting>>, who: string | null): Msg {
  if (!r.ok) return { ok: false, text: r.error };
  const n = r.data.cards_assigned;
  return { ok: true, text: who ? `Saved${n ? `: ${n} waiting card${n === 1 ? "" : "s"} now with ${who}` : ""}` : "Rule removed" };
}

/** On an agent's page: who gets every card this agent creates (unless a client rule or a manual assignment says otherwise). */
export function AgentRouting({ automationKey, people, current }: { automationKey: string; people: Assignee[]; current: string | null }) {
  const router = useRouter();
  const [value, setValue] = useState(current ?? "");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <div className="space-y-2">
      <Label htmlFor={`route-${automationKey}`}>New cards go to</Label>
      <div className="flex flex-wrap gap-2">
        <Select id={`route-${automationKey}`} className="max-w-xs" value={value} disabled={pending} onChange={(e) => {
          const v = e.target.value;
          setValue(v);
          start(async () => {
            const r = await setCardRouting("automation", automationKey, v || null);
            setMsg(done(r, people.find((p) => p.id === v)?.name ?? null));
            router.refresh();
          });
        }}>
          <option value="">Anyone (not assigned)</option>
          {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
        </Select>
      </div>
      <p className="text-xs text-muted">They see these cards under Needs you → Mine. A rule for a specific client, or assigning a card by hand, comes first.</p>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </div>
  );
}

/** On the Invoices page: one person handles everything for a client (reminder cards, disputes, replies). */
export function ClientRouting({ clients, people, rules }: { clients: { id: string; name: string }[]; people: Assignee[]; rules: RoutingRule[] }) {
  const router = useRouter();
  const [client, setClient] = useState("");
  const [person, setPerson] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const mine = rules.filter((r) => r.scope === "contact");
  function save(key: string, who: string | null) {
    start(async () => {
      const r = await setCardRouting("contact", key, who);
      setMsg(done(r, people.find((p) => p.id === who)?.name ?? null));
      if (r.ok) { setClient(""); setPerson(""); }
      router.refresh();
    });
  }
  return (
    <div className="space-y-3">
      {mine.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {mine.map((r) => (
            <li key={r.key}>
              <Badge tone="lime">{r.contact_name ?? "Client"} → {r.assign_name ?? "?"}{r.resources.length === 1 ? ` (${r.resources[0]}s only)` : ""}
                <button type="button" aria-label={`Remove the rule for ${r.contact_name ?? "this client"}`} className="ml-1 hover:text-danger"
                  disabled={pending} onClick={() => save(r.key, null)}>×</button>
              </Badge>
            </li>
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (client && person) save(client, person); }}>
        <div><Label htmlFor="cr-client">Client</Label>
          <Select id="cr-client" value={client} onChange={(e) => setClient(e.target.value)} className="min-w-48">
            <option value="">Choose a client</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select></div>
        <div><Label htmlFor="cr-person">Handled by</Label>
          <Select id="cr-person" value={person} onChange={(e) => setPerson(e.target.value)} className="min-w-48">
            <option value="">Choose a person</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
          </Select></div>
        <Button type="submit" variant="secondary" disabled={pending || !client || !person}>Save</Button>
      </form>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </div>
  );
}
