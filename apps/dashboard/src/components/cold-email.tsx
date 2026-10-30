"use client";

import { Badge, Button, Card, Input, Label, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { addSendingMailbox, approveReadyLines, changeSendingMailbox, createColdCampaign, pauseColdCampaign, reviewProspect, simulateColdReply,
  startColdCampaign, uploadColdCampaign } from "@/app/(app)/actions";

type Msg = { ok: boolean; text: string } | null;

/** A new prospect list: a business search (Google Places once connected; the sample list until then) or an uploaded file. */
export function NewColdCampaign() {
  const router = useRouter();
  const [mode, setMode] = useState<"search" | "file">("search");
  const [name, setName] = useState("");
  const [query, setQuery] = useState("dental clinic");
  const [city, setCity] = useState("Pune");
  const [limit, setLimit] = useState(50);
  const [minRating, setMinRating] = useState("4.0");
  const [minReviews, setMinReviews] = useState("20");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    start(async () => {
      const filters = { min_rating: minRating ? Number(minRating) : null, min_reviews: minReviews ? Number(minReviews) : null };
      let r;
      if (mode === "search") {
        r = await createColdCampaign({ name: name || `${query} in ${city}`, query, city, limit, ...filters });
      } else {
        if (!file) return setMsg({ ok: false, text: "Choose a file first" });
        const fd = new FormData();
        fd.append("file", file);
        fd.append("name", name || file.name.replace(/\.[^.]+$/, ""));
        if (filters.min_rating) fd.append("min_rating", String(filters.min_rating));
        if (filters.min_reviews !== null) fd.append("min_reviews", String(filters.min_reviews));
        r = await uploadColdCampaign(fd);
      }
      if (!r.ok) return setMsg({ ok: false, text: r.error });
      router.push(`/cold-email/${r.data.id}`);
    });
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="inline-grid grid-cols-2 rounded-xl border-2 border-line p-1 text-sm" role="tablist">
        {(["search", "file"] as const).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
            className={`rounded-lg px-4 py-1.5 font-medium transition-colors ${mode === m ? "bg-ink text-paper" : "text-muted hover:text-ink"}`}>
            {m === "search" ? "Search businesses" : "Upload a list"}
          </button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Label htmlFor="ce-name">Campaign name</Label>
          <Input id="ce-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={mode === "search" ? `${query} in ${city}` : "e.g. Apollo export, October"} /></div>
        {mode === "search" ? (
          <>
            <div><Label htmlFor="ce-q">Type of business</Label><Input id="ce-q" required minLength={2} value={query} onChange={(e) => setQuery(e.target.value)} /></div>
            <div><Label htmlFor="ce-city">City or area</Label><Input id="ce-city" required minLength={2} value={city} onChange={(e) => setCity(e.target.value)} /></div>
            <div><Label htmlFor="ce-limit">How many businesses to look at</Label>
              <Input id="ce-limit" type="number" min={5} max={200} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></div>
          </>
        ) : (
          <div className="sm:col-span-2"><Label htmlFor="ce-file">CSV or Excel, one business per row (name and website; rating, reviews and city if you have them)</Label>
            <input id="ce-file" type="file" accept=".csv,.xlsx" className="block text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div><Label htmlFor="ce-rating">Min. rating</Label><Input id="ce-rating" type="number" step="0.1" min={1} max={5} value={minRating} onChange={(e) => setMinRating(e.target.value)} /></div>
          <div><Label htmlFor="ce-reviews">Min. reviews</Label><Input id="ce-reviews" type="number" min={0} value={minReviews} onChange={(e) => setMinReviews(e.target.value)} /></div>
        </div>
      </div>
      <p className="text-sm text-muted">
        Agentry checks each business&apos;s website, finds the person who decides, verifies their email and writes one first line from
        a fact on their own site. Nothing is sent: you review every line first.
      </p>
      <Button type="submit" disabled={pending}>{pending ? "Starting…" : "Build the list"}</Button>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </form>
  );
}

/** While a list is being built, refresh the page every few seconds so the funnel fills in. */
export function RefreshWhileBuilding({ building }: { building: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!building) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [building, router]);
  return null;
}

export function ApproveReady({ campaignId, count }: { campaignId: string; count: number }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <span className="inline-flex items-center gap-3">
      <Button disabled={pending || count === 0} onClick={() => {
        if (!confirm(`Approve all ${count} lines that passed the fact check? Lines that need attention stay for you.`)) return;
        start(async () => {
          const r = await approveReadyLines(campaignId);
          setMsg(r.ok ? { ok: true, text: `${r.data.approved} approved` } : { ok: false, text: r.error });
          router.refresh();
        });
      }}>Approve {count} checked lines</Button>
      {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
    </span>
  );
}

export type Prospect = {
  id: string; name: string | null; role: string | null; email: string; email_source: "site" | "finder" | "pattern";
  verify_status: string; snippets: { n: number; url: string; text: string }[]; first_line: string | null; line_snippet: number | null;
  fact_check: { ok?: boolean; reason?: string; attempts?: number }; review: "pending" | "needs_attention" | "approved" | "dropped";
  edited: boolean; company: string; website: string | null; city: string | null; rating: number | null; reviews: number | null;
  reviewed_by_name: string | null; status: "waiting" | "active" | "finished" | "stopped"; next_step: number; next_send_at: string | null;
  stop_reason: string | null; reply_kind: string | null; conversation_id: string | null;
};

const REPLY_LABEL: Record<string, string> = { interested: "Interested", not_now: "Not now", unsubscribe: "Unsubscribed", out_of_office: "Out of office",
  referral: "Referred us on", wrong_person: "Wrong person", bounce: "Bounced" };

function SequenceLine({ p }: { p: Prospect }) {
  if (p.status === "waiting") return null;
  const when = p.next_send_at ? new Date(p.next_send_at).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) : null;
  const text = p.status === "active" ? (p.next_step === 0 ? `Queued: first email${when ? ` from ${when}` : ""}` : `Email ${p.next_step} of 4 sent · next ${when ?? "soon"}`)
    : p.status === "finished" ? "All 4 emails sent, no reply" : `Stopped: ${p.stop_reason ?? "—"}`;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
      <span>{text}</span>
      {p.reply_kind && <Badge tone={p.reply_kind === "interested" ? "lime" : p.reply_kind === "unsubscribe" || p.reply_kind === "bounce" ? "danger" : "neutral"}>{REPLY_LABEL[p.reply_kind] ?? p.reply_kind}</Badge>}
      {p.conversation_id && <a href={`/conversations/${p.conversation_id}`} className="underline hover:text-ink">Open the thread</a>}
    </p>
  );
}

