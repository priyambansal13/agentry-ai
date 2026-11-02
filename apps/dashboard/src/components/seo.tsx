"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { editSeoArticle, runSeoAudit, writeSeoArticle } from "@/app/(app)/actions";

/** Local SEO (ROADMAP-V3 B1). */
function useGo() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const go = (f: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, after?: (d: unknown) => void) => {
    setErr(null);
    start(async () => { const r = await f(); if (!r.ok) return setErr(r.error ?? "failed"); after?.(r.data); router.refresh(); });
  };
  return { err, pending, go, router };
}
const Err = ({ e }: { e: string | null }) => (e ? <p role="alert" className="text-sm text-danger">{e}</p> : null);

export function RunAudit({ website }: { website: string | null }) {
  const { err, pending, go } = useGo();
  const [url, setUrl] = useState(website ?? "");
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => runSeoAudit(url)); }}>
      <div className="min-w-64 flex-1 space-y-1"><Label htmlFor="su">Website</Label><Input id="su" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://yourbusiness.in" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Checking the site…" : "Audit now"}</Button><Err e={err} />
    </form>
  );
}

export function WriteArticle() {
  const { err, pending, go, router } = useGo();
  const [topic, setTopic] = useState("");
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go(() => writeSeoArticle(topic), (d) => router.push(`/seo/${(d as { id: string }).id}`)); }}>
      <div className="min-w-64 flex-1 space-y-1"><Label htmlFor="at">Topic people search for</Label><Input id="at" required minLength={3} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="AC gas refilling cost" /></div>
      <Button type="submit" disabled={pending}>{pending ? "Writing…" : "Write an article"}</Button><Err e={err} />
    </form>
  );
}

export function ArticleEditor({ a }: { a: { id: string; title: string; meta: string | null; body: string; status: string } }) {
  const { err, pending, go } = useGo();
  const [f, setF] = useState({ title: a.title, meta: a.meta ?? "", body: a.body });
  return (
    <div className="space-y-2">
      <Input aria-label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
      <Input aria-label="Meta description" value={f.meta} onChange={(e) => setF({ ...f, meta: e.target.value })} placeholder="Meta description (140-155 characters)" />
      <p className="text-xs text-muted">{f.meta.length} characters</p>
      <textarea aria-label="Article" rows={22} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 font-mono text-sm" />
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={pending} onClick={() => go(() => editSeoArticle(a.id, f))}>Save</Button>
        {a.status !== "approved" && <Button disabled={pending} onClick={() => go(() => editSeoArticle(a.id, { ...f, status: "approved" }))}>Save and approve</Button>}
        {a.status === "approved" && <Button variant="secondary" disabled={pending} onClick={() => go(() => editSeoArticle(a.id, { status: "published" }))}>Mark published</Button>}
        <a href={`/api/seo-export/${a.id}?format=html`} className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 text-sm font-semibold">HTML</a>
        <a href={`/api/seo-export/${a.id}?format=md`} className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 text-sm font-semibold">Markdown</a>
      </div>
      <Err e={err} />
    </div>
  );
}
