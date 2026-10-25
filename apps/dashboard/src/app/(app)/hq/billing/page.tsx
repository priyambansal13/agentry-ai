import { Card } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { money } from "@/lib/billing";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Revenue & margin · Agentry HQ" };

type Row = { org_id: string; name: string; llm_usd: number; whatsapp_templates: number; voice_minutes: number; cost_inr: number; revenue: Record<string, number>; revenue_inr: number; margin_pct: number | null };

export default async function HqBilling({ searchParams }: { searchParams: Promise<{ months?: string }> }) {
  const [{ months = "1" }, me] = await Promise.all([searchParams, getMe()]);
  if (!me.is_staff) redirect("/home");
  const d = await api<{ months: number; from: string; to: string; items: Row[] }>(`/hq/billing?months=${Number(months) || 1}`);
  const rev = d.items.reduce((n, r) => n + r.revenue_inr, 0);
  const cost = d.items.reduce((n, r) => n + r.cost_inr, 0);
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="font-hand text-xl text-muted">Agentry HQ</p><h1 className="font-display text-3xl font-bold tracking-tight">Revenue &amp; margin</h1>
          <p className="mt-1 text-sm text-muted">{new Date(d.from).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} – {new Date(d.to).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</p></div>
        <nav className="flex gap-1 text-sm" aria-label="Period">{[1, 3, 12].map((n) => (
          <Link key={n} href={`/hq/billing?months=${n}`} aria-current={d.months === n ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 ${d.months === n ? "bg-ink text-paper" : "border border-line hover:border-ink"}`}>{n === 1 ? "Last month" : `${n} months`}</Link>
        ))}</nav>
      </header>
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5"><p className="text-sm text-muted">Revenue (billed, pre-tax)</p><p className="mt-1 text-3xl font-semibold">{money(rev, "INR")}</p></Card>
        <Card className="p-5"><p className="text-sm text-muted">Cost to serve</p><p className="mt-1 text-3xl font-semibold">{money(cost, "INR")}</p></Card>
        <Card className="p-5"><p className="text-sm text-muted">Gross margin</p><p className="mt-1 text-3xl font-semibold">{rev ? `${(100 * (1 - cost / rev)).toFixed(1)}%` : "—"}</p></Card>
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr><th className="px-5 py-3 font-medium">Client</th><th className="px-5 py-3 text-right font-medium">Revenue</th>
            <th className="px-5 py-3 text-right font-medium">Model cost</th><th className="px-5 py-3 text-right font-medium">WhatsApp templates</th><th className="px-5 py-3 text-right font-medium">Call minutes</th>
            <th className="px-5 py-3 text-right font-medium">Cost (₹)</th><th className="px-5 py-3 text-right font-medium">Margin</th></tr></thead>
          <tbody className="divide-y divide-line">
            {d.items.length === 0 && <tr><td colSpan={7} className="px-5 py-8 text-center text-muted">No clients have a plan yet.</td></tr>}
            {d.items.map((r) => (
              <tr key={r.org_id}>
                <td className="px-5 py-3"><Link href={`/hq/${r.org_id}`} className="font-medium underline-offset-4 hover:underline">{r.name}</Link></td>
                <td className="px-5 py-3 text-right tabular-nums">{Object.entries(r.revenue).map(([c, v]) => money(v, c)).join(" + ") || "—"}</td>
                <td className="px-5 py-3 text-right tabular-nums">${r.llm_usd.toFixed(2)}</td>
                <td className="px-5 py-3 text-right tabular-nums">{r.whatsapp_templates}</td>
                <td className="px-5 py-3 text-right tabular-nums">{r.voice_minutes}</td>
                <td className="px-5 py-3 text-right tabular-nums">{money(r.cost_inr, "INR")}</td>
                <td className={`px-5 py-3 text-right font-semibold tabular-nums ${r.margin_pct != null && r.margin_pct < 60 ? "text-danger" : ""}`}>{r.margin_pct != null ? `${r.margin_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <p className="text-xs text-muted">Revenue is converted to rupees at rough rates for comparison only. Margins below 60% are flagged.</p>
    </div>
  );
}
