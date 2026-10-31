"use client";

import { Badge, Button, Card, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ruleAction, type RuleIn, saveNotificationSettings, saveRule } from "@/app/(app)/actions";

export type CatalogueEvent = { type: string; label: string; area: string; facts: Record<string, "number" | "text" | "bool"> };
export type Rule = RuleIn & { id: string; enabled: boolean; muted: boolean; mine: boolean; is_default: boolean; owner_user: string | null };
type Person = { id: string; name: string; role: string };
type Msg = { ok: boolean; text: string } | null;

const CHANNEL = { telegram: "Telegram", whatsapp: "WhatsApp", email: "Email", in_app: "In the app" } as const;
const OPS = { gt: "is more than", gte: "is at least", lt: "is less than", lte: "is at most", eq: "is", ne: "is not", contains: "contains", in: "is one of" };
const ROLES = ["owner", "manager", "staff", "finance", "viewer"] as const;
const ROLE_LABEL: Record<string, string> = { owner: "Owner", manager: "Manager", staff: "Front desk", finance: "Finance", viewer: "Viewer" };
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;

function describe(r: Rule, events: CatalogueEvent[], people: Person[]): string {
  const ev = events.find((e) => e.type === r.event_type)?.label ?? r.event_type;
  const cond = r.conditions.map((c) => `${c.field.replace("_", " ")} ${OPS[c.op as keyof typeof OPS] ?? c.op} ${c.value}`).join(" and ");
  const who = r.owner_user ? "me" : [...r.roles.map((x) => ROLE_LABEL[x] ?? x), ...r.user_ids.map((id) => people.find((p) => p.id === id)?.name ?? "someone"),
                                     ...(r.assignee ? ["whoever the card is assigned to"] : [])].join(", ");
  const how = r.channels.map((c) => CHANNEL[c as keyof typeof CHANNEL] ?? c).join(" + ");
  const when = r.cadence === "digest" ? `in a daily digest at ${r.digest_hour}:00` : "right away";
  return `When ${ev.toLowerCase()}${cond ? ` and ${cond}` : ""} → tell ${who} on ${how}, ${when}${r.critical ? " (even in quiet hours)" : ""}.`;
}

