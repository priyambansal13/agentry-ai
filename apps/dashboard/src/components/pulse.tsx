"use client";

import { Button, Card, Label, Select } from "@agentry/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { savePulseSettings, sendPulseNow } from "@/app/(app)/actions";

export type Pulse = { title: string; opener: string; items: { kind: "do" | "today" | "good"; text: string; action: string; link: string }[];
                      settings: { enabled: boolean; hour: number; weekly: boolean }; can_edit: boolean };

/** Today's brief on Home: what needs doing first, today, and good news (agentry/pulse.py). */
export function PulseCard({ p }: { p: Pulse }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [s, setS] = useState(p.settings);
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const doNow = p.items.filter((i) => i.kind !== "good");
  const good = p.items.find((i) => i.kind === "good");
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-hand text-lg text-muted">Today</p>
          <p className="font-semibold">{p.opener}</p>
        </div>
        {p.can_edit && <button type="button" className="text-xs text-muted underline hover:text-ink" onClick={() => setOpen((o) => !o)}>{open ? "Close" : "Brief settings"}</button>}
      </div>
      {doNow.length > 0 && (
        <ul className="mt-3 space-y-2">
          {doNow.map((i) => (
            <li key={i.text} className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span aria-hidden="true">{i.kind === "do" ? "→" : "•"}</span>
              <Link href={i.link} className="font-medium hover:underline">{i.text}</Link>
              {i.action && <span className="text-muted">{i.action}</span>}
            </li>
          ))}
        </ul>
      )}
      {good && <p className="mt-3 text-sm text-ink-soft"><span className="font-medium">Yesterday:</span> {good.text}</p>}
      {open && p.can_edit && (
        <form className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4 text-sm" onSubmit={(e) => { e.preventDefault(); start(async () => {
          const r = await savePulseSettings(s.enabled, s.hour, s.weekly);
          setMsg(r.ok ? "Saved" : r.error);
          router.refresh();
        }); }}>
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.enabled} onChange={(e) => setS({ ...s, enabled: e.target.checked })} />Send a morning brief</label>
          <div><Label htmlFor="pulse-hour">at</Label>
            <Select id="pulse-hour" className="h-9 w-auto" value={s.hour} onChange={(e) => setS({ ...s, hour: Number(e.target.value) })}>
              {[5, 6, 7, 8, 9, 10, 11, 12].map((h) => <option key={h} value={h}>{h}:00</option>)}</Select></div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.weekly} onChange={(e) => setS({ ...s, weekly: e.target.checked })} />and a week in review on Mondays</label>
          <Button type="submit" size="sm" variant="secondary" disabled={pending}>Save</Button>
          <Button type="button" size="sm" variant="ghost" disabled={pending} onClick={() => start(async () => {
            const r = await sendPulseNow();
            setMsg(r.ok ? "Sent: it goes to whoever the Morning brief rule says" : r.error);
          })}>Send it now</Button>
          {msg && <span role="status" className="text-sm text-muted">{msg}</span>}
          <p className="w-full text-xs text-muted">Who gets it, and how, is set in <Link href="/settings/notifications" className="underline">Notification rules</Link> (Morning brief, Monday week in review).</p>
        </form>
      )}
    </Card>
  );
}
