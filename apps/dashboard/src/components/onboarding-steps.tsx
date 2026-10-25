"use client";

import { Button, Input, Label, Select, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { goLive, markStep, setPersona, testAgent, updateProfile } from "@/app/(app)/actions";

function Status({ msg }: { msg: { ok: boolean; text: string } | null }) {
  return msg ? <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span> : null;
}

export function MarkDone({ step, label = "Mark as done", allowSkip = false }: { step: string; label?: string; allowSkip?: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const go = (status: "done" | "skipped") => start(async () => { await markStep(step, status); router.refresh(); });
  return (
    <div className="flex gap-2">
      <Button onClick={() => go("done")} disabled={pending}>{label}</Button>
      {allowSkip && <Button variant="ghost" onClick={() => go("skipped")} disabled={pending}>Skip for now</Button>}
    </div>
  );
}

export function ProfileStep({ initial }: { initial: Record<string, string | number | null> }) {
  const router = useRouter();
  const [f, setF] = useState(initial);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await updateProfile({ ...f, customer_value: f.customer_value === "" || f.customer_value == null ? null : Number(f.customer_value) });
        setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
        if (r.ok) router.refresh();
      });
    }}>
      <div><Label htmlFor="p-web">Website</Label><Input id="p-web" value={String(f.website ?? "")} onChange={set("website")} /></div>
      <div><Label htmlFor="p-phone">Phone</Label><Input id="p-phone" value={String(f.phone ?? "")} onChange={set("phone")} /></div>
      <div className="sm:col-span-2"><Label htmlFor="p-addr">Address</Label><Input id="p-addr" value={String(f.address ?? "")} onChange={set("address")} /></div>
      <div><Label htmlFor="p-city">City</Label><Input id="p-city" value={String(f.city ?? "")} onChange={set("city")} /></div>
      <div><Label htmlFor="p-tz">Time zone</Label>
        <Select id="p-tz" value={String(f.timezone ?? "Asia/Kolkata")} onChange={set("timezone")}>
          {["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York", "America/Chicago", "America/Los_Angeles", "Australia/Sydney"].map((z) => <option key={z}>{z}</option>)}
        </Select></div>
      <div><Label htmlFor="p-cur">Currency</Label>
        <Select id="p-cur" value={String(f.currency ?? "INR")} onChange={set("currency")}>{["INR", "USD", "EUR", "GBP", "AED"].map((c) => <option key={c}>{c}</option>)}</Select></div>
      <div><Label htmlFor="p-val">What is one customer worth to you?</Label>
        <Input id="p-val" type="number" min={0} value={String(f.customer_value ?? "")} onChange={set("customer_value")} />
        <p className="mt-1 text-xs text-muted">Used to show the money your agents win back.</p></div>
      <div className="flex items-center gap-3 sm:col-span-2"><Button type="submit" disabled={pending}>Save profile</Button><Status msg={msg} /></div>
    </form>
  );
}

export function PersonaStep({ initial }: { initial: { name?: string; tone?: string; greeting?: string; signoff?: string } }) {
  const router = useRouter();
  const [p, setP] = useState({ name: initial.name ?? "", tone: initial.tone ?? "", greeting: initial.greeting ?? "", signoff: initial.signoff ?? "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="space-y-4" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await setPersona({ ...p, signoff: p.signoff || undefined });
        setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
        if (r.ok) router.refresh();
      });
    }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><Label htmlFor="ps-name">Agent name</Label><Input id="ps-name" required value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></div>
        <div><Label htmlFor="ps-sign">Email sign-off</Label><Input id="ps-sign" value={p.signoff} onChange={(e) => setP({ ...p, signoff: e.target.value })} placeholder="Team SmileCraft" /></div>
      </div>
      <div><Label htmlFor="ps-tone">Tone</Label><Input id="ps-tone" required value={p.tone} onChange={(e) => setP({ ...p, tone: e.target.value })} /></div>
      <div><Label htmlFor="ps-greet">First message on your website</Label><Textarea id="ps-greet" required value={p.greeting} onChange={(e) => setP({ ...p, greeting: e.target.value })} />
        <p className="mt-1 text-xs text-muted">Keep the words &quot;AI assistant&quot; in it: customers should always know.</p></div>
      <div className="flex items-center gap-3"><Button type="submit" disabled={pending}>Save persona</Button><Status msg={msg} /></div>
    </form>
  );
}

type Line = { from: "you" | "agent"; text: string; booking?: { service: string; when: string; staff: string } | null };

export function TestChat({ greeting }: { greeting: string }) {
  const [lines, setLines] = useState<Line[]>([{ from: "agent", text: greeting }]);
  const [text, setText] = useState("");
  const [conv, setConv] = useState<string | undefined>();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  function send(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setLines((l) => [...l, { from: "you", text: t }]);
    setText("");
    start(async () => {
      const r = await testAgent(t, conv);
      if (!r.ok) return setError(r.error);
      setConv(r.data.conversation_id);
      setLines((l) => [...l, { from: "agent", text: r.data.reply, booking: r.data.booking }]);
    });
  }
  return (
    <div className="rounded-2xl border-2 border-ink">
      <div className="flex max-h-96 min-h-56 flex-col gap-2 overflow-y-auto p-4" aria-live="polite">
        {lines.map((l, i) => (
          <div key={i} className={l.from === "you" ? "self-end" : "self-start"}>
            <div className={`max-w-md rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap ${l.from === "you" ? "bg-ink text-paper" : "bg-paper border border-line"}`}>{l.text}</div>
            {l.booking && <div className="mt-1 rounded-xl border-2 border-ink bg-lime px-3 py-1.5 text-xs text-lime-ink">✓ Test booking: {l.booking.service}, {l.booking.when}</div>}
          </div>
        ))}
        {pending && <div className="self-start text-sm text-muted">typing…</div>}
      </div>
      <form onSubmit={send} className="flex gap-2 border-t border-line p-3">
        <label htmlFor="test-msg" className="sr-only">Message</label>
        <Input id="test-msg" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask what a customer would ask…" />
        <Button type="submit" disabled={pending}>Send</Button>
      </form>
      {error && <p role="alert" className="px-3 pb-3 text-sm text-danger">{error}</p>}
    </div>
  );
}

export function GoLive({ ready, missing }: { ready: boolean; missing: string[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <div className="space-y-3">
      <p className="text-ink-soft">Your agents will start in <strong>approval mode</strong>: every message they write waits for your OK in Needs you. We&apos;ll review results with you after 14 days and switch steps to automatic when you&apos;re happy.</p>
      {!ready && <p className="text-sm text-warning">Finish first: {missing.join(", ")}</p>}
      <Button size="lg" disabled={!ready || pending} onClick={() => start(async () => {
        const r = await goLive();
        setMsg(r.ok ? { ok: true, text: "You're live! 🎉" } : { ok: false, text: r.error });
        if (r.ok) router.push("/home");
      })}>Go live</Button>
      <Status msg={msg} />
    </div>
  );
}
