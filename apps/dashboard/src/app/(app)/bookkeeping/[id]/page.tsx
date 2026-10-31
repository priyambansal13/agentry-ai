import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ReviewDocument } from "@/components/bookkeeping";
import { DOC_STATUS, timeAgo } from "@/lib/format";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Receipt" };

type Doc = { id: string; kind: string; source: string; filename: string | null; mime: string; status: string; error: string | null;
             fields: Record<string, { value: string | number | null; confidence: number; checked?: boolean }>; confidence: number | null;
             checks: { code: string; message: string; severity: string; fields: string[] }[]; duplicate_of: string | null; sender: string | null;
             created_at: string; reviewed_at: string | null; exported_at: string | null; categories: string[]; review_below: number; can_act: boolean;
             field_order: { name: string; type: string; required: boolean }[] };

export default async function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("bookkeeping");
  const { id } = await params;
  let d: Doc;
  try {
    d = await api<Doc>(`/org/bookkeeping/documents/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && [403, 404, 422].includes(e.status)) notFound();
    throw e;
  }
  const flagged = d.checks.flatMap((c) => c.fields);
  return (
    <div className="space-y-6">
      <header>
        <Link href="/bookkeeping" className="text-sm text-muted hover:text-ink">← Bookkeeping</Link>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">{d.fields.vendor?.value ?? d.filename ?? "Document"}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-muted">
          <Badge tone={DOC_STATUS[d.status]?.tone ?? "neutral"}>{DOC_STATUS[d.status]?.label ?? d.status}</Badge>
          <span>{d.kind} · from {d.sender ? `${d.sender} on ` : ""}{d.source} · {timeAgo(d.created_at)}{d.reviewed_at ? ` · checked ${timeAgo(d.reviewed_at)}` : ""}{d.exported_at ? " · exported" : ""}</span>
        </p>
      </header>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="overflow-hidden p-2">
          {d.mime === "application/pdf" ? (
            <iframe src={`/api/document-file/${d.id}`} title="The document" className="h-[70vh] w-full rounded-lg" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`/api/document-file/${d.id}`} alt="The receipt as sent" className="w-full rounded-lg object-contain" />
          )}
        </Card>
        <div className="space-y-4">
          {d.error && <p role="alert" className="rounded-xl border-2 border-danger px-4 py-3 text-sm text-danger">{d.error}</p>}
          {d.checks.length > 0 && (
            <Card className="space-y-2 p-5">
              <h2 className="font-semibold">What the checks found</h2>
              <ul className="space-y-1 text-sm">
                {d.checks.map((c) => <li key={c.code} className={c.severity === "error" ? "text-danger" : "text-ink-soft"}>{c.severity === "error" ? "✕" : "!"} {c.message}</li>)}
              </ul>
              {d.duplicate_of && <Link href={`/bookkeeping/${d.duplicate_of}`} className="text-sm font-semibold underline">See the earlier one</Link>}
            </Card>
          )}
          {d.status !== "failed" && (
            <Card className="p-5">
              <h2 className="mb-3 font-semibold">Fields {d.status === "needs_review" ? "(highlighted: please check)" : ""}</h2>
              <ReviewDocument id={d.id} fields={d.fields} specs={d.field_order} categories={d.categories} threshold={d.review_below}
                              canAct={d.can_act} status={d.status} flagged={flagged} />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
