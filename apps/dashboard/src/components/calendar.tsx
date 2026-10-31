"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addToWaitlist, markBooking, removeFromWaitlist } from "@/app/(app)/actions";

type Msg = { ok: boolean; text: string } | null;
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;

/** Showed / No-show / Cancel on one appointment. No-show sends "we missed you" with new times; cancel offers the slot to the waitlist. */
export function BookingActions({ id, status, past }: { id: string; status: string; past: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  const act = (s: "showed" | "no_show" | "cancelled" | "confirmed", confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    start(async () => {
      const r = await markBooking(id, s);
      setMsg(r.ok ? null : { ok: false, text: r.error });
      if (r.ok) router.refresh();
    });
  };
  if (!["booked", "confirmed"].includes(status)) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {past ? (
        <>
          <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("showed")}>Showed</Button>
          <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("no_show")}>No-show</Button>
        </>
      ) : status === "booked" && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("confirmed")}>Mark confirmed</Button>}
      <Button size="sm" variant="ghost" disabled={pending}
              onClick={() => act("cancelled", "Cancel this appointment? The slot is offered to people on the waitlist.")}>Cancel</Button>
      <Status msg={msg} />
    </div>
  );
}

export function AddToWaitlist({ services }: { services: { key: string; name: string }[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  const [f, setF] = useState({ name: "", phone: "", email: "", service_key: services[0]?.key ?? "", notes: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  function submit(e: React.FormEvent) {
    e.preventDefault();
    start(async () => {
      const r = await addToWaitlist({ name: f.name, service_key: f.service_key, phone: f.phone || undefined, email: f.email || undefined, notes: f.notes || undefined });
      setMsg(r.ok ? { ok: true, text: "Added. They'll be offered the next freed slot." } : { ok: false, text: r.error });
      if (r.ok) { setF({ ...f, name: "", phone: "", email: "", notes: "" }); router.refresh(); }
    });
  }
  if (!services.length) return <p className="text-sm text-muted">Add services in onboarding first.</p>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <div><Label htmlFor="wl-name">Name</Label><Input id="wl-name" required value={f.name} onChange={set("name")} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><Label htmlFor="wl-phone">Phone (WhatsApp)</Label><Input id="wl-phone" value={f.phone} onChange={set("phone")} placeholder="+91 98…" /></div>
        <div><Label htmlFor="wl-email">Email</Label><Input id="wl-email" type="email" value={f.email} onChange={set("email")} /></div>
      </div>
      <div>
        <Label htmlFor="wl-service">Wants</Label>
        <Select id="wl-service" value={f.service_key} onChange={set("service_key")}>
          {services.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
        </Select>
      </div>
      <div><Label htmlFor="wl-notes">Notes (optional)</Label><Input id="wl-notes" value={f.notes} onChange={set("notes")} placeholder="Prefers mornings" /></div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending || !f.name || !(f.phone || f.email)}>Add to waitlist</Button>
        <Status msg={msg} />
      </div>
    </form>
  );
}

export function RemoveFromWaitlist({ id }: { id: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button size="sm" variant="ghost" disabled={pending} onClick={() => start(async () => { const r = await removeFromWaitlist(id); if (r.ok) router.refresh(); })}>
      Remove
    </Button>
  );
}
