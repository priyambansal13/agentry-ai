"use client";

import { Badge, Button, Card, Input, Label, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { approveReadyLines, createColdCampaign, reviewProspect, uploadColdCampaign } from "@/app/(app)/actions";

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
  reviewed_by_name: string | null;
};

const FOUND_VIA = { site: "on their website", finder: "email finder", pattern: "guessed, then verified" };
const REVIEW_TONE = { pending: "neutral", needs_attention: "warning", approved: "lime", dropped: "neutral" } as const;
const REVIEW_LABEL = { pending: "To review", needs_attention: "Needs attention", approved: "Approved", dropped: "Dropped" };

export function ProspectCard({ p, canEdit }: { p: Prospect; canEdit: boolean }) {
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
          {!open && <Button size="sm" variant="secondary" disabled={pending} onClick={() => act("reopen")}>Back to review</Button>}
          {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
        </div>
      )}
    </Card>
  );
}
