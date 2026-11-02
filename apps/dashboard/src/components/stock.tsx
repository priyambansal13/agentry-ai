"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { applyScan, importStock, scanShelf } from "@/app/(app)/actions";

/** Stock shelf scanner (ROADMAP-V3 B2). */
type Line = { name: string; read_as: string; count: number; unit: string; confidence: number; item_id: string | null; previous: number | null };

export function ScanShelf({ confirmBelow }: { confirmBelow: number }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const [area, setArea] = useState("");
  const [scan, setScan] = useState<{ id: string; items: Line[] } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label htmlFor="sa">Shelf / area</Label><Input id="sa" value={area} onChange={(e) => setArea(e.target.value)} placeholder="Front shelf" /></div>
        <input type="file" accept="image/*" capture="environment" disabled={pending} className="text-sm" onChange={(e) => {
          const f = e.target.files?.[0]; if (!f) return;
          const fd = new FormData(); fd.append("photo", f); if (area) fd.append("area", area);
          setErr(null); setDone(null);
          start(async () => { const r = await scanShelf(fd); if (!r.ok) return setErr(r.error); setScan(r.data); });
          e.target.value = "";
        }} />
      </div>
      {pending && <p className="text-sm text-muted">Counting…</p>}
      {scan && (
        <div className="space-y-2">
          {scan.items.length === 0 ? <p className="text-sm text-muted">Nothing could be counted in that photo: try closer, in good light.</p> : (
            <table className="w-full text-sm"><thead className="text-left text-muted"><tr><th className="p-1">Item</th><th className="p-1">Last count</th><th className="p-1">Count now</th></tr></thead>
              <tbody>{scan.items.map((l, i) => (
                <tr key={i} className={l.confidence < confirmBelow ? "bg-[var(--warning)]/10" : ""}>
                  <td className="p-1">{l.name}{!l.item_id && <span className="text-xs text-muted"> (new)</span>}{l.confidence < confirmBelow && <span className="block text-xs text-warning">check this count</span>}</td>
                  <td className="p-1 text-muted">{l.previous ?? "-"}</td>
                  <td className="p-1"><Input aria-label={`${l.name} count`} className="h-8 w-24" inputMode="numeric" value={String(l.count)}
                    onChange={(e) => setScan({ ...scan, items: scan.items.map((x, j) => (j === i ? { ...x, count: Number(e.target.value) || 0 } : x)) })} /></td>
                </tr>))}</tbody></table>)}
          {scan.items.length > 0 && <Button disabled={pending} onClick={() => start(async () => {
            const r = await applyScan(scan.id, scan.items.map((l) => ({ name: l.name, count: l.count, unit: l.unit, item_id: l.item_id })), true);
            if (!r.ok) return setErr(r.error);
            setDone(`Saved: ${r.data.updated} updated, ${r.data.added} new`); setScan(null); router.refresh();
          })}>Save these counts</Button>}
        </div>)}
      {done && <p className="text-sm">{done}</p>}{err && <p role="alert" className="text-sm text-danger">{err}</p>}
    </div>
  );
}

export function ImportStock() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return <div className="space-y-1"><input type="file" accept=".csv,.xlsx" disabled={pending} className="text-sm" onChange={(e) => {
    const f = e.target.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    start(async () => { const r = await importStock(fd); setMsg(r.ok ? `${r.data.imported} items loaded` : r.error); router.refresh(); });
    e.target.value = "";
  }} />{msg && <p className="text-sm">{msg}</p>}</div>;
}
