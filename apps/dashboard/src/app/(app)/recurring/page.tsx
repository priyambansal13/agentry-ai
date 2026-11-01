import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { BookNow, type Recurring, RecurringForm } from "@/components/ca-tool-forms";
import { api, getFeatures, requirePage } from "@/lib/session";

export const metadata = { title: "Recurring entries" };

const CATEGORIES = ["Rent", "Salaries & wages", "Utilities", "Software & subscriptions", "Professional fees", "Repairs & maintenance", "Marketing", "Travel & fuel", "Equipment", "Other"];
const EVERY: Record<string, string> = { weekly: "week", monthly: "month", quarterly: "quarter", yearly: "year" };

export default async function RecurringPage() {
  const active = await requirePage("recurring");
  const [{ items, monthly_cost }, features] = await Promise.all([api<{ items: Recurring[]; monthly_cost: number }>("/org/ca/recurring", { orgId: active.id }), getFeatures(active.id)]);
  const books = features.pages.includes("bookkeeping");
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Recurring entries</h1>
          <p className="mt-1 max-w-3xl text-muted">Rent, retainers, EMIs and subscriptions, booked into the books on their dates (never twice), so monthly spend, budgets and
            the Tally / CSV export include them. {books ? <>Budgets and their 80% alerts are in <Link href="/automations/bookkeeping" className="underline">Bookkeeping settings</Link>.</> : "Switch on the bookkeeping assistant to see them in your books and budgets."}</p>
        </div>
        <BookNow />
      </header>
      <Card><CardHeader><CardTitle>{items.length} entr{items.length === 1 ? "y" : "ies"}</CardTitle><span className="text-sm text-muted">about ₹{Math.round(monthly_cost).toLocaleString("en-IN")} a month with GST</span></CardHeader>
        <CardBody className="space-y-4">
          {items.map((e) => (
            <div key={e.id} className="space-y-2 rounded-xl border-2 border-line p-3">
              <p className="text-sm"><span className="font-semibold">{e.name}</span> · ₹{e.amount.toLocaleString("en-IN")}{e.gst_rate ? ` + ${e.gst_rate}% GST` : ""} every {EVERY[e.frequency]} to {e.vendor}
                {!e.active && <Badge className="ml-2">paused</Badge>}<span className="text-muted"> · next {e.next_on} · {e.booked} booked</span></p>
              <details><summary className="cursor-pointer text-sm underline">Edit</summary><div className="mt-2"><RecurringForm entry={e} categories={CATEGORIES} /></div></details>
            </div>))}
          <div className="border-t border-line pt-4"><p className="mb-2 font-semibold">Add one</p><RecurringForm categories={CATEGORIES} /></div>
        </CardBody></Card>
    </div>
  );
}
