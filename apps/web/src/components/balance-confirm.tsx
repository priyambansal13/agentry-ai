"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

type View = { firm: string; client: string; party: string; as_of: string; kind: string; balance: number; side: string; answered: boolean;
  answer: { status: string; their_balance: number | null } | null };

const day = (d: string) => new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

/** The party's page: agree, or give the balance in their books (and attach their statement). One tap for most. */
export function BalanceConfirm({ token }: { token: string }) {
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [differs, setDiffers] = useState(false);
  const [fig, setFig] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const r = await fetch(`${API}/public/confirm/${token}`, { cache: "no-store" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) return setErr(typeof body.detail === "string" ? body.detail : "This link isn't working.");
      setV(body);
    })();
  }, [token]);

  async function send(agree: boolean) {
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.append("agree", String(agree));
    if (!agree) form.append("their_balance", fig.replace(/,/g, ""));
    if (note.trim()) form.append("note", note.trim());
    if (file) form.append("file", file);
    const r = await fetch(`${API}/public/confirm/${token}`, { method: "POST", body: form });
    const body = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) return setErr(typeof body.detail === "string" ? body.detail : "That didn't go through: please try again, or reply to the email.");
    setDone(body.status === "agreed" ? "Thank you: you've confirmed the balance." : "Thank you: we've noted your balance and will reconcile the difference.");
  }

  if (err && !v) return <div className="mx-auto max-w-md px-4 py-24 text-center"><h1 className="font-display text-2xl font-bold">This link isn&apos;t working</h1><p className="mt-2 text-ink-soft">{err}</p></div>;
  if (!v) return <div className="flex min-h-[50vh] items-center justify-center gap-2"><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> Opening…</div>;
  const figOk = fig.trim() !== "" && Number.isFinite(Number(fig.replace(/,/g, ""))) && Number(fig.replace(/,/g, "")) >= 0;
  return (
    <main className="mx-auto max-w-xl space-y-6 px-4 py-10">
      <header><p className="text-sm text-muted">From {v.firm}, auditors of {v.client}</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Balance confirmation</h1></header>
      <section className="rounded-2xl border-2 border-ink bg-card p-5 shadow-[4px_4px_0_0_var(--ink)]">
        <p className="text-sm text-ink-soft">For {v.party}, as at {day(v.as_of)}, as per {v.client}&apos;s books:</p>
        <p className="mt-2 font-display text-2xl font-bold">{v.side}</p>
        <p className="mt-2 text-xs text-muted">This is a request for information for the audit, not a demand for payment.</p>
      </section>
      {done || v.answered ? (
        <p className="flex items-center gap-2 rounded-2xl border-2 border-success bg-card p-4 font-semibold"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" />
          {done ?? "Thank you: we have your reply."}</p>
      ) : (
        <section className="space-y-4" aria-label="Your reply">
          {!differs && <div className="flex flex-wrap gap-3">
            <button type="button" disabled={busy} onClick={() => void send(true)} className="rounded-xl border-2 border-ink bg-lime px-5 py-3 font-semibold disabled:opacity-60">
              {busy ? "Sending…" : "Yes, this matches our books"}</button>
            <button type="button" onClick={() => setDiffers(true)} className="rounded-xl border-2 border-ink px-5 py-3 font-semibold">No, our balance is different</button></div>}
          {differs && <form className="space-y-3 rounded-2xl border-2 border-line bg-card p-4" onSubmit={(e) => { e.preventDefault(); void send(false); }}>
            <label className="block text-sm font-semibold" htmlFor="fig">The balance in your books (₹)</label>
            <input id="fig" inputMode="decimal" className="w-full rounded-xl border-2 border-line px-3 py-2" value={fig} onChange={(e) => setFig(e.target.value)} placeholder="e.g. 4,60,600" />
            <label className="block text-sm font-semibold" htmlFor="note">What explains the difference? (optional)</label>
            <textarea id="note" rows={3} className="w-full rounded-xl border-2 border-line px-3 py-2 text-sm" value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. our payment of ₹25,000 on 30 March; invoice 388 received in April" />
            <label className="block text-sm font-semibold" htmlFor="file">Your statement of account (optional)</label>
            <input id="file" type="file" accept=".pdf,.xlsx,.csv,.jpg,.jpeg,.png" className="block text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <div className="flex flex-wrap gap-3 pt-1">
              <button type="submit" disabled={busy || !figOk} className="rounded-xl border-2 border-ink bg-lime px-5 py-2.5 font-semibold disabled:opacity-60">{busy ? "Sending…" : "Send our balance"}</button>
              <button type="button" onClick={() => setDiffers(false)} className="text-sm underline">back</button></div>
          </form>}
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
        </section>
      )}
      <footer className="pt-6 text-center text-xs text-muted">This private link is just for {v.party}: your reply goes directly to {v.firm}. · powered by Agentry</footer>
    </main>
  );
}
