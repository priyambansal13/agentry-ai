"use client";

import { Badge, Button, Card, Input, Label, Select, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import {
  approveContentReady, deleteContent, dropContentMoment, learnBrandVoice, moveContentPost, retryContent, reviewContentPost, sampleContent,
  saveBrandKit, scheduleContent, uploadBrandLogo,
} from "@/app/(app)/actions";
import { PLATFORM } from "@/lib/format";

type Msg = { ok: boolean; text: string } | null;
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;


/** Upload a recording (streamed to the API: videos are big) or try the sample podcast. */
export function NewContent() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [owns, setOwns] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const [uploading, setUploading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setMsg({ ok: true, text: `Uploading ${(file.size / 1024 / 1024).toFixed(1)} MB…` });
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title || file.name.replace(/\.[^.]+$/, ""));
    fd.append("owns_rights", String(owns));
    const res = await fetch("/api/content-upload", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    setUploading(false);
    if (!res.ok) return setMsg({ ok: false, text: typeof body.detail === "string" ? body.detail : "Upload failed" });
    router.push(`/content/${body.id}`);
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div><Label htmlFor="ct-title">Title</Label><Input id="ct-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Podcast episode 12" /></div>
        <div><Label htmlFor="ct-file">Video, audio or transcript (MP4, MOV, MP3, M4A, WAV, SRT, VTT, TXT)</Label>
          <input id="ct-file" type="file" accept="video/*,audio/*,.srt,.vtt,.txt" className="block text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
        <label className="flex items-start gap-2 text-sm sm:col-span-2">
          <input type="checkbox" className="mt-1" checked={owns} onChange={(e) => setOwns(e.target.checked)} />
          <span>This is our own recording (or we have the rights to post from it).</span>
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" disabled={!file || !owns || uploading}>{uploading ? "Uploading…" : "Make posts"}</Button>
          <span className="text-sm text-muted">or</span>
          <Button type="button" variant="secondary" disabled={pending || uploading} onClick={() => start(async () => {
            const r = await sampleContent();
            if (!r.ok) return setMsg({ ok: false, text: r.error });
            router.push(`/content/${r.data.id}`);
          })}>Try a sample podcast</Button>
          <Status msg={msg} />
        </div>
      </form>
      <p className="text-sm text-muted">Agentry transcribes it, picks the 10 best moments and writes a post for each platform with a branded image.
        Nothing is posted until you approve it. A 45-minute recording takes a few minutes.</p>
    </div>
  );
}

export function SourceActions({ id, failed }: { id: string; failed: boolean }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {failed && <Button size="sm" disabled={pending} onClick={() => start(async () => {
        const r = await retryContent(id);
        setMsg(r.ok ? { ok: true, text: "Trying again" } : { ok: false, text: r.error });
        router.refresh();
      })}>Try again</Button>}
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => {
        if (!confirm("Delete this recording, its transcript and every post made from it? Posts already published stay on the platforms.")) return;
        start(async () => {
          const r = await deleteContent(id);
          if (!r.ok) return setMsg({ ok: false, text: r.error });
          router.push("/content");
        });
      }}>Delete</Button>
      <Status msg={msg} />
    </span>
  );
}

export function BulkActions({ sourceId, ready, approvedUnscheduled }: { sourceId: string; ready: number; approvedUnscheduled: number }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {ready > 0 && <Button disabled={pending} onClick={() => {
        if (!confirm(`Approve all ${ready} posts that passed the checks? Posts that need attention stay for you.`)) return;
        start(async () => {
          const r = await approveContentReady(sourceId);
          setMsg(r.ok ? { ok: true, text: `${r.data.approved} approved` } : { ok: false, text: r.error });
          router.refresh();
        });
      }}>Approve {ready} checked posts</Button>}
      {approvedUnscheduled > 0 && <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
        const r = await scheduleContent(sourceId);
        setMsg(r.ok ? { ok: true, text: `${r.data.scheduled} posts added to the calendar` } : { ok: false, text: r.error });
        router.refresh();
      })}>Schedule {approvedUnscheduled} approved</Button>}
      <Status msg={msg} />
    </span>
  );
}

export function DropMoment({ id }: { id: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button type="button" className="text-xs text-muted underline hover:text-danger" disabled={pending} onClick={() => {
      if (!confirm("Drop this moment and its posts?")) return;
      start(async () => { await dropContentMoment(id); router.refresh(); });
    }}>Drop this moment</button>
  );
}

export type ContentPost = {
  id: string; platform: "linkedin" | "instagram" | "x"; body: string; hashtags: string[]; review: "pending" | "needs_attention" | "approved" | "dropped";
  critic: { ok?: boolean; problems?: string[]; attempts?: number; edited_by_person?: boolean }; edited: boolean; has_image: boolean;
  scheduled_at: string | null; published_at: string | null; publish_ref: string | null; publish_error: string | null;
};

const LIMIT = { linkedin: 3000, instagram: 2200, x: 280 };

