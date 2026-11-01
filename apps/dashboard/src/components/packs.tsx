"use client";

import { Badge, Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { hqAssignPack, hqRemovePack, hqSavePack } from "@/app/(app)/actions";
import type { PlanIn } from "@/components/hq-billing";
import type { CatalogItem } from "@/components/new-client-form";

/** docs/PACKS.md: bundles of agents, tailored per client; every agent is also sold standalone. */
export type PackAgent = { key: string; default_on: boolean };
export type Pack = { key: string; name: string; tagline: string; audience: string; agents: PackAgent[];
  pricing: Record<string, Partial<PlanIn>>; active: boolean; clients?: number };
export type OrgPack = { key: string; name: string; tagline: string; agents: { key: string; name: string; on: boolean; coming_soon: boolean }[];
  add_ons: { key: string; name: string }[] } | null;

const CURRENCIES = ["INR", "USD"] as const;
const money = (v: unknown) => (v === undefined || v === null ? "" : String(Number(v)));

export function PackEditor({ pack, catalog, onDone }: { pack?: Pack; catalog: CatalogItem[]; onDone?: () => void }) {
  const router = useRouter();
  const create = !pack;
  const [key, setKey] = useState(pack?.key ?? "");
  const [name, setName] = useState(pack?.name ?? "");
  const [tagline, setTagline] = useState(pack?.tagline ?? "");
  const [audience, setAudience] = useState(pack?.audience ?? "");
  const [active, setActive] = useState(pack?.active ?? true);
  const [agents, setAgents] = useState<PackAgent[]>(pack?.agents ?? []);
  const [price, setPrice] = useState<Record<string, { setup_fee: string; retainer: string }>>(() => Object.fromEntries(
    CURRENCIES.map((c) => [c, { setup_fee: money(pack?.pricing[c]?.setup_fee), retainer: money(pack?.pricing[c]?.retainer) }])));
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const inPack = new Map(agents.map((a) => [a.key, a]));
  // the pack's agents first, in its order, then everything else
  const rows = [...agents.map((a) => catalog.find((c) => c.key === a.key)!).filter(Boolean), ...catalog.filter((c) => !inPack.has(c.key))];

  function toggle(k: string) {
    setAgents(inPack.has(k) ? agents.filter((a) => a.key !== k) : [...agents, { key: k, default_on: true }]);
  }
  function save() {
    setErr(null);
    // keep the rest of each currency's plan (included usage, overage, tax) and change only what's edited here
    const pricing = Object.fromEntries(CURRENCIES.filter((c) => price[c]!.retainer || price[c]!.setup_fee || pack?.pricing[c]).map((c) => [c, {
      ...(pack?.pricing[c] ?? { tax_rate: c === "INR" ? 0.18 : 0 }), currency: c,
      setup_fee: Number(price[c]!.setup_fee || 0), retainer: Number(price[c]!.retainer || 0) }]));
    start(async () => {
      const r = await hqSavePack(key, { name, tagline, audience, active, agents, pricing }, create);
      if (!r.ok) return setErr(r.error);
      router.refresh();
      onDone?.();
    });
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {create && <div className="space-y-1"><Label htmlFor="pk">Key</Label>
          <Input id="pk" value={key} onChange={(e) => setKey(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} placeholder="clinic" /></div>}
        <div className="space-y-1"><Label htmlFor="pn">Name</Label><Input id="pn" value={name} onChange={(e) => setName(e.target.value)} placeholder="Clinic" /></div>
        <div className="space-y-1 sm:col-span-2"><Label htmlFor="pt">Tagline</Label><Input id="pt" value={tagline} maxLength={160} onChange={(e) => setTagline(e.target.value)} /></div>
        <div className="space-y-1 sm:col-span-2"><Label htmlFor="pa">Who it&apos;s for</Label><Input id="pa" value={audience} maxLength={200} onChange={(e) => setAudience(e.target.value)} /></div>
      </div>
      <div>
        <p className="mb-1 font-semibold">Agents <span className="font-normal text-muted">({agents.length} in the pack, {agents.filter((a) => a.default_on).length} on by default)</span></p>
        <ul className="divide-y divide-line rounded-xl border-2 border-line">
          {rows.map((c) => {
            const a = inPack.get(c.key);
            return (
              <li key={c.key} className="flex flex-wrap items-center gap-3 px-3 py-2">
                <input type="checkbox" className="h-4 w-4 accent-[var(--ink)]" checked={!!a} onChange={() => toggle(c.key)} aria-label={`${c.name} in pack`} />
                <span className="min-w-0 flex-1"><span className="font-medium">{c.name}</span>{!c.available && <Badge className="ml-2">coming soon</Badge>}
                  <span className="block truncate text-xs text-muted">{c.description}</span></span>
                {a && <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" className="h-4 w-4 accent-[var(--ink)]" checked={a.default_on}
                  onChange={() => setAgents(agents.map((x) => (x.key === c.key ? { ...x, default_on: !x.default_on } : x)))} />on by default</label>}
              </li>
            );
          })}
        </ul>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {CURRENCIES.map((c) => (
          <div key={c} className="space-y-2 rounded-xl bg-paper p-3">
            <p className="text-sm font-semibold">Price in {c} <span className="font-normal text-muted">(suggested; editable per client)</span></p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label htmlFor={`sf-${c}`}>Setup fee</Label><Input id={`sf-${c}`} inputMode="decimal" value={price[c]!.setup_fee}
                onChange={(e) => setPrice({ ...price, [c]: { ...price[c]!, setup_fee: e.target.value } })} /></div>
              <div className="space-y-1"><Label htmlFor={`rt-${c}`}>Monthly</Label><Input id={`rt-${c}`} inputMode="decimal" value={price[c]!.retainer}
                onChange={(e) => setPrice({ ...price, [c]: { ...price[c]!, retainer: e.target.value } })} /></div>
            </div>
          </div>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[var(--ink)]" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active (archived packs stay with their clients but can&apos;t be given to anyone new)</label>
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      <Button onClick={save} disabled={pending || !name || !agents.length || (create && key.length < 2)}>{pending ? "Saving…" : create ? "Create pack" : "Save pack"}</Button>
    </div>
  );
}

/** HQ client page: which pack they bought and which of its agents they get; add-ons are switched separately. */
export function ClientPack({ orgId, packs, current, catalog }: { orgId: string; packs: Pack[]; current: OrgPack; catalog: CatalogItem[] }) {
  const router = useRouter();
  const choosable = packs.filter((p) => p.active || p.key === current?.key);
  const [key, setKey] = useState(current?.key ?? "");
  const pack = choosable.find((p) => p.key === key);
  const startWith = (k: string) => (k === current?.key ? current.agents.map((a) => a.key) : choosable.find((p) => p.key === k)?.agents.filter((a) => a.default_on).map((a) => a.key) ?? []);
  const [chosen, setChosen] = useState<string[]>(startWith(current?.key ?? ""));
  const [usePrice, setUsePrice] = useState(!current);
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const info = Object.fromEntries(catalog.map((c) => [c.key, c]));

  function run(f: () => Promise<{ ok: boolean; error?: string }>) {
    setErr(null);
    start(async () => {
      const r = await f();
      if (!r.ok) return setErr(r.error ?? "failed");
      router.refresh();
    });
  }
  return (
    <div className="space-y-3">
      {current ? (
        <p className="text-sm">Bought: <span className="font-semibold">{current.name}</span> · {current.agents.filter((a) => a.on).length} on
          {current.agents.some((a) => a.coming_soon) && <>, {current.agents.filter((a) => a.coming_soon).length} coming soon</>}
          {current.add_ons.length > 0 && <> · add-ons: {current.add_ons.map((a) => a.name).join(", ")}</>}</p>
      ) : <p className="text-sm text-muted">No pack: every agent is a standalone add-on.</p>}
      <div className="space-y-1"><Label htmlFor="pack">Pack</Label>
        <Select id="pack" value={key} onChange={(e) => { setKey(e.target.value); setChosen(startWith(e.target.value)); }}>
          <option value="">Choose a pack…</option>
          {choosable.map((p) => <option key={p.key} value={p.key}>{p.name}{p.active ? "" : " (archived)"}</option>)}
        </Select></div>
      {pack && (
        <>
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {pack.agents.map((a) => (
              <li key={a.key}><label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--ink)]" checked={chosen.includes(a.key)}
                  onChange={() => setChosen(chosen.includes(a.key) ? chosen.filter((k) => k !== a.key) : [...chosen, a.key])} />
                <span>{info[a.key]?.name ?? a.key}{!info[a.key]?.available && <Badge className="ml-1.5">coming soon</Badge>}</span>
              </label></li>
            ))}
          </ul>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[var(--ink)]" checked={usePrice} onChange={(e) => setUsePrice(e.target.checked)} />
            Set their pricing plan to the pack&apos;s price (replaces the current plan)</label>
          <div className="flex flex-wrap gap-2">
            <Button disabled={pending || !chosen.length} onClick={() => run(() => hqAssignPack(orgId, key, chosen, usePrice))}>
              {pending ? "Saving…" : current ? "Save pack" : "Give them this pack"}</Button>
            {current && <Button variant="secondary" disabled={pending} onClick={() => {
              if (!confirm(`Remove the ${current.name} pack? Its agents stay switched on as add-ons.`)) return;
              run(() => hqRemovePack(orgId, true));
            }}>Remove pack</Button>}
          </div>
          <p className="text-xs text-muted">Coming-soon agents are kept with their pack and switched on once built. Unticked agents of this pack are switched off; add-ons are never touched.</p>
        </>
      )}
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
    </div>
  );
}