const FOUND_VIA = { site: "on their website", finder: "email finder", pattern: "guessed, then verified" };
const REVIEW_TONE = { pending: "neutral", needs_attention: "warning", approved: "lime", dropped: "neutral" } as const;
const REVIEW_LABEL = { pending: "To review", needs_attention: "Needs attention", approved: "Approved", dropped: "Dropped" };

export function ProspectCard({ p, canEdit, canSimulate = false }: { p: Prospect; canEdit: boolean; canSimulate?: boolean }) {
  const router = useRouter();
  const [line, setLine] = useState(p.first_line ?? "");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const [showFacts, setShowFacts] = useState(false);
  const cited = p.snippets.find((s) => s.n === p.line_snippet);
  const changed = line.trim() !== (p.first_line ?? "").trim();
  const open = p.review === "pending" || p.review === "needs_attention";

  function act(action: "approve" | "drop" | "reopen") {
    start(async () => {
      const r = await reviewProspect(p.id, action, action === "approve" && changed ? line.trim() : undefined);
      setMsg(r.ok ? { ok: true, text: action === "approve" ? (r.data.edited ? "Approved with your edit" : "Approved") : action === "drop" ? "Dropped" : "Back in review" }
                  : { ok: false, text: r.error });
      if (r.ok) router.refresh();
    });
  }

  return (
    <Card className="min-w-0 p-5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">{p.company}</h3>
          <p className="text-sm break-words text-muted">
            {[p.city, p.rating ? `★ ${p.rating}${p.reviews ? ` (${p.reviews})` : ""}` : null].filter(Boolean).join(" · ")}
            {p.website && <> · <a href={p.website} target="_blank" rel="noreferrer noopener" className="underline">{p.website.replace(/^https?:\/\//, "")}</a></>}
          </p>
        </div>
        <Badge tone={REVIEW_TONE[p.review]}>{REVIEW_LABEL[p.review]}</Badge>
      </div>
      <p className="mt-3 text-sm">
        <span className="font-medium">{p.name ?? "Unknown name"}</span>{p.role && <span className="text-muted">, {p.role}</span>}
        <span className="mx-1 text-muted">·</span><span className="font-mono text-[13px] break-all">{p.email}</span>
        <span className="ml-2 text-xs text-muted">verified · found {FOUND_VIA[p.email_source]}</span>
      </p>
      <SequenceLine p={p} />
      {p.review === "needs_attention" && (
        <p role="alert" className="mt-3 rounded-xl border-2 border-warning px-4 py-2.5 text-sm text-warning">
          The fact check stopped this line{p.fact_check.reason ? `: ${p.fact_check.reason}` : ""}. Rewrite it using only the fact below, or drop it.
        </p>
      )}
      <div className="mt-3">
        <Label htmlFor={`line-${p.id}`}>First line</Label>
        <Textarea id={`line-${p.id}`} rows={2} value={line} onChange={(e) => setLine(e.target.value)} disabled={!canEdit || !open} maxLength={300} />
        {cited && (
          <p className="mt-1.5 text-xs text-muted">
            Based on, from <a href={cited.url} target="_blank" rel="noreferrer noopener" className="underline">{cited.url.replace(/^https?:\/\//, "")}</a>:
            <span className="italic"> “{cited.text}”</span>
            {p.edited && <span className="ml-1 not-italic">· edited by {p.reviewed_by_name ?? "a person"}</span>}
          </p>
        )}
        {p.snippets.length > 1 && (
          <button type="button" className="mt-1 text-xs text-muted underline hover:text-ink" onClick={() => setShowFacts((s) => !s)}>
            {showFacts ? "Hide" : "Show"} all {p.snippets.length} facts from their website
          </button>
        )}
        {showFacts && (
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-ink-soft">
            {p.snippets.map((s) => <li key={s.n}>{s.text}</li>)}
          </ol>
        )}
      </div>
      {canEdit && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {open && <Button size="sm" disabled={pending || line.trim().length < 10 || (p.review === "needs_attention" && !changed)}
            onClick={() => act("approve")}>{changed ? "Approve with edit" : "Approve"}</Button>}
          {open && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("drop")}>Drop</Button>}
          {!open && p.status === "waiting" && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("reopen")}>Back to review</Button>}
          {p.status === "active" && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("drop")}>Stop emailing</Button>}
          {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
        </div>
      )}
      {canSimulate && p.status !== "waiting" && !p.reply_kind && <SimulateReply prospectId={p.id} />}
    </Card>
  );
}

/** Start (or add newly approved people), pause and resume sending. */
export function SendingControls({ campaignId, status, approvedWaiting }: { campaignId: string; status: string; approvedWaiting: number }) {
  const router = useRouter();
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const go = (fn: () => Promise<{ ok: boolean; error?: string; data?: unknown }>, ok: (d: never) => string) => start(async () => {
    const r = await fn();
    setMsg(r.ok ? { ok: true, text: ok(r.data as never) } : { ok: false, text: r.error ?? "Something went wrong" });
    router.refresh();
  });
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {approvedWaiting > 0 && status !== "completed" && (
        <Button disabled={pending} onClick={() => {
          if (!confirm(`Start emailing ${approvedWaiting} approved ${approvedWaiting === 1 ? "person" : "people"}? First emails go out in office hours, a few a day per mailbox.`)) return;
          go(() => startColdCampaign(campaignId), (d: { queued: number }) => `${d.queued} queued`);
        }}>{status === "running" || status === "paused" ? `Add ${approvedWaiting} approved` : "Start sending"}</Button>
      )}
      {status === "running" && <Button variant="secondary" disabled={pending} onClick={() => go(() => pauseColdCampaign(campaignId, "pause"), () => "Paused")}>Pause</Button>}
      {status === "paused" && <Button disabled={pending} onClick={() => go(() => pauseColdCampaign(campaignId, "resume"), () => "Sending again")}>Resume</Button>}
      {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
    </span>
  );
}

/** Mock mode, Agentry staff: pretend a prospect replied, to show a client what happens next. */
export function SimulateReply({ prospectId }: { prospectId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reply, setReply] = useState("Sounds interesting. What would it cost for our clinic?");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  if (!open) return <button type="button" className="text-xs text-muted underline hover:text-ink" onClick={() => setOpen(true)}>Simulate a reply (test mode)</button>;
  const send = (complaint: boolean) => start(async () => {
    const r = await simulateColdReply(prospectId, reply, complaint);
    setMsg(r.ok ? { ok: true, text: complaint ? `Spam complaint recorded${r.data.mailbox_paused ? `: mailbox paused (${r.data.mailbox_paused})` : ""}`
                                              : `Understood as: ${(r.data.kind ?? "").replace("_", " ")}` } : { ok: false, text: r.error });
    router.refresh();
  });
  return (
    <div className="mt-3 space-y-2 rounded-xl border-2 border-dashed border-line p-3">
      <Label htmlFor={`sim-${prospectId}`}>Their reply</Label>
      <Textarea id={`sim-${prospectId}`} rows={2} value={reply} onChange={(e) => setReply(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => send(false)}>Receive this reply</Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => send(true)}>They marked it as spam</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </div>
  );
}

export type SendingMailbox = { id: string; address: string; sender_name: string; daily_cap: number; status: string; paused_reason: string | null;
                               sent_24h: number; provider: string };

/** HQ: the client's sending mailboxes on separate domains (mock until Instantly is connected). */
export function SendingMailboxes({ orgId, items }: { orgId: string; items: SendingMailbox[] }) {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [cap, setCap] = useState(30);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  return (
    <div className="space-y-3">
      {items.length === 0 ? <p className="text-sm text-muted">No sending mailboxes. Cold email can&apos;t start without one.</p> : (
        <ul className="divide-y divide-line text-sm">
          {items.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-mono text-[13px] break-all">{m.address}</span>
              <span className="text-muted">as {m.sender_name} · up to {m.daily_cap}/day · {m.sent_24h} in 24h · {m.provider}</span>
              <Badge tone={m.status === "active" ? "success" : "danger"}>{m.status}{m.paused_reason ? `: ${m.paused_reason}` : ""}</Badge>
              <Button size="sm" variant="ghost" className="ml-auto" disabled={pending} onClick={() => start(async () => {
                const r = await changeSendingMailbox(orgId, m.id, m.status === "active" ? "paused" : "active");
                if (!r.ok) setMsg({ ok: false, text: r.error });
                router.refresh();
              })}>{m.status === "active" ? "Pause" : "Resume"}</Button>
            </li>
          ))}
        </ul>
      )}
      <form className="grid gap-2 sm:grid-cols-[1fr_1fr_90px_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); start(async () => {
        const r = await addSendingMailbox(orgId, address, name, cap);
        setMsg(r.ok ? { ok: true, text: "Added" } : { ok: false, text: r.error });
        if (r.ok) { setAddress(""); }
        router.refresh();
      }); }}>
        <div><Label htmlFor="mb-address">Mailbox (separate domain)</Label><Input id="mb-address" type="email" required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="priyam@getagentry.in" /></div>
        <div><Label htmlFor="mb-name">Sender name</Label><Input id="mb-name" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><Label htmlFor="mb-cap">Per day</Label><Input id="mb-cap" type="number" min={1} max={100} value={cap} onChange={(e) => setCap(Number(e.target.value))} /></div>
        <Button type="submit" variant="secondary" disabled={pending}>Add</Button>
      </form>
      <p className="text-xs text-muted">New mailboxes ramp up: 5 emails on day one, 3 more each day, up to the daily limit. Bounces over 3% or any spam complaint pause a mailbox.</p>
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>}
    </div>
  );
}