export function PostCard({ p, canEdit }: { p: ContentPost; canEdit: boolean }) {
  const router = useRouter();
  const [body, setBody] = useState(p.body);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const changed = body.trim() !== p.body.trim();
  const open = p.review === "pending" || p.review === "needs_attention";
  const length = body.length + p.hashtags.reduce((n, t) => n + t.length + 2, 0);
  function act(action: "approve" | "drop" | "reopen" | "regenerate") {
    start(async () => {
      const r = await reviewContentPost(p.id, action, action === "approve" && changed ? body : undefined);
      setMsg(r.ok ? { ok: true, text: { approve: "Approved", drop: "Dropped", reopen: "Back in review", regenerate: "Rewritten" }[action] } : { ok: false, text: r.error });
      if (r.ok) router.refresh();
    });
  }
  return (
    <Card className="flex min-w-0 flex-col p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{PLATFORM[p.platform]}</span>
        <Badge tone={p.review === "approved" ? "lime" : p.review === "needs_attention" ? "warning" : "neutral"}>
          {{ pending: "To review", needs_attention: "Needs attention", approved: "Approved", dropped: "Dropped" }[p.review]}
        </Badge>
        {p.published_at && <Badge tone="success">Published{p.publish_ref?.startsWith("test-mode") ? " (test mode)" : ""}</Badge>}
        {!p.published_at && p.scheduled_at && <span className="text-xs text-muted">{new Date(p.scheduled_at).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>}
      </div>
      {p.has_image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/api/content-image/${p.id}`} alt={`Quote card for the ${PLATFORM[p.platform]} post`} loading="lazy"
          className="mt-3 w-full rounded-lg border border-line" />
      )}
      {p.review === "needs_attention" && (
        <p role="alert" className="mt-3 rounded-lg border-2 border-warning px-3 py-2 text-xs text-warning">
          The checks stopped this draft: {(p.critic.problems ?? []).join("; ") || "see below"}. Edit it, rewrite it, or drop it.
        </p>
      )}
      <Textarea aria-label={`${PLATFORM[p.platform]} post`} className="mt-3 text-sm" rows={p.platform === "x" ? 4 : 8} value={body}
        onChange={(e) => setBody(e.target.value)} disabled={!canEdit || !open} />
      <p className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-muted">
        <span>{p.hashtags.map((t) => `#${t}`).join(" ")}</span>
        <span className={length > LIMIT[p.platform] ? "text-danger" : ""}>{length}/{LIMIT[p.platform]}</span>
      </p>
      {canEdit && !p.published_at && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {open && <Button size="sm" disabled={pending || (p.review === "needs_attention" && !changed)} onClick={() => act("approve")}>{changed ? "Approve with edit" : "Approve"}</Button>}
          {open && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("regenerate")}>Rewrite</Button>}
          {open && <Button size="sm" variant="ghost" disabled={pending} onClick={() => act("drop")}>Drop</Button>}
          {!open && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("reopen")}>Back to review</Button>}
          <Status msg={msg} />
        </div>
      )}
    </Card>
  );
}

export function MovePost({ id, at }: { id: string; at: string }) {
  const router = useRouter();
  const local = new Date(new Date(at).getTime() - new Date(at).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [value, setValue] = useState(local);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Input type="datetime-local" aria-label="Move to" className="h-8 w-auto text-xs" value={value} onChange={(e) => setValue(e.target.value)} />
      {value !== local && <Button size="sm" variant="secondary" disabled={pending} onClick={() => start(async () => {
        const r = await moveContentPost(id, new Date(value).toISOString());
        setMsg(r.ok ? null : { ok: false, text: r.error });
        router.refresh();
      })}>Move</Button>}
      <Status msg={msg} />
    </span>
  );
}

export function ScheduleAll({ count }: { count: number }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  if (!count) return null;
  return (
    <span className="inline-flex items-center gap-2">
      <Button disabled={pending} onClick={() => start(async () => {
        const r = await scheduleContent();
        setMsg(r.ok ? { ok: true, text: `${r.data.scheduled} scheduled` } : { ok: false, text: r.error });
        router.refresh();
      })}>Schedule {count} approved</Button>
      <Status msg={msg} />
    </span>
  );
}

export type BrandKit = { primary_color: string; accent_color: string; template: "bold" | "light" | "split"; handle: string | null;
  platforms: ("linkedin" | "instagram" | "x")[]; moments_per_source: number; voice: string | null; voice_samples: number; has_logo: boolean };

