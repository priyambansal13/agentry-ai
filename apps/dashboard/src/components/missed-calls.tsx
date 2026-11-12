"use client";

import { Button, Input, Label } from "@agentry/ui";
import { Check, Copy } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { testMissedCall } from "@/app/(app)/actions";

export function CopyUrl({ url }: { url: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <code className="min-w-0 flex-1 break-all rounded-xl border-2 border-line bg-paper px-3 py-2 text-sm">{url}</code>
      <Button size="sm" variant="secondary" onClick={() => { void navigator.clipboard.writeText(url); setDone(true); setTimeout(() => setDone(false), 1500); }}>
        {done ? <Check aria-hidden="true" className="h-4 w-4" /> : <Copy aria-hidden="true" className="h-4 w-4" />}<span className="ml-1">{done ? "Copied" : "Copy"}</span></Button>
    </div>
  );
}

/** A pretend missed call from your own phone: see the WhatsApp arrive. */
export function TestCall() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
      const r = await testMissedCall(phone);
      setMsg(r.ok ? "Recorded. The WhatsApp goes out after the delay you set; refresh to see it." : r.error ?? "failed");
      router.refresh();
    }); }}>
      <div className="space-y-1"><Label htmlFor="mc-p">Your mobile</Label><Input id="mc-p" type="tel" required value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98100 00011" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Sending…" : "Pretend I missed your call"}</Button>
      {msg && <p className="basis-full text-sm text-muted">{msg}</p>}
    </form>
  );
}
