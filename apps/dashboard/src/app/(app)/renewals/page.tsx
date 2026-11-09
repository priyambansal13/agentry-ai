import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { AddRenewal, ImportRenewals, MarkRenewal } from "@/components/renewals";
import { pageApi as api, requirePage } from "@/lib/session";

export const metadata = { title: "Renewals" };

type R = { id: string; customer: string; item: string; due_on: string; amount: number | null; every: string; status: string; reminded: number[];
  winback_sent: boolean; payment_link: string | null; renewals: number; days_left: number };
type D = { items: R[]; stats: { due_30: number; due_30_value: number; lapsed: number; renewed: number }; can_work: boolean };
const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;

export default async function RenewalsPage() {
  const active = await requirePage("renewals");
  const d = await api<D>("/org/renewals", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Renewals</h1>
        <p className="mt-1 max-w-3xl text-muted">AMCs, memberships, policies and services that come due. Customers are reminded before (with a payment link when Razorpay
          is connected), lapsed ones get one win-back message, and birthdays get a wish. Renewing moves the date to the next cycle.</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-4">
        {[["Due in 30 days", `${d.stats.due_30} · ${inr(d.stats.due_30_value)}`], ["Lapsed", d.stats.lapsed], ["Renewed so far", d.stats.renewed]].map(([k, v]) => (
          <Card key={String(k)}><CardBody><p className="text-sm text-muted">{k}</p><p className="text-xl font-semibold">{v}</p></CardBody></Card>))}
      </div>
      <Card><CardBody className="p-0">{d.items.length === 0 ? <p className="p-5 text-muted">Nothing yet: import your customer list below.</p> : (
        <ul className="divide-y divide-line">{d.items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div><p className="font-semibold">{r.customer} · {r.item}</p>
              <p className="text-xs text-muted">due {r.due_on}{r.amount ? ` · ${inr(Number(r.amount))}` : ""} · every {r.every.replace("_", " ")}
                {r.reminded.length ? ` · reminded ${r.reminded.map((x) => `${x}d`).join(", ")}` : ""}{r.winback_sent ? " · win-back sent" : ""}
                {r.payment_link ? <> · <a href={r.payment_link} target="_blank" rel="noreferrer" className="underline">payment link</a></> : null}</p></div>
            <span className="flex items-center gap-3">{d.can_work && ["upcoming", "lapsed"].includes(r.status) && <MarkRenewal id={r.id} />}
              <Badge tone={r.status === "lapsed" ? "danger" : r.status === "upcoming" && r.days_left <= 7 ? "warning" : "neutral"}>
                {r.status === "upcoming" ? (r.days_left < 0 ? `${-r.days_left}d overdue` : `in ${r.days_left}d`) : r.status}</Badge></span>
          </li>))}</ul>)}</CardBody></Card>
      {d.can_work && (
        <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <Card><CardHeader><CardTitle>Add one</CardTitle></CardHeader><CardBody><AddRenewal /></CardBody></Card>
          <Card><CardHeader><CardTitle>Import your list</CardTitle></CardHeader><CardBody className="space-y-2">
            <p className="text-sm text-muted">CSV or Excel: Customer, Mobile, Email, Plan, Renewal date, Amount, Frequency, Date of birth.</p><ImportRenewals /></CardBody></Card>
        </div>)}
    </div>
  );
}