export function BrandForm({ kit }: { kit: BrandKit }) {
  const router = useRouter();
  const [k, setK] = useState(kit);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const [stamp, setStamp] = useState(0);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); start(async () => {
        const r = await saveBrandKit({ primary_color: k.primary_color, accent_color: k.accent_color, template: k.template, handle: k.handle || "",
                                        platforms: k.platforms, moments_per_source: k.moments_per_source });
        setMsg(r.ok ? { ok: true, text: `Saved${r.data.images_redrawn ? `: ${r.data.images_redrawn} images redrawn` : ""}` } : { ok: false, text: r.error });
        setStamp(Date.now());
        router.refresh();
      }); }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label htmlFor="bk-primary">Main colour</Label>
            <div className="flex gap-2"><input type="color" aria-label="Main colour picker" value={k.primary_color} onChange={(e) => setK({ ...k, primary_color: e.target.value })} className="h-11 w-14 rounded-lg border-2 border-line" />
              <Input id="bk-primary" value={k.primary_color} onChange={(e) => setK({ ...k, primary_color: e.target.value })} /></div></div>
          <div><Label htmlFor="bk-accent">Accent colour</Label>
            <div className="flex gap-2"><input type="color" aria-label="Accent colour picker" value={k.accent_color} onChange={(e) => setK({ ...k, accent_color: e.target.value })} className="h-11 w-14 rounded-lg border-2 border-line" />
              <Input id="bk-accent" value={k.accent_color} onChange={(e) => setK({ ...k, accent_color: e.target.value })} /></div></div>
          <div><Label htmlFor="bk-template">Card style</Label>
            <Select id="bk-template" value={k.template} onChange={(e) => setK({ ...k, template: e.target.value as BrandKit["template"] })}>
              <option value="bold">Bold: quote on your main colour</option><option value="light">Light: on white, accent bar</option>
              <option value="split">Split: accent panel beside the quote</option>
            </Select></div>
          <div><Label htmlFor="bk-handle">Handle on the cards</Label><Input id="bk-handle" value={k.handle ?? ""} onChange={(e) => setK({ ...k, handle: e.target.value })} placeholder="@yourbusiness" /></div>
          <fieldset className="sm:col-span-2"><legend className="mb-1.5 text-sm font-medium">Platforms</legend>
            <div className="flex flex-wrap gap-4 text-sm">{(["linkedin", "instagram", "x"] as const).map((pl) => (
              <label key={pl} className="flex items-center gap-2"><input type="checkbox" checked={k.platforms.includes(pl)}
                onChange={(e) => setK({ ...k, platforms: e.target.checked ? [...k.platforms, pl] : k.platforms.filter((x) => x !== pl) })} />{PLATFORM[pl]}</label>
            ))}</div></fieldset>
          <div><Label htmlFor="bk-moments">Moments per recording</Label>
            <Input id="bk-moments" type="number" min={3} max={20} value={k.moments_per_source} onChange={(e) => setK({ ...k, moments_per_source: Number(e.target.value) })} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-3"><Button type="submit" disabled={pending}>Save brand kit</Button><Status msg={msg} /></div>
      </form>
      <div className="space-y-2">
        <p className="text-sm font-medium">Preview</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/api/content-preview?platform=instagram&v=${stamp}`} alt="A sample quote card in your brand" className="w-full rounded-lg border border-line" />
        <LogoUpload onDone={() => setStamp(Date.now())} hasLogo={kit.has_logo} />
      </div>
    </div>
  );
}

function LogoUpload({ onDone, hasLogo }: { onDone: () => void; hasLogo: boolean }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <div>
      <Label htmlFor="bk-logo">{hasLogo ? "Replace logo" : "Logo"} (PNG or JPG, transparent PNG looks best)</Label>
      <input id="bk-logo" type="file" accept="image/png,image/jpeg" className="block text-sm" disabled={pending} onChange={(e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        start(async () => {
          const fd = new FormData();
          fd.append("file", f);
          const r = await uploadBrandLogo(fd);
          setMsg(r.ok ? { ok: true, text: `Logo saved${r.data.images_redrawn ? `: ${r.data.images_redrawn} images redrawn` : ""}` } : { ok: false, text: r.error });
          onDone();
          router.refresh();
        });
      }} />
      <Status msg={msg} />
    </div>
  );
}

export function VoiceForm({ voice, samples }: { voice: string | null; samples: number }) {
  const router = useRouter();
  const [posts, setPosts] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <div className="space-y-3">
      {voice ? (
        <div className="rounded-xl bg-paper px-4 py-3 text-sm"><p className="mb-1 font-medium">How you write (learned from {samples} posts)</p>
          <p className="whitespace-pre-wrap text-ink-soft">{voice}</p></div>
      ) : <p className="text-sm text-muted">Not learned yet: drafts use a clear, warm, direct tone.</p>}
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); start(async () => {
        const r = await learnBrandVoice(posts);
        setMsg(r.ok ? (r.data.learned ? { ok: true, text: `Learned from ${r.data.samples} posts` } : { ok: false, text: r.data.reason ?? "Couldn't learn" }) : { ok: false, text: r.error });
        if (r.ok && r.data.learned) setPosts("");
        router.refresh();
      }); }}>
        <Label htmlFor="bk-posts">Paste 10–20 of your past posts, separated by a blank line</Label>
        <Textarea id="bk-posts" rows={8} value={posts} onChange={(e) => setPosts(e.target.value)} />
        <div className="flex flex-wrap items-center gap-3"><Button type="submit" variant="secondary" disabled={pending || posts.trim().length < 50}>Learn our voice</Button><Status msg={msg} /></div>
      </form>
    </div>
  );
}
