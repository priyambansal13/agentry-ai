import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { AddDocuments } from "@/components/bookkeeping";
import { DOC_STATUS, timeAgo } from "@/lib/format";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Bookkeeping" };

type F = { value: string | number | null; confidence: number };
type Doc = { id: string; kind: string; source: string; filename: string | null; status: string; fields: Record<string, F>; confidence: number | null;
             checks: { code: string; message: string; severity: string }[]; error: string | null; created_at: string; exported_at: string | null };
type Data = { month: string; items: Doc[]; counts: Record<string, number>; to_export: number; can_act: boolean; total: number;
              by_category: { category: string; spent: number; budget: number | null }[] };

const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const TABS = [["", "All"], ["needs_review", "To check"], ["ready", "Filed"], ["failed", "Couldn't read"], ["rejected", "Rejected"]] as const;

function shift(month: string, n: number) {
  const [y = 2026, m = 1] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

export default async function BookkeepingPage({ searchParams }: { searchParams: Promise<{ status?: string; month?: string }> }) {
  const active = await requirePage("bookkeeping");
  const { status = "", month } = await searchParams;
  const q = new URLSearchParams({ ...(status ? { status } : {}), ...(month && /^\d{4}-\d{2}$/.test(month) ? { month } : {}) });
  const d = await api<Data>(`/org/bookkeeping/documents?${q}`, { orgId: active.id });
  const monthName = new Date(`${d.month}-01T12:00:00Z`).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
  const link = (p: Record<string, string>) => `/bookkeeping?${new URLSearchParams({ ...(status ? { status } : {}), month: d.month, ...p })}`;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Bookkeeping</h1>
          <p className="mt-1 text-muted">Receipts and bills read by AI, checked for totals, GST and duplicates. Anything unclear waits for a person.</p>
        </div>
        {d.can_act && (
          <div className="flex flex-wrap gap-2 text-sm">
            <a href={`/api/bookkeeping-export?format=tally`} className="inline-flex h-10 items-center rounded-xl border-2 border-ink px-4 font-semibold hover:bg-lime-soft">
              Export to Tally ({d.to_export} new)
            </a>
            <a href={`/api/bookkeeping-export?format=csv`} className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 font-semibold hover:border-ink">CSV for Sheets</a>
          </div>
        )}
      </header>
      {d.can_act && <Card className="p-5"><AddDocuments empty={Object.keys(d.counts).length === 0} /></Card>}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-xl font-bold">{monthName}: {inr(d.total)}</h2>
          <nav className="flex gap-2 text-sm" aria-label="Month">
            <Link href={link({ month: shift(d.month, -1) })} className="rounded-xl border-2 border-line px-3 py-1.5 font-semibold hover:border-ink">← Earlier</Link>
            <Link href={link({ month: shift(d.month, 1) })} className="rounded-xl border-2 border-line px-3 py-1.5 font-semibold hover:border-ink">Later →</Link>
          </nav>
        </div>
        {d.by_category.length === 0 ? <p className="text-sm text-muted">Nothing filed for this month yet.</p> : (
          <Card className="divide-y divide-line">
            {d.by_category.map((c) => {
              const pct = c.budget ? Math.min(100, Math.round((100 * c.spent) / c.budget)) : null;
              return (
                <div key={c.category} className="grid gap-2 px-5 py-3 sm:grid-cols-[14rem_1fr_9rem] sm:items-center">
                  <span className="font-medium">{c.category}</span>
                  {pct !== null ? (
                    <div className="h-2 rounded-full bg-line" role="img" aria-label={`${pct}% of budget`}>
                      <div className={`h-2 rounded-full ${pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-ink"}`} style={{ width: `${pct}%` }} />
                    </div>
                  ) : <span className="text-xs text-muted">no budget set</span>}
                  <span className="text-sm tabular-nums sm:text-right">{inr(c.spent)}{c.budget ? <span className="text-muted"> / {inr(c.budget)}</span> : null}</span>
                </div>
              );
            })}
          </Card>
        )}
      </section>

      <section className="space-y-3">
        <nav className="flex flex-wrap gap-2 text-sm" aria-label="Status">
          {TABS.map(([key, name]) => (
            <Link key={key} href={link({ status: key })} aria-current={status === key ? "page" : undefined}
                  className={`rounded-full border-2 px-3 py-1 font-semibold ${status === key ? "border-ink bg-lime-soft" : "border-line hover:border-ink"}`}>
              {name}{key && d.counts[key] ? ` (${d.counts[key]})` : ""}
            </Link>
          ))}
        </nav>
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted"><tr>
              <th className="px-4 py-3 font-medium">Vendor</th><th className="px-4 py-3 font-medium">Date</th><th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 text-right font-medium">Total</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">From</th>
            </tr></thead>
            <tbody className="divide-y divide-line">
              {d.items.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">No receipts here yet.</td></tr>}
              {d.items.map((x) => (
                <tr key={x.id}>
                  <td className="px-4 py-3"><Link href={`/bookkeeping/${x.id}`} className="font-medium hover:underline">{x.fields.vendor?.value ?? x.filename ?? "Document"}</Link>
                    {x.checks[0] && x.status !== "ready" && <div className="text-xs text-muted">{x.checks[0].message}</div>}
                    {x.error && <div className="text-xs text-danger">{x.error}</div>}</td>
                  <td className="px-4 py-3 tabular-nums">{x.fields.date?.value ?? "—"}</td>
                  <td className="px-4 py-3">{x.fields.category?.value ?? "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{typeof x.fields.total?.value === "number" ? `₹${x.fields.total.value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}</td>
                  <td className="px-4 py-3"><Badge tone={DOC_STATUS[x.status]?.tone ?? "neutral"}>{DOC_STATUS[x.status]?.label ?? x.status}</Badge>
                    {x.exported_at && <div className="text-xs text-muted">exported</div>}</td>
                  <td className="px-4 py-3 text-xs text-muted">{x.source} · {timeAgo(x.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}
