"use client";

import { Button } from "@agentry/ui";
import { ArrowRight, Loader2, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { attribution, track } from "./analytics";
import { useTurnstile } from "./turnstile";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

/** Instant demo: website -> /try/{id}. */
export function TryForm({ site = "" }: { site?: string }) {
  const router = useRouter();
  const [url, setUrl] = useState(site);
  const [state, setState] = useState<{ kind: "idle" | "sending" | "error"; message?: string }>({ kind: "idle" });
  const [hp, setHp] = useState("");
  const captcha = useTurnstile();
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (captcha.enabled && !captcha.token) return setState({ kind: "error", message: "Please complete the quick human check." });
    setState({ kind: "sending" });
    const src = Object.entries(attribution()).map(([k, v]) => `${k}=${v}`).join("; ");
    const r = await fetch(`${API}/public/try`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, token: captcha.token ?? undefined, source: src || undefined, company_url: hp || undefined }) });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      captcha.reset();
      return setState({ kind: "error", message: typeof body.detail === "string" ? body.detail : "Please check the address and try again." });
    }
    track("instant_demo_start");
    router.push(`/try/${body.id}`);
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
      {captcha.script}
      <div><label htmlFor="t-url" className="mb-1 block text-sm font-semibold">Your website</label>
        <input id="t-url" required inputMode="url" placeholder="yourbusiness.in" value={url} onChange={(e) => setUrl(e.target.value)}
          className="h-12 w-full rounded-xl border-2 border-ink bg-card px-4 text-base placeholder:text-muted focus:outline-none" /></div>
      <input type="text" name="company_url" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden" value={hp} onChange={(e) => setHp(e.target.value)} />
      <Button type="submit" size="lg" className="h-12 rounded-xl px-6" disabled={state.kind === "sending"}>
        {state.kind === "sending" ? <><Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" /> Reading your website…</> : <>Build my assistant <ArrowRight aria-hidden="true" className="h-5 w-5" /></>}
      </Button>
      {captcha.enabled && <div ref={captcha.box} className="sm:col-span-2" />}
      {state.kind === "error" && <p role="alert" className="text-sm text-danger sm:col-span-2">{state.message}</p>}
    </form>
  );
}

type Demo = { id: string; url: string; domain: string; name: string; brand: { color?: string; logo?: string }; expired: boolean;
  messages_left: number; pages: string[]; suggestions: string[] };
type Msg = { role: "user" | "assistant"; content: string };

/** White or dark text, whichever reads better on the brand colour. */
function textOn(hex: string): string {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b! > 0.4 ? "#111" : "#fff";
}

