"use client";

import { Button, Input, Select } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { draftDoc, editDoc } from "@/app/(app)/actions";

/** SOP & proposal drafter (ROADMAP-V3 B4). */
export function NewDoc() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState("sop");
  const [brief, setBrief] = useState("");
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); setErr(null); start(async () => {
      const r = await draftDoc(kind, brief); if (!r.ok) return setErr(r.error); router.push(`/docs/${r.data.id}`); }); }}>
      <Select aria-label="Kind" className="w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="sop">SOP with a flowchart</option><option value="proposal">Client proposal</option><option value="checklist">Checklist</option></Select>
      <textarea aria-label="Brief" required minLength={15} rows={4} value={brief} onChange={(e) => setBrief(e.target.value)} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 text-sm"
        placeholder={kind === "proposal" ? "Who it's for, what they need, what you'll do, your price and timeline" : kind === "sop" ? "Which process, who does it, anything that must not be missed" : "What the checklist is for and who uses it"} />
      <Button type="submit" disabled={pending}>{pending ? "Drafting…" : "Draft it"}</Button>
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
    </form>
  );
}

export function DocEditor({ d }: { d: { id: string; title: string; content: string; diagram: string | null; status: string } }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [f, setF] = useState({ title: d.title, content: d.content, diagram: d.diagram ?? "" });
  const save = (status?: string) => start(async () => { await editDoc(d.id, { ...f, diagram: f.diagram || null, ...(status ? { status } : {}) }); router.refresh(); });
  return (
    <div className="space-y-2">
      <Input aria-label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
      <textarea aria-label="Document" rows={24} value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 font-mono text-sm" />
      {d.diagram !== null && <><p className="text-sm font-semibold">Flowchart (Mermaid: paste into mermaid.live, Notion or GitHub to see it drawn)</p>
        <textarea aria-label="Flowchart" rows={10} value={f.diagram} onChange={(e) => setF({ ...f, diagram: e.target.value })} className="w-full rounded-xl border-2 border-line bg-card px-3 py-2 font-mono text-xs" /></>}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={pending} onClick={() => save()}>Save</Button>
        {d.status !== "final" && <Button disabled={pending} onClick={() => save("final")}>Save as final</Button>}
        <a href={`/api/doc-export/${d.id}`} className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 text-sm font-semibold">Download Markdown</a>
      </div>
    </div>
  );
}
