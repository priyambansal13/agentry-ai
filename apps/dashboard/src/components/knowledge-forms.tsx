"use client";

import { Button, Input, Label, Textarea } from "@agentry/ui";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addFaq, addKnowledgeText, deleteKnowledge, learnWebsite, uploadKnowledgeFile } from "@/app/(app)/actions";

export function AddFaqForm({ onDone }: { onDone?: () => void }) {
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await addFaq(q, a);
        setMsg(r.ok ? { ok: true, text: "Added. Your agents know this now." } : { ok: false, text: r.error });
        if (r.ok) { setQ(""); setA(""); onDone?.(); }
      });
    }}>
      <div><Label htmlFor="faq-q">Question customers ask</Label><Input id="faq-q" required minLength={3} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Do you offer EMI?" /></div>
      <div><Label htmlFor="faq-a">Your answer</Label><Textarea id="faq-a" required value={a} onChange={(e) => setA(e.target.value)} placeholder="Yes, 0% EMI for 6 months on treatments above ₹20,000." /></div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending}>{pending ? "Adding…" : "Add answer"}</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </form>
  );
}

export function LearnWebsiteForm({ defaultUrl }: { defaultUrl?: string | null }) {
  const [url, setUrl] = useState(defaultUrl ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await learnWebsite(url);
        setMsg(r.ok ? { ok: true, text: `Learned ${r.data.pages_learned} pages.` } : { ok: false, text: r.error });
      });
    }}>
      <div className="min-w-60 flex-1"><Label htmlFor="kb-url">Learn from a website</Label><Input id="kb-url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="yourbusiness.com" /></div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Reading pages…" : "Read website"}</Button>
      {msg && <p role="status" className={`w-full text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </form>
  );
}

export function DeleteDoc({ id, title }: { id: string; title: string }) {
  const [pending, start] = useTransition();
  return (
    <button type="button" aria-label={`Remove ${title}`} disabled={pending}
      onClick={() => confirm(`Remove "${title}" from your agents' knowledge?`) && start(async () => { await deleteKnowledge(id); })}
      className="rounded-lg p-1.5 text-muted hover:bg-lime-soft hover:text-danger disabled:opacity-50">
      <Trash2 className="h-4 w-4" />
    </button>
  );
}


export function AddTextForm() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await addKnowledgeText(title, content);
        setMsg(r.ok ? { ok: true, text: `Added "${title}".` } : { ok: false, text: r.error });
        if (r.ok) { setTitle(""); setContent(""); router.refresh(); }
      });
    }}>
      <div className="space-y-1"><Label htmlFor="kb-title">Title</Label>
        <Input id="kb-title" required minLength={2} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Price list 2026" /></div>
      <div className="space-y-1"><Label htmlFor="kb-text">Text</Label>
        <Textarea id="kb-text" required minLength={20} rows={6} value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="Paste prices, policies, product details, opening hours… anything your agents should know." /></div>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Adding…" : "Add text"}</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
      <p className="text-xs text-muted">Adding text with the same title again replaces it.</p>
    </form>
  );
}

export function UploadFileForm() {
  const router = useRouter();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      const form = e.currentTarget;
      const data = new FormData(form);
      const file = data.get("file") as File | null;
      if (!file || !file.size) return setMsg({ ok: false, text: "Choose a file first" });
      if (file.size > 10 * 1024 * 1024) return setMsg({ ok: false, text: "Files can be up to 10 MB" });
      start(async () => {
        const r = await uploadKnowledgeFile(data);
        setMsg(r.ok ? { ok: true, text: `Learned "${file.name}" (${r.data.characters.toLocaleString("en-IN")} characters).` } : { ok: false, text: r.error });
        if (r.ok) { form.reset(); router.refresh(); }
      });
    }}>
      <div className="space-y-1"><Label htmlFor="kb-file">Upload a file</Label>
        <input id="kb-file" name="file" type="file" accept=".pdf,.docx,.txt,.md,.csv"
          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-2 file:border-ink file:bg-card file:px-3 file:py-1.5 file:font-semibold" /></div>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Reading file…" : "Upload"}</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
      <p className="text-xs text-muted">PDF, Word (.docx), text, Markdown or CSV, up to 10 MB. Uploading a file with the same name replaces it. Scanned PDFs (photos of pages) can't be read yet.</p>
    </form>
  );
}
