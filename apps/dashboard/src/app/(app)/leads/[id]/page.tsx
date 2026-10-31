import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ResearchAgain } from "@/components/lead-research";
import { BOOKING_STATUS, timeAgo } from "@/lib/format";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Lead" };

type Research = {
  status: "done" | "no_site" | "no_company"; domain: string | null; company: string | null; what_they_do: string | null; size: string | null;
  decision_maker: { name: string; role: string | null } | null; likely_need: string | null; talking_points: string[]; questions: string[];
  sources: string[]; at: string;
};
type Lead = {
  id: string; source: string; stage: string; qualification: Record<string, string>; research: Research | null; created_at: string;
  conversation_id: string | null; name: string | null; email: string | null; phone: string | null; company: string | null;
  bookings: { id: string; starts_at: string; status: string; service: string; brief: { title: string; body: string; sent_at: string } | null }[];
  research_on: boolean; can_research: boolean;
};

const NO_SITE: Record<string, string> = {
  no_company: "They wrote from a personal address and gave no website, so this note is from what they told us.",
  no_site: "Their website couldn't be read, so this note is from what they told us.",
};

const SAID = ["need", "interest", "budget", "timeline", "notes", "message"];  // their words (not our outreach data)

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid gap-1 sm:grid-cols-[10rem_1fr]"><dt className="text-sm text-muted">{label}</dt><dd className="text-sm">{children}</dd></div>;
}

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("leads");
  const { id } = await params;
  let l: Lead;
  try {
    l = await api<Lead>(`/org/leads/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 403 || e.status === 422)) notFound();
    throw e;
  }
  const r = l.research;
  const said = Object.entries(l.qualification).filter(([k, v]) => SAID.includes(k) && typeof v === "string" && v);
  return (
    <div className="space-y-6">
      <header>
        <Link href="/leads" className="text-sm text-muted hover:text-ink">← Leads</Link>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">{l.name ?? l.email ?? l.phone}</h1>
        <p className="mt-1 text-muted">
          {[l.company, l.email, l.phone].filter(Boolean).join(" · ")} · came in via {l.source.replace(/_/g, " ")} {timeAgo(l.created_at)}
          {" "}<Badge>{l.stage.replace("_", " ")}</Badge>
        </p>
        {l.conversation_id && <Link href={`/conversations/${l.conversation_id}`} className="text-sm font-semibold underline">Open the conversation</Link>}
      </header>

      <Card className="space-y-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-bold">Research</h2>
            {r && <p className="text-xs text-muted">{timeAgo(r.at)}{r.domain ? ` · from ${r.domain}` : ""}. Only what their pages and messages say.</p>}
          </div>
          {l.can_research && <ResearchAgain id={l.id} first={!r} />}
        </div>
        {!r ? (
          <p className="text-sm text-muted">{l.research_on ? "Not researched yet: it usually happens within a minute of the lead arriving." : "Switch on Lead research & meeting prep to get a note on every new lead."}</p>
        ) : (
          <>
            {NO_SITE[r.status] && <p className="text-sm text-muted">{NO_SITE[r.status]}</p>}
            <dl className="space-y-3">
              {r.company && <Row label="Company">{r.company}</Row>}
              {r.what_they_do && <Row label="What they do">{r.what_they_do}</Row>}
              {r.size && <Row label="Size">{r.size}</Row>}
              {r.decision_maker && <Row label="Decision maker">{r.decision_maker.name}{r.decision_maker.role ? ` (${r.decision_maker.role})` : ""}</Row>}
              {r.likely_need && <Row label="Likely need">{r.likely_need}</Row>}
              {r.talking_points.length > 0 && <Row label="Talking points"><ul className="list-disc space-y-1 pl-5">{r.talking_points.map((t) => <li key={t}>{t}</li>)}</ul></Row>}
              {r.questions.length > 0 && <Row label="Ask them"><ul className="list-disc space-y-1 pl-5">{r.questions.map((t) => <li key={t}>{t}</li>)}</ul></Row>}
              {r.sources.length > 0 && <Row label="Sources"><ul className="space-y-1">{r.sources.map((u) => <li key={u} className="break-all text-xs text-muted">{u}</li>)}</ul></Row>}
            </dl>
          </>
        )}
      </Card>

      {said.length > 0 && (
        <Card className="space-y-3 p-6">
          <h2 className="font-display text-xl font-bold">What they told us</h2>
          <dl className="space-y-2">{said.map(([k, v]) => <Row key={k} label={k.replace(/_/g, " ")}>{v}</Row>)}</dl>
        </Card>
      )}

      <Card className="space-y-3 p-6">
        <h2 className="font-display text-xl font-bold">Appointments</h2>
        {l.bookings.length === 0 ? <p className="text-sm text-muted">None yet.</p> : l.bookings.map((b) => (
          <div key={b.id} className="space-y-2 border-t border-line pt-3 first:border-0 first:pt-0">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold">{new Date(b.starts_at).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
              <span>{b.service}</span>
              <Badge tone={BOOKING_STATUS[b.status]?.tone ?? "neutral"}>{BOOKING_STATUS[b.status]?.label ?? b.status}</Badge>
            </div>
            {b.brief && (
              <details className="rounded-xl bg-paper p-3 text-sm">
                <summary className="cursor-pointer font-semibold">Meeting brief (sent {timeAgo(b.brief.sent_at)})</summary>
                <p className="mt-2 whitespace-pre-line text-ink-soft">{b.brief.body}</p>
              </details>
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}
