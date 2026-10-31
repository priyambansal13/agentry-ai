"use client";

import { Badge, Button, Card, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { saveAutonomy } from "@/app/(app)/actions";

export type GovAction = { action: string; label: string; agent: string; level: string; levels: string[]; chosen: boolean;
  limits: { max_per_day?: number; quiet_hours?: boolean }; record: { decided: number; as_written: number; edited: number; rejected: number; rate: number | null };
  suggestion: string | null };

const LEVEL: Record<string, { name: string; hint: string }> = {
  shadow: { name: "Watch only", hint: "Works it out and records what it would have done. Nothing is sent." },
  recommend: { name: "Suggest", hint: "A card in Needs you: a person decides." },
  auto_limited: { name: "Act within limits", hint: "Goes out on its own up to the daily limit, never at night; the rest become cards." },
  auto: { name: "Act", hint: "Goes out on its own (the daily limit still applies)." },
};

export function AutonomyRow({ a, canChange }: { a: GovAction; canChange: boolean }) {
  const router = useRouter();
  const [level, setLevel] = useState(a.level);
  const [max, setMax] = useState(a.limits.max_per_day ?? 50);
  const [quiet, setQuiet] = useState(!!a.limits.quiet_hours);
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const changed = level !== a.level || max !== a.limits.max_per_day || quiet !== !!a.limits.quiet_hours;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">{a.label}</h2>
          <p className="text-sm text-muted">{LEVEL[a.level]?.name}{a.chosen ? "" : " (from this agent's approval / live setting)"}
            {a.record.decided > 0 && <> · last 30 days: {a.record.as_written} of {a.record.decided} approved as written{a.record.edited ? `, ${a.record.edited} edited` : ""}{a.record.rejected ? `, ${a.record.rejected} discarded` : ""}</>}</p>
        </div>
      </div>
      {a.suggestion && <p className="mt-3 rounded-xl border-2 border-lime bg-lime-soft px-4 py-2 text-sm">💡 {a.suggestion}</p>}
      <fieldset className="mt-4" disabled={!canChange}>
        <legend className="sr-only">How much it may do on its own</legend>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {a.levels.map((l) => (
            <label key={l} className={`cursor-pointer rounded-xl border-2 p-3 text-sm ${level === l ? "border-ink bg-lime-soft" : "border-line"} ${!canChange ? "cursor-default opacity-80" : ""}`}>
              <input type="radio" name={`lvl-${a.action}`} className="sr-only" checked={level === l} onChange={() => setLevel(l)} />
              <span className="block font-semibold">{LEVEL[l]?.name ?? l}</span>
              <span className="mt-1 block text-xs text-muted">{LEVEL[l]?.hint}</span>
            </label>
          ))}
        </div>
        {(level === "auto_limited" || level === "auto") && (
          <div className="mt-3 flex flex-wrap items-end gap-4 text-sm">
            <div><Label htmlFor={`max-${a.action}`}>At most per day</Label>
              <Input id={`max-${a.action}`} type="number" min={0} max={10000} className="w-28" value={max} onChange={(e) => setMax(Number(e.target.value))} /></div>
            <label className="flex items-center gap-2"><input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} />Never between 9 pm and 8 am</label>
          </div>
        )}
      </fieldset>
      {canChange && changed && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="sm" disabled={pending} onClick={() => start(async () => {
            if ((level === "auto" || level === "auto_limited") && a.level !== level && !confirm(`Let “${a.label}” go out without a person approving each one?`)) return;
            const r = await saveAutonomy(a.action, level, max, quiet);
            setMsg(r.ok ? "Saved" : r.error);
            router.refresh();
          })}>Save</Button>
          {msg && <span role="status" className="text-sm text-muted">{msg}</span>}
        </div>
      )}
      {!canChange && <p className="mt-3 text-xs text-muted"><Badge>Owner only</Badge> Only the owner changes this.</p>}
    </Card>
  );
}
