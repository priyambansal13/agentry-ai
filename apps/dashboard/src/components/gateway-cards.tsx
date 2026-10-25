"use client";

import { Badge, Button, Card, Input, Label } from "@agentry/ui";
import { CreditCard } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { connectRazorpay, connectStripe } from "@/app/(app)/actions";
import type { Connection } from "./connections";

function Result({ r }: { r: { ok: true; url: string; events: string[] } | { ok: false; error: string } | null }) {
  if (!r) return null;
  if (!r.ok) return <p role="alert" className="text-sm text-danger">{r.error}</p>;
  return (
    <div role="status" className="rounded-xl bg-paper p-3 text-sm">
      <p className="font-medium text-success">✓ Connected. Last step: add this webhook in the gateway dashboard</p>
      <code className="mt-1 block break-all text-xs">{r.url}</code>
      <p className="mt-1 text-xs text-muted">Events: {r.events.join(", ")}</p>
    </div>
  );
}

export function GatewayCards({ razorpay, stripe, canManage }: { razorpay?: Connection; stripe?: Connection; canManage: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [rz, setRz] = useState({ key_id: "", key_secret: "", webhook_secret: "" });
  const [st, setSt] = useState("");
  const [sk, setSk] = useState("");
  const [rzRes, setRzRes] = useState<Parameters<typeof Result>[0]["r"]>(null);
  const [stRes, setStRes] = useState<Parameters<typeof Result>[0]["r"]>(null);
  return (
    <Card className="p-6">
      <div className="flex items-start gap-4">
        <CreditCard className="mt-1 h-6 w-6 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-5">
          <div>
            <h2 className="font-display text-xl font-bold">Payments</h2>
            <p className="mt-1 text-sm text-muted">So reminders stop the moment a customer pays, and reminders can include a payment link.</p>
          </div>
          <div>
            <div className="flex items-center gap-2"><h3 className="font-semibold">Razorpay (UPI, cards)</h3>{razorpay && <Badge tone="success">Connected · {razorpay.account_ref}</Badge>}</div>
            {!razorpay && canManage && (
              <form className="mt-3 grid gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
                const r = await connectRazorpay(rz.key_id.trim(), rz.key_secret.trim(), rz.webhook_secret.trim());
                setRzRes(r.ok ? { ok: true, url: r.data.webhook_url, events: r.data.events } : { ok: false, error: r.error });
                if (r.ok) router.refresh();
              }); }}>
                <div><Label htmlFor="rz-id">Key ID</Label><Input id="rz-id" placeholder="rzp_live_…" required value={rz.key_id} onChange={(e) => setRz({ ...rz, key_id: e.target.value })} /></div>
                <div><Label htmlFor="rz-sec">Key secret</Label><Input id="rz-sec" type="password" autoComplete="off" required value={rz.key_secret} onChange={(e) => setRz({ ...rz, key_secret: e.target.value })} /></div>
                <div><Label htmlFor="rz-wh">Webhook secret</Label><Input id="rz-wh" type="password" autoComplete="off" required value={rz.webhook_secret} onChange={(e) => setRz({ ...rz, webhook_secret: e.target.value })} /></div>
                <div className="sm:col-span-3"><Button type="submit" disabled={pending}>Connect Razorpay</Button></div>
              </form>
            )}
            <div className="mt-2"><Result r={rzRes} /></div>
          </div>
          <div>
            <div className="flex items-center gap-2"><h3 className="font-semibold">Stripe</h3>{stripe && <Badge tone="success">Connected</Badge>}</div>
            {!stripe && canManage && (
              <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); start(async () => {
                const r = await connectStripe(st.trim(), sk.trim());
                setStRes(r.ok ? { ok: true, url: r.data.webhook_url, events: r.data.events } : { ok: false, error: r.error });
                if (r.ok) router.refresh();
              }); }}>
                <div className="min-w-64 flex-1"><Label htmlFor="st-wh">Webhook signing secret</Label><Input id="st-wh" type="password" autoComplete="off" placeholder="whsec_…" required value={st} onChange={(e) => setSt(e.target.value)} /></div>
                <div className="min-w-64 flex-1"><Label htmlFor="st-sk">Secret key (optional: adds pay links to reminders)</Label><Input id="st-sk" type="password" autoComplete="off" placeholder="sk_live_… or a restricted rk_live_…" value={sk} onChange={(e) => setSk(e.target.value)} /></div>
                <Button type="submit" disabled={pending}>Connect Stripe</Button>
              </form>
            )}
            <div className="mt-2"><Result r={stRes} /></div>
          </div>
        </div>
      </div>
    </Card>
  );
}
