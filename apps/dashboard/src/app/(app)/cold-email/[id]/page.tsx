import { Badge, buttonClasses, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApproveReady, type Prospect, ProspectCard, RefreshWhileBuilding } from "@/components/cold-email";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Cold email list" };

type Funnel = { steps: { key: string; label: string; count: number }[]; dropped: { reason: string; count: number }[];
                review: { pending: number; needs_attention: number; approved: number; dropped: number } };
type Campaign = { id: string; name: string; settings: { source?: string; query?: string; city?: string; min_rating?: number; min_reviews?: number };
                  build_status: string | null; build_error: string | null; stats: { total?: number; processed?: number };
                  funnel: Funnel; can_edit: boolean };

const TABS = [["to_review", "To review"], ["approved", "Approved"], ["dropped", "Dropped"], ["all", "All"]] as const;

export default async function ColdEmailCampaignPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ review?: string }> }) {
  const active = await requirePage("cold-email");
  const { id } = await params;
  const asked = (await searchParams).review;
  const review = TABS.find(([k]) => k === asked)?.[0] ?? "to_review";
  let c: Campaign;
  try {
    c = await api<Campaign>(`/org/cold-email/campaigns/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const { items } = await api<{ items: Prospect[] }>(`/org/cold-email/campaigns/${id}/prospects?review=${review}`, { orgId: active.id });
  const building = c.build_status === "building";
  const top = Math.max(1, c.funnel.steps[0]?.count ?? 1);
  const counts = { to_review: c.funnel.review.pending + c.funnel.review.needs_attention, approved: c.funnel.review.approved,
                   dropped: c.funnel.review.dropped, all: Object.values(c.funnel.review).reduce((a, b) => a + b, 0) };
  return (
    <div className="space-y-6">
      <RefreshWhileBuilding building={building} />
      <header>
        <Link href="/cold-email" className="text-sm text-muted hover:text-ink">← Cold email</Link>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">{c.name}</h1>
        <p className="mt-1 text-muted">
          {c.settings.source === "csv" ? "Uploaded list" : `${c.settings.query} in ${c.settings.city}`}
          {c.settings.min_rating ? ` · rating ${c.settings.min_rating}+` : ""}{c.settings.min_reviews ? ` · ${c.settings.min_reviews}+ reviews` : ""}
        </p>
      </header>
      {building && <p role="status" className="rounded-xl border-2 border-lime bg-lime-soft px-4 py-3 text-sm">
        Researching {c.stats.processed ?? 0} of {c.stats.total ?? "…"} businesses. This page updates by itself.</p>}
      {c.build_status === "failed" && <p role="alert" className="rounded-xl border-2 border-danger px-4 py-3 text-sm text-danger">
        The list stopped part-way: {c.build_error ?? "unknown error"}. What was found so far is kept.</p>}

      <Card>
        <CardHeader><CardTitle>Funnel</CardTitle></CardHeader>
        <CardBody className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <ol className="space-y-2" aria-label="How many businesses reached each step">
            {c.funnel.steps.map((s) => (
              <li key={s.key} className="grid grid-cols-[150px_1fr_40px] items-center gap-3 text-sm sm:grid-cols-[190px_1fr_48px]">
                <span className="text-ink-soft">{s.label}</span>
                <span className="h-5 rounded-md bg-paper" aria-hidden="true">
                  <span className="block h-5 rounded-md border-2 border-ink bg-lime" style={{ width: `${Math.max(s.count ? 2 : 0, (s.count / top) * 100)}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{s.count}</span>
              </li>
            ))}
          </ol>
          <div className="text-sm">
            <p className="font-medium">Why businesses dropped out</p>
            {c.funnel.dropped.length === 0 ? <p className="mt-1 text-muted">None yet.</p> : (
              <ul className="mt-1 space-y-1">
                {c.funnel.dropped.map((d) => (
                  <li key={d.reason} className="flex justify-between gap-3 text-ink-soft"><span>{d.reason}</span><span className="tabular-nums">{d.count}</span></li>
                ))}
              </ul>
            )}
          </div>
        </CardBody>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <nav className="flex flex-wrap gap-1 rounded-xl border-2 border-line p-1 text-sm" aria-label="Review state">
          {TABS.map(([k, label]) => (
            <Link key={k} href={`/cold-email/${id}?review=${k}`} aria-current={review === k ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 font-medium ${review === k ? "bg-ink text-paper" : "text-muted hover:text-ink"}`}>
              {label} <span className="tabular-nums opacity-70">{counts[k]}</span>
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {c.can_edit && <ApproveReady campaignId={id} count={c.funnel.review.pending} />}
          {c.can_edit && counts.all > 0 && (
            <a href={`/api/cold-email/${id}/export`} className={buttonClasses("secondary", "md")}>Export sheet (CSV)</a>
          )}
        </div>
      </div>
      {c.funnel.review.needs_attention > 0 && review === "to_review" && (
        <p className="text-sm"><Badge tone="warning">{c.funnel.review.needs_attention} need attention</Badge>
          <span className="ml-2 text-muted">Their first line didn&apos;t pass the fact check. They&apos;re listed first.</span></p>
      )}
      {items.length === 0 ? (
        <p className="text-muted">{building ? "People appear here as they're found." : "Nothing here."}</p>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {items.map((p) => <ProspectCard key={p.id} p={p} canEdit={c.can_edit} />)}
        </div>
      )}
    </div>
  );
}
