"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useState, useTransition } from "react";
import { createDemo } from "@/app/(app)/actions";

const WEB = process.env.NEXT_PUBLIC_WEB_URL ?? "http://localhost:3200";

export function DemoForm({ packs }: { packs: { key: string; name: string }[] }) {
  const [url, setUrl] = useState("");
  const [pack, setPack] = useState(packs[0]?.key ?? "");
  const [pending, start] = useTransition();
  const [started, setStarted] = useState<number | null>(null);
  const [res, setRes] = useState<{ ok: true; slug: string; name: string; pages: number; seconds: number } | { ok: false; error: string } | null>(null);
  return (
    <form className="space-y-4" onSubmit={(e) => {
      e.preventDefault();
      const t0 = Date.now();
      setStarted(t0);
      setRes(null);
      start(async () => {
        const r = await createDemo(url, pack);
        setRes(r.ok ? { ok: true, slug: r.data.slug, name: r.data.name, pages: r.data.pages_learned, seconds: Math.round((Date.now() - t0) / 1000) }
                    : { ok: false, error: r.error });
      });
    }}>
      <div className="grid gap-4 sm:grid-cols-[1fr_260px]">
        <div><Label htmlFor="demo-url">Prospect&apos;s website</Label><Input id="demo-url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="brightsmile.in" /></div>
        <div><Label htmlFor="demo-pack">Industry pack</Label>
          <Select id="demo-pack" value={pack} onChange={(e) => setPack(e.target.value)}>{packs.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}</Select></div>
      </div>
      <Button type="submit" size="lg" disabled={pending}>{pending ? "Reading their site and building…" : "Build demo"}</Button>
      {pending && started && <p className="text-sm text-muted">Crawling up to 8 pages, building the knowledge base and agent. Usually under a minute.</p>}
      {res?.ok && (
        <div role="status" className="rounded-2xl border-2 border-ink bg-lime p-5 text-lime-ink">
          <p className="font-display text-xl font-bold">Demo ready for {res.name}</p>
          <p className="text-sm">Learned {res.pages} pages in {res.seconds}s. Record your 2-minute video on the demo page.</p>
          <a href={`${WEB}/demo/${res.slug}`} target="_blank" rel="noopener" className="mt-3 inline-block font-semibold underline">Open {WEB.replace(/^https?:\/\//, "")}/demo/{res.slug} →</a>
        </div>
      )}
      {res && !res.ok && <p role="alert" className="text-sm text-danger">{res.error}</p>}
    </form>
  );
}
