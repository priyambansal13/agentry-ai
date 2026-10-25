"use client";

import { Button, Input, Label, Select, Textarea } from "@agentry/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { hqBuildDemoFromRequest, hqPreviewDemoEmail, hqSendDemo, hqUpdateDemoRequest } from "@/app/(app)/actions";

export type DemoRequest = {
  id: string; name: string; email: string; phone: string | null; company: string | null; website: string | null; niche: string | null;
  message: string | null; status: string; notes: string | null; demo_slug: string | null; demo_url: string | null; video_url: string | null;
  demo_sent_at: string | null; followups_sent: number; follow_up_days: number[]; client_org_id: string | null; lead_id: string | null;
  suggested_pack: string | null; link_problem: string | null; created_at: string; updated_at: string;
  proposals: { id: string; url: string; sent_at: string; first_viewed_at: string | null; views: number }[];
  messages: { kind: "reply" | "auto_reply" | "bounce"; from_address: string | null; subject: string | null; snippet: string | null; received_at: string }[];
};


function useAct() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const act = (fn: () => Promise<{ ok: boolean; error?: string }>, done: string) => start(async () => {
    const r = await fn();
    setMsg(r.ok ? { ok: true, text: done } : { ok: false, text: r.error ?? "Something went wrong" });
    router.refresh();
  });
  return { pending, msg, act };
}

function Note({ msg }: { msg: { ok: boolean; text: string } | null }) {
  return msg ? <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm text-success" : "text-sm text-danger"}>{msg.text}</p> : null;
}

export function StatusButtons({ d }: { d: DemoRequest }) {
  const { pending, msg, act } = useAct();
  // reopening goes back to the furthest step really reached (a demo that was never sent isn't "in talks")
  const reopenTo = d.demo_sent_at ? "in_talks" : d.demo_slug ? "demo_built" : "new";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {d.status === "demo_sent" && <Button size="sm" disabled={pending} onClick={() => act(() => hqUpdateDemoRequest(d.id, { status: "in_talks" }), "Marked in talks: follow-ups stopped")}>They replied</Button>}
        {!["won", "lost"].includes(d.status) && <Button size="sm" variant="secondary" disabled={pending}
          onClick={() => confirm("Mark this request as lost? Follow-ups stop.") && act(() => hqUpdateDemoRequest(d.id, { status: "lost" }), "Marked lost")}>Lost</Button>}
        {["won", "lost"].includes(d.status) && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act(() => hqUpdateDemoRequest(d.id, { status: reopenTo }), "Reopened")}>Reopen</Button>}
      </div>
      <Note msg={msg} />
    </div>
  );
}

export function NotesForm({ d }: { d: DemoRequest }) {
  const [notes, setNotes] = useState(d.notes ?? "");
  const { pending, msg, act } = useAct();
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); act(() => hqUpdateDemoRequest(d.id, { notes }), "Notes saved"); }}>
      <Label htmlFor="notes">Notes (only Agentry sees these)</Label>
      <Textarea id="notes" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Call notes, what they want first, budget…" />
      <div className="flex items-center gap-3"><Button type="submit" size="sm" variant="secondary" disabled={pending}>Save notes</Button><Note msg={msg} /></div>
    </form>
  );
}

export function BuildDemo({ d, packs }: { d: DemoRequest; packs: { key: string; name: string }[] }) {
  const [url, setUrl] = useState(d.website ?? "");
  const [pack, setPack] = useState(d.suggested_pack ?? packs[0]?.key ?? "");
  const { pending, msg, act } = useAct();
  if (d.demo_url) {
    return <p className="text-sm">Demo: <a className="font-semibold underline" href={d.demo_url} target="_blank" rel="noopener">{d.demo_url.replace(/^https?:\/\//, "")} →</a></p>;
  }
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); act(() => hqBuildDemoFromRequest(d.id, url, pack), "Demo built"); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><Label htmlFor="b-url">Their website</Label><Input id="b-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></div>
        <div><Label htmlFor="b-pack">Industry</Label>
          <Select id="b-pack" value={pack} onChange={(e) => setPack(e.target.value)}>{packs.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}</Select></div>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending || url.length < 4}>{pending ? "Reading their website…" : "Build their demo"}</Button>
        <Note msg={msg} />
      </div>
      <p className="text-xs text-muted">Reads their site (up to 8 pages) and makes a demo assistant with their name, services and colours.</p>
    </form>
  );
}

export function SendDemo({ d }: { d: DemoRequest }) {
  const [video, setVideo] = useState(d.video_url ?? "");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<{ to: string; subject: string; body: string } | null>(null);
  const { pending, msg, act } = useAct();
  if (!d.demo_url) return <p className="text-sm text-muted">Build their demo first.</p>;
  return (
    <div className="space-y-3">
      {d.link_problem && <p role="alert" className="rounded-xl border-2 border-warning px-3 py-2 text-sm text-warning">{d.link_problem}</p>}
      <div><Label htmlFor="s-video">Walkthrough video link (optional)</Label>
        <Input id="s-video" value={video} onChange={(e) => setVideo(e.target.value)} placeholder="https://www.loom.com/share/…" /></div>
      <div><Label htmlFor="s-note">A personal line (optional)</Label>
        <Textarea id="s-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. I set it up to answer questions about your root canal pricing." /></div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" disabled={pending} onClick={() => act(async () => {
          const r = await hqPreviewDemoEmail(d.id, video, note);
          if (r.ok) setPreview(r.data);
          return r;
        }, "Preview below")}>Preview email</Button>
        <Button disabled={pending || Boolean(d.link_problem)} onClick={() => confirm(`Send the demo to ${d.email}?`) && act(() => hqSendDemo(d.id, video, note), "Sent. Follow-ups are scheduled.")}>
          {d.demo_sent_at ? "Send again" : "Send demo"}
        </Button>
        <Note msg={msg} />
      </div>
      {preview && (
        <div className="rounded-xl border-2 border-line bg-paper p-4 text-sm">
          <p className="text-muted">To {preview.to} · <strong className="text-ink">{preview.subject}</strong></p>
          <pre className="mt-2 font-sans whitespace-pre-wrap">{preview.body}</pre>
        </div>
      )}
    </div>
  );
}

export function ConvertLink({ d }: { d: DemoRequest }) {
  if (d.client_org_id) return <Link className="text-sm font-semibold underline" href={`/hq/${d.client_org_id}`}>Open their client page →</Link>;
  return <Link className="inline-flex h-10 items-center rounded-xl border-2 border-ink bg-lime px-4 text-sm font-semibold" href={`/hq/new?from=${d.id}`}>Convert to client →</Link>;
}

