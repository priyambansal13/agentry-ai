import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { ToolForm } from "@/components/ca-tool-forms";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Excel desk" };

const SHEETS = ".csv,.xlsx";

export default async function ExcelPage() {
  const active = await requirePage("excel");
  const { items } = await api<{ items: { id: string; title: string; created_at: string; params: { kind?: string } }[] }>("/org/ca/excel", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Excel desk</h1>
        <p className="mt-1 max-w-3xl text-muted">Messy sheets cleaned, tables out of PDFs, two sheets reconciled, and questions answered from a sheet. The cleaner works by fixed rules. The AI only reads tables and turns
          questions into a calculation; every number is worked out from your file.</p>
      </header>
      <Card><CardHeader><CardTitle>Clean a messy sheet</CardTitle></CardHeader><CardBody>
        <ToolForm spec={{ key: "clean", path: "/org/ca/excel/clean", files: [{ name: "file", label: "Sheet", accept: SHEETS }], extra: "standardise_names", sample: true,
          button: "Clean it", hint: "The register or ledger a client sent: title lines, totals and repeated headers removed; \"1,200 Dr\", \"(500)\" and \"₹5,000\" made numbers; dates in one format; GSTIN / PAN checked; duplicates removed; similar party names grouped. Every change is listed." }} /></CardBody></Card>
      <Card><CardHeader><CardTitle>Find anomalies</CardTitle></CardHeader><CardBody>
        <ToolForm spec={{ key: "anomalies", path: "/org/ca/excel/anomalies", files: [{ name: "file", label: "Ledger, day book or register", accept: SHEETS }], sample: true,
          button: "Find anomalies", hint: "What a reviewer looks for, most serious first: duplicates, repeated or missing voucher numbers, cash over the 40A(3) / 269ST limits, wrong GST type for the state, odd rates, invalid GSTINs, dates outside the year, amounts just under limits, outliers, holidays and a Benford test. On a client's page the client's own GSTIN is used." }} /></CardBody></Card>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card><CardHeader><CardTitle>PDF or photo to Excel</CardTitle></CardHeader><CardBody>
          <ToolForm spec={{ key: "table", path: "/org/ca/excel/table", files: [{ name: "file", label: "PDF, photo or text", accept: ".pdf,.jpg,.jpeg,.png,.webp,.txt" }],
            extra: "columns", button: "Make the table", hint: "A statement, ledger or invoice list. Give your column layout to get it in that order; numbers not found in the source are marked." }} /></CardBody></Card>
        <Card><CardHeader><CardTitle>Reconcile two sheets</CardTitle></CardHeader><CardBody>
          <ToolForm spec={{ key: "reco", path: "/org/ca/excel/reconcile", files: [{ name: "first", label: "First sheet", accept: SHEETS }, { name: "second", label: "Second sheet", accept: SHEETS }],
            extra: "tolerance", button: "Reconcile", hint: "Books vs bank, debtors vs confirmations, your list vs the portal's. Matched on invoice / reference / party; amounts compared." }} /></CardBody></Card>
        <Card><CardHeader><CardTitle>Ask a sheet</CardTitle></CardHeader><CardBody>
          <ToolForm spec={{ key: "ask", path: "/org/ca/excel/ask", files: [{ name: "file", label: "Sheet", accept: SHEETS }], extra: "question", button: "Answer",
            hint: "\"Total TDS under 194C\", \"top 5 parties by amount\", \"how many invoices above 1 lakh\"." }} /></CardBody></Card>
      </div>
      {items.length > 0 && (
        <Card><CardHeader><CardTitle>Recent</CardTitle></CardHeader><CardBody className="p-0">
          <ul className="divide-y divide-line">{items.map((i) => (
            <li key={i.id} className="flex justify-between gap-2 px-4 py-2.5 text-sm"><Link href={`/ca-work/${i.id}`} className="font-medium hover:underline">{i.title}</Link>
              <span className="text-muted">{new Date(i.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span></li>))}</ul>
        </CardBody></Card>)}
    </div>
  );
}
