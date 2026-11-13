import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import type { CaMeta } from "@/components/ca";
import { HubForm, ItrForm, ToolForm, type ToolSpec } from "@/components/ca-tool-forms";
import { api } from "@/lib/session";

/** The CA agents that work on one client's documents: GST, ITR, capital gains, bank statements, notices, TDS, 3CD. */
const SHEET = ".csv,.xlsx";
export const AGENT_LABEL: Record<string, string> = {
  ca_gst_reconciliation: "GST reconciliation", ca_itr_prep: "ITR computation", ca_capital_gains: "Capital gains", ca_bank_classifier: "Bank statement",
  ca_notice_handler: "Notice", ca_tds_returns: "TDS returns", ca_tax_audit: "Tax audit (3CD)", excel_desk: "Excel desk", excel_cleaner: "Excel cleaner", ca_anomaly_finder: "Anomaly finder", ca_upload_hub: "Upload hub", ca_gstr1: "GSTR-1 preparation", ca_financial_statements: "Financial statements", ca_tax_docs_reader: "Tax documents reader",
};

function specs(cid: string): (ToolSpec & { agent: string; title: string; needs?: string })[] {
  const p = (x: string) => `/org/ca/clients/${cid}/${x}`;
  return [
    { agent: "ca_notice_handler", title: "Notice", key: "notice", path: p("notices"), files: [{ name: "file", label: "The notice", accept: ".pdf,.jpg,.jpeg,.png,.txt" }],
      sample: true, button: "Read the notice", hint: "Upload an income-tax or GST notice: what it is, by when, how much, a draft reply, and a reply card on the board with the documents to collect." },
    { agent: "ca_gst_reconciliation", title: "GST reconciliation", key: "gst", path: p("gst"), extra: "period", sample: true, button: "Reconcile",
      files: [{ name: "gstr2b", label: "GSTR-2B (JSON, Excel or CSV)", accept: ".json,.csv,.xlsx" }, { name: "books", label: "Purchase register", accept: SHEET }],
      hint: "Matched, amounts that differ, invoices missing from 2B (ITC at risk) and from the books, and a message for each supplier who hasn't filed." },
    { agent: "ca_gstr1", needs: "ca_gst_reconciliation", title: "GSTR-1 preparation", key: "gstr1", path: p("gstr1"), extra: "period", sample: true, button: "Prepare GSTR-1",
      files: [{ name: "file", label: "Sales register for the month", accept: SHEET }],
      hint: "B2B, B2CL, B2CS, exports, credit / debit notes, HSN (B2B and B2C) and documents issued, in the GST offline tool's Excel layout; GSTINs, tax type for the place of supply, rates, values, invoice numbers and dates checked first." },
    { agent: "ca_financial_statements", needs: "ca_filing_tracker", title: "Financial statements", key: "fin", path: p("financials"), sample: true, button: "Prepare statements",
      files: [{ name: "file", label: "Trial balance (Tally export: this year and last)", accept: SHEET }],
      hint: "Schedule III balance sheet and profit & loss, ratios with the 25% changes to explain, and questions for the client wherever a figure moved a lot. Ledgers are placed by rules; you fix the rest once and it's learned." },
    { agent: "ca_capital_gains", title: "Capital gains", key: "cg", path: p("capital-gains"), sample: true, button: "Work out the gains",
      files: [{ name: "file", label: "Broker tax P&L / CAMS statement", accept: SHEET }],
      hint: "STCG / LTCG by section, grandfathering for shares bought before Feb 2018, rates before and after 23 Jul 2024; feeds the ITR computation." },
    { agent: "ca_bank_classifier", title: "Bank statement", key: "bank", path: p("bank"), sample: true, button: "Classify",
      files: [{ name: "file", label: "Statement (Excel or CSV from net banking)", accept: SHEET }],
      hint: "Every line tagged (your corrections become rules), totals by category, business receipts, and 44AD / 44ADA presumptive income." },
    { agent: "ca_tds_returns", title: "TDS returns", key: "tds", path: p("tds"), sample: true, button: "Check and prepare",
      files: [{ name: "file", label: "Payments register with TDS", accept: SHEET }],
      hint: "PAN and rate checks, late deduction / deposit interest, and the 24Q / 26Q deductee lines by quarter." },
    { agent: "ca_tax_audit", title: "Tax audit (3CD)", key: "audit", path: p("audit"), extra: "fy", sample: true, button: "Test the clauses",
      files: [{ name: "file", label: "Ledger / day book", accept: SHEET }],
      hint: "40A(3), 43B, 36(1)(va), 43B(h) MSME, 269SS / 269T / 269ST and 40(a)(ia) exceptions, with the disallowance for each." },
    { agent: "ca_anomaly_finder", needs: "excel_desk", title: "Anomaly finder", key: "anomalies", path: p("anomalies"), sample: true, button: "Find anomalies",
      files: [{ name: "file", label: "Ledger, day book or sales / purchase register", accept: SHEET }],
      hint: "Duplicates, repeated or missing voucher numbers, cash over the 40A(3) / 269ST limits, IGST vs CGST + SGST against the client's state, odd GST rates, invalid GSTINs, out-of-year dates, outliers and a Benford test." },
  ];
}

export async function CaTools({ clientId, meta, orgId }: { clientId: string; meta: CaMeta; orgId: string }) {
  const on = (k: string) => meta.enabled.includes(k);
  const tools = specs(clientId).filter((s) => on(s.needs ?? s.agent));
  const work = (await api<{ items: { id: string; agent: string; title: string; created_at: string }[] }>(`/org/ca/clients/${clientId}/work`, { orgId })).items;
  const itr = on("ca_itr_prep") ? await api<{ inputs: Record<string, number>; fields: Record<string, string>; from: { documents: number; capital_gains: boolean } }>(
    `/org/ca/clients/${clientId}/itr/prefill`, { orgId }) : null;
  return (
    <Card>
      <CardHeader><CardTitle>Work on this client</CardTitle><span className="text-sm text-muted">{work.length} result{work.length === 1 ? "" : "s"}</span></CardHeader>
      <CardBody className="space-y-5">
        {work.length > 0 && (
          <ul className="divide-y divide-line rounded-xl border-2 border-line">{work.slice(0, 12).map((w) => (
            <li key={w.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <Link href={`/ca-work/${w.id}`} className="font-medium hover:underline">{w.title}</Link>
              <span className="text-xs text-muted">{AGENT_LABEL[w.agent] ?? w.agent} · {new Date(w.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
            </li>))}</ul>)}
        {meta.can_work && (
          <details className="rounded-xl border-2 border-ink p-3" open={work.length === 0}>
            <summary className="cursor-pointer font-semibold">Drop many files or a zip</summary>
            <div className="mt-2"><HubForm clientId={clientId} /></div>
          </details>)}
        {meta.can_work && tools.map((s) => (
          <details key={s.key} className="rounded-xl border-2 border-line p-3">
            <summary className="cursor-pointer font-semibold">{s.title}</summary>
            <div className="mt-2"><ToolForm spec={s} clientId={clientId} /></div>
          </details>))}
        {meta.can_work && itr && (
          <details className="rounded-xl border-2 border-line p-3">
            <summary className="cursor-pointer font-semibold">ITR computation (old vs new regime)</summary>
            <div className="mt-2"><ItrForm clientId={clientId} fields={itr.fields} inputs={itr.inputs} from={itr.from} /></div>
          </details>)}
      </CardBody>
    </Card>
  );
}
