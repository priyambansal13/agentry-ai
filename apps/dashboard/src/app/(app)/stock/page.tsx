import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { CopyText } from "@/components/ca-tool-forms";
import { ImportStock, ScanShelf } from "@/components/stock";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Stock" };

type Item = { id: string; name: string; unit: string; count: number | null; counted_at: string | null; reorder_at: number | null; supplier: string | null };
type Order = { supplier: string; phone: string | null; message: string; items: { name: string; count: number; order: number; unit: string }[] };
type D = { items: Item[]; reorder: Order[]; confirm_below: number; can_work: boolean };

export default async function StockPage() {
  const active = await requirePage("stock");
  const d = await api<D>("/org/stock", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Stock</h1>
        <p className="mt-1 max-w-3xl text-muted">Take a photo of a shelf, fridge or storeroom: the items are counted, you check the doubtful ones, and anything at its reorder level
          shows up below, grouped by supplier, with the order message ready.</p>
      </header>
      {d.can_work && <Card><CardHeader><CardTitle>Scan a shelf</CardTitle></CardHeader><CardBody><ScanShelf confirmBelow={d.confirm_below} /></CardBody></Card>}
      {d.reorder.length > 0 && <Card><CardHeader><CardTitle>To reorder</CardTitle></CardHeader><CardBody className="space-y-3">{d.reorder.map((o) => (
        <div key={o.supplier} className="rounded-xl border-2 border-line p-3 text-sm">
          <p className="flex flex-wrap items-center justify-between gap-2 font-semibold">{o.supplier}<span className="flex gap-3">
            {o.phone && <a href={`https://wa.me/${o.phone.replace(/\D/g, "")}?text=${encodeURIComponent(o.message)}`} target="_blank" rel="noreferrer" className="underline">Send on WhatsApp</a>}
            <CopyText text={o.message} /></span></p>
          <ul className="mt-1">{o.items.map((i) => <li key={i.name}>{i.name}: {i.count} left, order {i.order} {i.unit}</li>)}</ul>
        </div>))}</CardBody></Card>}
      <Card><CardHeader><CardTitle>Items</CardTitle><span className="text-sm text-muted">{d.items.length}</span></CardHeader><CardBody className="space-y-3">
        {d.items.length > 0 && <table className="w-full text-sm"><thead className="text-left text-muted"><tr><th className="p-1">Item</th><th className="p-1">Count</th><th className="p-1">Reorder at</th><th className="p-1">Supplier</th></tr></thead>
          <tbody>{d.items.map((i) => (<tr key={i.id}><td className="p-1">{i.name}</td>
            <td className="p-1">{i.count ?? "-"} {i.unit}{i.count != null && i.reorder_at != null && i.reorder_at > 0 && i.count <= i.reorder_at && <Badge tone="warning" className="ml-1">low</Badge>}</td>
            <td className="p-1">{i.reorder_at || "-"}</td><td className="p-1">{i.supplier ?? "-"}</td></tr>))}</tbody></table>}
        {d.can_work && <><p className="text-sm text-muted">Load your items: CSV or Excel with Item, Unit, Reorder at, Reorder qty, Supplier, Supplier phone.</p><ImportStock /></>}
      </CardBody></Card>
    </div>
  );
}
