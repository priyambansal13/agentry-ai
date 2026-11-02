import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { ImportProducts, NewQuote, type Product, QuoteActions } from "@/components/quotes";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Quotes" };

type Q = { id: string; number: string; customer: string; total: number; currency: string; status: string; source: string; valid_until: string; followups: number; created_at: string };
type D = { items: Q[]; stats: { open: number; won: number; lost: number; won_value: number; open_value: number }; products: number; can_act: boolean };
const TONE: Record<string, "neutral" | "lime" | "success" | "danger" | "warning"> = { draft: "neutral", sent: "lime", won: "success", lost: "danger", expired: "warning" };
const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;

export default async function QuotesPage() {
  const active = await requirePage("quotes");
  const [d, { items: products }] = await Promise.all([api<D>("/org/quotes", { orgId: active.id }), api<{ items: Product[] }>("/org/quotes/products", { orgId: active.id })]);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Quotes</h1>
        <p className="mt-1 max-w-3xl text-muted">Your assistant answers product, price and stock questions from your catalogue, and sends GST quotes as PDFs on WhatsApp or email,
          then follows them up. Prices always come from the catalogue, never from the AI.</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-4">
        {[["Open quotes", `${d.stats.open} · ${inr(d.stats.open_value)}`], ["Won (90 days)", `${d.stats.won} · ${inr(d.stats.won_value)}`], ["Lost", d.stats.lost],
          ["Win rate", d.stats.won + d.stats.lost ? `${Math.round((100 * d.stats.won) / (d.stats.won + d.stats.lost))}%` : "-"]].map(([k, v]) => (
          <Card key={String(k)}><CardBody><p className="text-sm text-muted">{k}</p><p className="text-xl font-semibold">{v}</p></CardBody></Card>))}
      </div>
      <Card><CardBody className="p-0">{d.items.length === 0 ? <p className="p-5 text-muted">No quotes yet.</p> : (
        <ul className="divide-y divide-line">{d.items.map((q) => (
          <li key={q.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div><p className="font-semibold">{q.number} · {q.customer}</p>
              <p className="text-xs text-muted">{inr(Number(q.total))} incl. GST · valid until {q.valid_until}{q.source === "agent" ? " · made by the assistant" : ""}{q.followups ? ` · ${q.followups} follow-up${q.followups > 1 ? "s" : ""}` : ""}</p></div>
            <span className="flex items-center gap-3"><QuoteActions id={q.id} status={q.status} canAct={d.can_act} /><Badge tone={TONE[q.status]}>{q.status}</Badge></span>
          </li>))}</ul>)}</CardBody></Card>
      {d.can_act && (
        <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <Card><CardHeader><CardTitle>New quote</CardTitle></CardHeader><CardBody><NewQuote products={products} /></CardBody></Card>
          <Card><CardHeader><CardTitle>Catalogue</CardTitle><span className="text-sm text-muted">{d.products} products</span></CardHeader><CardBody className="space-y-2">
            <p className="text-sm text-muted">CSV or Excel with: Code, Product, Category, Unit, Price, GST %, Stock, Min qty, Description. Upload again whenever prices or stock change.</p>
            <ImportProducts /></CardBody></Card>
        </div>)}
    </div>
  );
}
