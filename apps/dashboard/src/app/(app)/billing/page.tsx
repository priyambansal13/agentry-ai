import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { money, period, type Statement, type StatementDetail, STATUS_TONE } from "@/lib/billing";
import { api, ApiError, getActiveOrg } from "@/lib/session";

export const metadata = { title: "Billing" };

type Plan = { currency: string; setup_fee: number; setup_billed: boolean; retainer: number; included: Record<string, number>;
              overage: Record<string, number>; outcome_prices: { outcome: string; price?: number; pct_of_customer_value?: number; min?: number }[];
              revenue_share: { basis: string; rate: number; cap?: number; strong_only?: boolean; window_days?: number }; tax_rate: number };

export default async function BillingPage() {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  let d: { plan: Plan | null; estimate: StatementDetail | null; statements: Statement[] };
  try {
    d = await api("/org/billing", { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  const p = d.plan;
  const terms: string[] = [];
  if (p) {
    if (Number(p.retainer) > 0) terms.push(`${money(p.retainer, p.currency)} per month`);
    if (Number(p.setup_fee) > 0) terms.push(`one-time setup ${money(p.setup_fee, p.currency)}${p.setup_billed ? " (billed)" : ""}`);
    for (const o of p.outcome_prices) terms.push(o.price != null ? `${money(o.price, p.currency)} per booked appointment`
      : `${Math.round((o.pct_of_customer_value ?? 0) * 100)}% of each appointment's value (min ${money(o.min ?? 0, p.currency)})`);
    if (p.revenue_share.rate > 0) terms.push(`${(p.revenue_share.rate * 100).toFixed(1)}% of ${p.revenue_share.basis === "overdue_only" ? "overdue invoices" : "money"} recovered${p.revenue_share.cap ? `, capped at ${money(p.revenue_share.cap, p.currency)}/month` : ""}`);
    for (const [k, n] of Object.entries(p.included)) terms.push(`${n.toLocaleString("en-IN")} ${k.replace("_", " ")} included${p.overage[k] ? `, then ${money(p.overage[k], p.currency)} each` : ""}`);
    if (Number(p.tax_rate) > 0) terms.push(`+ ${Math.round(Number(p.tax_rate) * 100)}% GST`);
  }
  const est = d.estimate?.statement;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Billing</h1>
        <p className="mt-1 text-muted">What you pay, and the results behind every line.</p>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Your plan</CardTitle></CardHeader>
          <CardBody>{p ? <ul className="space-y-1.5 text-sm">{terms.map((t) => <li key={t} className="flex gap-2"><span aria-hidden="true">✓</span>{t}</li>)}</ul>
            : <p className="text-sm text-muted">Your plan is being set up by Agentry.</p>}</CardBody>
        </Card>
        {est && (
          <Card>
            <CardHeader><CardTitle>This month so far</CardTitle><span className="text-sm text-muted">estimate</span></CardHeader>
            <CardBody>
              <p className="text-3xl font-semibold">{money(est.total, est.currency)}</p>
              <ul className="mt-3 space-y-1 text-sm text-ink-soft">{d.estimate!.lines.map((l) => (
                <li key={l.id} className="flex justify-between gap-4"><span>{l.description}</span><span className="tabular-nums">{money(l.amount, est.currency)}</span></li>
              ))}</ul>
              <p className="mt-3 text-xs text-muted">Final figures are on the statement we send at the start of next month.</p>
            </CardBody>
          </Card>
        )}
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr><th className="px-5 py-3 font-medium">Statement</th><th className="px-5 py-3 font-medium">Period</th>
            <th className="px-5 py-3 font-medium">Status</th><th className="px-5 py-3 text-right font-medium">Total</th><th className="px-5 py-3" /></tr></thead>
          <tbody className="divide-y divide-line">
            {d.statements.length === 0 && <tr><td colSpan={5} className="px-5 py-8 text-center text-muted">No statements yet.</td></tr>}
            {d.statements.map((s) => (
              <tr key={s.id}>
                <td className="px-5 py-3 font-mono text-xs">{s.number}</td>
                <td className="px-5 py-3">{period(s)}</td>
                <td className="px-5 py-3"><Badge tone={STATUS_TONE[s.status] ?? "neutral"}>{s.status}</Badge></td>
                <td className="px-5 py-3 text-right tabular-nums">{money(s.total, s.currency)}</td>
                <td className="px-5 py-3 text-right"><Link className="font-semibold underline-offset-4 hover:underline" href={`/billing/statements/${s.id}`}>View →</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