export function RulesList({ rules, events, people, canEditBusiness, channels }: { rules: Rule[]; events: CatalogueEvent[]; people: Person[];
                                                                               canEditBusiness: boolean; channels: string[] }) {
  const router = useRouter();
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const act = (r: Rule, a: Parameters<typeof ruleAction>[1]) => start(async () => {
    if (a === "delete" && !confirm(`Delete “${r.name}”?`)) return;
    const res = await ruleAction(r.id, a);
    if (!res.ok) return setMsg({ ok: false, text: res.error });
    if (a === "test") {
      const out = Object.entries((res.data as { results: Record<string, string> }).results);
      setMsg({ ok: true, text: out.length ? out.map(([c, v]) => `${CHANNEL[c as keyof typeof CHANNEL] ?? c}: ${v}`).join(" · ") : "This rule only shows in the app." });
    } else setMsg(null);
    router.refresh();
  });
  const groups = [...new Set(events.map((e) => e.area))];
  const shown = rules.filter((r) => events.some((e) => e.type === r.event_type));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => setEditing("new")}>New rule</Button>
        <Status msg={msg} />
      </div>
      {editing && <RuleForm initial={editing === "new" ? null : editing} events={events} people={people} canEditBusiness={canEditBusiness}
        channels={channels} onDone={() => { setEditing(null); router.refresh(); }} />}
      {groups.map((g) => {
        const rs = shown.filter((r) => events.find((e) => e.type === r.event_type)?.area === g);
        if (!rs.length) return null;
        return (
          <section key={g}>
            <h2 className="mb-2 text-sm font-semibold text-muted">{g}</h2>
            <div className="space-y-2">
              {rs.map((r) => {
                const editable = r.mine || canEditBusiness;
                return (
                  <Card key={r.id} className={`p-4 ${!r.enabled || r.muted ? "opacity-60" : ""}`}>
                    <div className="flex flex-wrap items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold">{r.name} {r.mine && <Badge>Just me</Badge>} {r.is_default && <Badge>Default</Badge>}
                          {!r.enabled && <Badge tone="warning">Off</Badge>} {r.muted && <Badge tone="warning">Muted for me</Badge>}</p>
                        <p className="mt-1 text-sm text-ink-soft">{describe(r, events, people)}</p>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        <Button size="sm" variant="ghost" disabled={pending} onClick={() => act(r, "test")}>Send me a test</Button>
                        {!r.mine && <Button size="sm" variant="ghost" disabled={pending} onClick={() => act(r, r.muted ? "unmute" : "mute")}>{r.muted ? "Unmute" : "Mute for me"}</Button>}
                        {editable && <Button size="sm" variant="ghost" disabled={pending} onClick={() => act(r, r.enabled ? "disable" : "enable")}>{r.enabled ? "Switch off" : "Switch on"}</Button>}
                        {editable && <Button size="sm" variant="secondary" disabled={pending} onClick={() => setEditing(r)}>Edit</Button>}
                        {editable && <Button size="sm" variant="ghost" disabled={pending} onClick={() => act(r, "delete")}>Delete</Button>}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </section>
        );
      })}
      {shown.length === 0 && <p className="text-sm text-muted">No rules yet.</p>}
    </div>
  );
}

function RuleForm({ initial, events, people, canEditBusiness, channels, onDone }: { initial: Rule | null; events: CatalogueEvent[]; people: Person[];
                                                                                   canEditBusiness: boolean; channels: string[]; onDone: () => void }) {
  const [r, setR] = useState<RuleIn>(initial ? { ...initial, personal: !!initial.owner_user } : {
    name: "", event_type: events[0]?.type ?? "", conditions: [], roles: ["owner"], user_ids: [], assignee: false,
    channels: channels.includes("telegram") ? ["telegram", "in_app"] : ["email", "in_app"], cadence: "now", digest_hour: 18, critical: false,
    personal: !canEditBusiness });
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const ev = events.find((e) => e.type === r.event_type);
  const facts = Object.entries(ev?.facts ?? {});
  const toggle = <K extends "roles" | "channels" | "user_ids">(k: K, v: string) =>
    setR({ ...r, [k]: r[k].includes(v) ? r[k].filter((x) => x !== v) : [...r[k], v] });
  return (
    <Card className="space-y-4 border-ink p-5">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); start(async () => {
        const res = await saveRule({ ...r, name: r.name || ev?.label || "Rule" }, initial?.id);
        if (!res.ok) return setMsg({ ok: false, text: res.error });
        onDone();
      }); }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label htmlFor="nr-name">Name</Label><Input id="nr-name" value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} placeholder={ev?.label} /></div>
          <div><Label htmlFor="nr-event">When</Label>
            <Select id="nr-event" value={r.event_type} onChange={(e) => setR({ ...r, event_type: e.target.value, conditions: [] })}>
              {[...new Set(events.map((x) => x.area))].map((area) => (
                <optgroup key={area} label={area}>{events.filter((x) => x.area === area).map((x) => <option key={x.type} value={x.type}>{x.label}</option>)}</optgroup>
              ))}
            </Select></div>
        </div>
        {facts.length > 0 && (
          <fieldset className="space-y-2"><legend className="text-sm font-medium">Only if (optional)</legend>
            {r.conditions.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Select aria-label="Field" className="w-auto" value={c.field} onChange={(e) => setR({ ...r, conditions: r.conditions.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)) })}>
                  {facts.map(([f]) => <option key={f} value={f}>{f.replace("_", " ")}</option>)}</Select>
                <Select aria-label="Comparison" className="w-auto" value={c.op} onChange={(e) => setR({ ...r, conditions: r.conditions.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)) })}>
                  {Object.entries(OPS).filter(([o]) => ev?.facts[c.field] === "number" || !["gt", "gte", "lt", "lte"].includes(o)).map(([o, l]) => <option key={o} value={o}>{l}</option>)}</Select>
                <Input aria-label="Value" className="w-40" value={String(c.value)} onChange={(e) => setR({ ...r, conditions: r.conditions.map((x, j) => (j === i ? { ...x, value: ev?.facts[c.field] === "number" && e.target.value !== "" && !isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value } : x)) })} />
                <Button type="button" size="sm" variant="ghost" onClick={() => setR({ ...r, conditions: r.conditions.filter((_, j) => j !== i) })}>Remove</Button>
              </div>
            ))}
            {r.conditions.length < 5 && facts[0] && <Button type="button" size="sm" variant="secondary" onClick={() => {
              const [field, kind] = facts[0]!;
              setR({ ...r, conditions: [...r.conditions, { field, op: kind === "number" ? "gt" : "eq", value: "" }] });
            }}>Add a condition</Button>}
          </fieldset>
        )}
        {canEditBusiness && !initial && (
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={r.personal} onChange={(e) => setR({ ...r, personal: e.target.checked })} />Just for me</label>
        )}
        {!r.personal && (
          <fieldset><legend className="mb-1.5 text-sm font-medium">Tell</legend>
            <div className="flex flex-wrap gap-4 text-sm">
              {ROLES.map((x) => <label key={x} className="flex items-center gap-2"><input type="checkbox" checked={r.roles.includes(x)} onChange={() => toggle("roles", x)} />{ROLE_LABEL[x]}</label>)}
              <label className="flex items-center gap-2"><input type="checkbox" checked={r.assignee} onChange={(e) => setR({ ...r, assignee: e.target.checked })} />The card&apos;s assignee</label>
            </div>
            {people.length > 0 && <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted">Specific people</summary>
              <div className="mt-2 flex flex-wrap gap-4">{people.map((p) => <label key={p.id} className="flex items-center gap-2"><input type="checkbox" checked={r.user_ids.includes(p.id)} onChange={() => toggle("user_ids", p.id)} />{p.name}</label>)}</div>
            </details>}
            <p className="mt-1 text-xs text-muted">Only people whose role can see this kind of event get it.</p>
          </fieldset>
        )}
        <fieldset><legend className="mb-1.5 text-sm font-medium">On</legend>
          <div className="flex flex-wrap gap-4 text-sm">{(["telegram", "whatsapp", "email", "in_app"] as const).map((c) => (
            <label key={c} className="flex items-center gap-2"><input type="checkbox" checked={r.channels.includes(c)} onChange={() => toggle("channels", c)} />{CHANNEL[c]}</label>
          ))}</div>
          <p className="mt-1 text-xs text-muted">Everything also appears in the bell. If a channel isn&apos;t set up for someone (no Telegram linked, no WhatsApp number), they get an email instead.</p>
        </fieldset>
        <div className="flex flex-wrap items-end gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name="cad" checked={r.cadence === "now"} onChange={() => setR({ ...r, cadence: "now" })} />Right away</label>
          <label className="flex items-center gap-2"><input type="radio" name="cad" checked={r.cadence === "digest"} onChange={() => setR({ ...r, cadence: "digest" })} />Daily digest at</label>
          <Input aria-label="Digest hour" type="number" min={0} max={23} className="h-9 w-20" value={r.digest_hour} disabled={r.cadence !== "digest"} onChange={(e) => setR({ ...r, digest_hour: Number(e.target.value) })} />
          <label className="flex items-center gap-2"><input type="checkbox" checked={r.critical} onChange={(e) => setR({ ...r, critical: e.target.checked })} />Critical (ignore quiet hours and limits)</label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={pending || !r.channels.length}>{initial ? "Save rule" : "Create rule"}</Button>
          <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
          <Status msg={msg} />
        </div>
      </form>
    </Card>
  );
}

export function MySettings({ quiet, maxPerHour }: { quiet: { from: string; to: string } | null; maxPerHour: number }) {
  const router = useRouter();
  const [from, setFrom] = useState(quiet?.from ?? "");
  const [to, setTo] = useState(quiet?.to ?? "");
  const [max, setMax] = useState(maxPerHour);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await saveNotificationSettings(from || null, to || null, max);
      setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
      router.refresh();
    }); }}>
      <div><Label htmlFor="q-from">Quiet from</Label><Input id="q-from" type="time" value={from} onChange={(e) => setFrom(e.target.value)} className="w-32" /></div>
      <div><Label htmlFor="q-to">until</Label><Input id="q-to" type="time" value={to} onChange={(e) => setTo(e.target.value)} className="w-32" /></div>
      <div><Label htmlFor="q-max">At most per hour</Label><Input id="q-max" type="number" min={1} max={100} value={max} onChange={(e) => setMax(Number(e.target.value))} className="w-24" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>Save</Button>
      <Status msg={msg} />
      <p className="w-full text-xs text-muted">During quiet hours, notifications wait until morning (critical ones still come). Over your hourly limit, the rest arrive together an hour later.</p>
    </form>
  );
}