export function TryChat({ id }: { id: string }) {
  const [d, setD] = useState<Demo | null>(null);
  const [missing, setMissing] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      const r = await fetch(`${API}/public/try/${id}`, { cache: "no-store" });
      if (!r.ok) return setMissing(true);
      const x: Demo = await r.json();
      setD(x);
      setMsgs([{ role: "assistant", content: `Hi! I'm the assistant for ${x.name}. Ask me anything a customer would.` }]);
    })();
  }, [id]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [msgs, busy]);

  async function send(text: string) {
    if (!text.trim() || busy || !d) return;
    const next = [...msgs, { role: "user" as const, content: text.trim() }];
    setMsgs(next); setInput(""); setBusy(true); setErr(null);
    const r = await fetch(`${API}/public/try/${id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: next.slice(1) }) });
    const body = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) return setErr(typeof body.detail === "string" ? body.detail : "The assistant is busy: try again.");
    setMsgs([...next, { role: "assistant", content: body.reply }]);
    setD({ ...d, messages_left: body.messages_left });
    if (next.length === 2) track("instant_demo_chat");
  }

  if (missing) return <div className="py-20 text-center"><h1 className="font-display text-3xl font-bold">This demo isn&apos;t available</h1>
    <p className="mt-2 text-ink-soft">Previews last 24 hours.</p><a href="/try" className="mt-4 inline-block font-semibold underline">Make a new one</a></div>;
  if (!d) return <div role="status" className="flex min-h-[40vh] items-center justify-center gap-3"><Loader2 aria-hidden="true" className="h-6 w-6 animate-spin" /> Opening…</div>;
  const colour = d.brand.color ?? "#1f2a1a";
  const ended = d.expired || d.messages_left === 0;

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_380px] lg:items-start">
      <div>
        <p className="font-hand text-2xl text-muted">your assistant, from {d.domain}</p>
        <h1 className="mt-1 font-display text-4xl font-bold tracking-tight sm:text-5xl">{d.name}&apos;s AI assistant</h1>
        <p className="mt-4 max-w-xl text-lg text-ink-soft">Play a customer. It answers only from the {d.pages.length} page{d.pages.length === 1 ? "" : "s"} we read on your
          website, and says so when it doesn&apos;t know.</p>
        <p className="mt-6 text-sm font-semibold uppercase tracking-wide text-muted">Try asking</p>
        <div className="mt-2 flex flex-wrap gap-2">{d.suggestions.map((s) => (
          <button key={s} type="button" disabled={busy || ended} onClick={() => void send(s)}
            className="rounded-full border-2 border-ink bg-card px-4 py-2 text-sm font-medium hover:bg-lime-soft disabled:opacity-50">{s}</button>))}</div>
        <div className="mt-8 rounded-3xl border-2 border-ink bg-lime p-6 text-lime-ink">
          <h2 className="font-display text-2xl font-bold">Like it? The real one does more.</h2>
          <ul className="mt-3 list-disc space-y-1 pl-5">
            <li>Answers on your website <strong>and WhatsApp</strong>, day and night</li>
            <li>Books appointments into your calendar and takes leads</li>
            <li>Hands over to your team when it should; you approve replies at first</li>
          </ul>
          <a href="#demo" className="mt-5 inline-flex h-12 items-center gap-2 rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90">Switch it on for my business <ArrowRight aria-hidden="true" className="h-5 w-5" /></a>
        </div>
      </div>

      <section aria-label={`Chat with ${d.name}'s assistant`} className="overflow-hidden rounded-[2rem] border-2 border-ink bg-card shadow-[6px_6px_0_0_var(--ink)]">
        <header className="flex items-center gap-3 px-5 py-4" style={{ background: colour, color: textOn(colour) }}>
          <span className="grid h-9 w-9 place-items-center rounded-full bg-black/15 font-bold" aria-hidden="true">{d.name.charAt(0)}</span>
          <div><p className="font-semibold leading-tight">{d.name}</p><p className="text-xs opacity-80">usually replies instantly</p></div>
        </header>
        <div className="h-[26rem] space-y-3 overflow-y-auto bg-paper p-4" aria-live="polite">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <p className={`max-w-[85%] whitespace-pre-line rounded-2xl px-4 py-2 text-sm ${m.role === "user" ? "bg-ink text-paper" : "border-2 border-line bg-card"}`}>{m.content}</p>
            </div>))}
          {busy && <p className="flex items-center gap-2 text-sm text-muted"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> typing…</p>}
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
          <div ref={end} />
        </div>
        <form className="flex gap-2 border-t-2 border-line p-3" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
          <label htmlFor="t-msg" className="sr-only">Your message</label>
          <input id="t-msg" value={input} onChange={(e) => setInput(e.target.value)} maxLength={1000} disabled={ended}
            placeholder={ended ? "This preview has ended" : "Ask like a customer would…"}
            className="h-11 flex-1 rounded-xl border-2 border-line bg-paper px-3 text-sm focus:border-ink focus:outline-none" />
          <Button type="submit" aria-label="Send" disabled={busy || ended || !input.trim()} className="h-11 w-11 rounded-xl p-0"><Send aria-hidden="true" className="h-5 w-5" /></Button>
        </form>
        <p className="px-4 pb-3 text-xs text-muted">{ended ? "Preview ended." : `${d.messages_left} messages left in this preview.`} Preview only: nothing is sent to anyone.</p>
      </section>
    </div>
  );
}
