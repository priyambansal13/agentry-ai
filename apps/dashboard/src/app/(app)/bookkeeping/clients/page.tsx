import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { OpenClientBooks } from "@/components/bookkeeping";
import { timeAgo } from "@/lib/format";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "All my clients' books" };

type Row = { id: string; name: string; to_check: number; unreadable: number; filed: number; month_total: number; to_export: number; last_document_at: string | null };

/** A CA firm's view: every business whose books this person keeps, and what's waiting in each. */
export default async function BookkeepingClientsPage() {
  const [me, d] = await Promise.all([getMe(), api<{ month: string; items: Row[] }>("/me/bookkeeping-clients")]);
  const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
  const waiting = d.items.reduce((n, r) => n + r.to_check + r.unreadable, 0);
  return (
    <div className="space-y-6">
      <header>
        <Link href="/bookkeeping" className="text-sm text-muted hover:text-ink">← Bookkeeping</Link>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">All my clients&apos; books</h1>
        <p className="mt-1 text-muted">{d.items.length} business{d.items.length === 1 ? "" : "es"} · {waiting} document{waiting === 1 ? "" : "s"} waiting for a person.</p>
      </header>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr>
            <th className="px-4 py-3 font-medium">Business</th><th className="px-4 py-3 font-medium">To check</th><th className="px-4 py-3 font-medium">Filed</th>
            <th className="px-4 py-3 text-right font-medium">This month</th><th className="px-4 py-3 font-medium">Not exported</th><th className="px-4 py-3 font-medium">Last receipt</th>
            <th className="px-4 py-3" />
          </tr></thead>
          <tbody className="divide-y divide-line">
            {d.items.length === 0 && <tr><td colSpan={7} className="px-4 py-8 text-center text-muted">No businesses with the bookkeeping assistant yet.</td></tr>}
            {d.items.map((r) => (
              <tr key={r.id}>
                <td className="px-4 py-3 font-medium">{r.name}</td>
                <td className="px-4 py-3">{r.to_check || r.unreadable ? <Badge tone="warning">{r.to_check + r.unreadable}</Badge> : <span className="text-muted">0</span>}</td>
                <td className="px-4 py-3 tabular-nums">{r.filed}</td>
                <td className="px-4 py-3 text-right tabular-nums">{inr(r.month_total)}</td>
                <td className="px-4 py-3 tabular-nums">{r.to_export}</td>
                <td className="px-4 py-3 text-xs text-muted">{r.last_document_at ? timeAgo(r.last_document_at) : "—"}</td>
                <td className="px-4 py-3 text-right"><OpenClientBooks id={r.id} staff={me.is_staff} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
