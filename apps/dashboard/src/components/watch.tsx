"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addWatcher, checkWatcher, removeWatcher, setWatcherStatus } from "@/app/(app)/actions";

type Msg = { ok: boolean; text: string } | null;
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;

export function AddWatcher() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  const [w, setW] = useState<{ kind: "page" | "price"; name: string; url: string }>({ kind: "page", name: "", url: "" });
  function submit(e: React.FormEvent) {
    e.preventDefault();
    start(async () => {
      const r = await addWatcher(w);
      setMsg(!r.ok ? { ok: false, text: r.error } : r.data.error ? { ok: false, text: `Added, but the page couldn't be read: ${r.data.error}` }
        : { ok: true, text: "Added. You'll hear when it changes." });
      if (r.ok) { setW({ ...w, name: "", url: "" }); router.refresh(); }
    });
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[10rem_1fr_1.5fr_auto] sm:items-end">
      <div><Label htmlFor="w-kind">Watch</Label>
        <Select id="w-kind" value={w.kind} onChange={(e) => setW({ ...w, kind: e.target.value as "page" | "price" })}>
          <option value="page">A page (offers, menu)</option><option value="price">A product price</option>
        </Select></div>
      <div><Label htmlFor="w-name">Name</Label><Input id="w-name" required value={w.name} onChange={(e) => setW({ ...w, name: e.target.value })} placeholder="Rival Dental offers" /></div>
      <div><Label htmlFor="w-url">Web address</Label><Input id="w-url" type="url" required value={w.url} onChange={(e) => setW({ ...w, url: e.target.value })} placeholder="https://…" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Reading…" : "Watch it"}</Button>
      <div className="sm:col-span-4"><Status msg={msg} /></div>
    </form>
  );
}

export function WatcherActions({ id, status }: { id: string; status: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="secondary" disabled={pending} onClick={() => start(async () => {
        const r = await checkWatcher(id);
        setMsg(!r.ok ? { ok: false, text: r.error } : r.data.error ? { ok: false, text: r.data.error } : { ok: true, text: r.data.changed ? "Changed!" : "No change" });
        router.refresh();
      })}>Check now</Button>
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => start(async () => {
        await setWatcherStatus(id, status === "paused" ? "active" : "paused"); router.refresh();
      })}>{status === "paused" ? "Resume" : "Pause"}</Button>
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => confirm("Stop watching this page?") && start(async () => {
        await removeWatcher(id); router.refresh();
      })}>Remove</Button>
      <Status msg={msg} />
    </div>
  );
}
