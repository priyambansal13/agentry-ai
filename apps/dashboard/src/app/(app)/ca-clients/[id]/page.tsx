import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  type CaClient, type CaMeta, Checklist, ClientForm, day, DeleteClient, FileActions, type Filing, FilingControls, NewFiling, STATUS_TONE,
  TrySamples, UploadFile,
} from "@/components/ca";
import { CaTools } from "@/components/ca-tools";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Client" };

type File = { id: string; filing_id: string | null; item_key: string | null; doc_type: string | null; filename: string; mime: string; bytes: number;
  source: string; created_at: string; read: boolean };
type Point = { severity: string; kind: string; message: string; sources: { file_id: string; file: string; quote: string }[] };
type Tax = { documents: { file_id: string; filename: string; doc_type: string; assessment_year: string | null;
  items: { category: string; description: string; payer: string | null; amount: number; tds: number; traced: boolean; quote: string }[] }[];
  points: Point[]; summary: { from: string; income: Record<string, number>; tds: number } | null; years: string[] };
type Due = { kind: string; period: string; due_on: string; title: string };

const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const INCOME: Record<string, string> = { salary: "Salary", interest_savings: "Savings interest", interest_deposit: "Deposit interest", interest_other: "Other interest",
  dividend: "Dividend", securities_sale: "Shares / MF sold", mutual_fund_sale: "Mutual funds sold", property_sale: "Property sold", rent: "Rent", other_income: "Other income" };

export default async function CaClientPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ay?: string; edit?: string }> }) {
  const active = await requirePage("ca-clients");
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const meta = await api<CaMeta>("/org/ca/meta", { orgId: active.id });
  let d: { client: CaClient & { notes: string | null }; filings: Filing[]; files: File[] };
  try {
    d = await api(`/org/ca/clients/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const on = (k: string) => meta.enabled.includes(k);
  const tax = on("ca_tax_docs_reader") ? await api<Tax>(`/org/ca/clients/${id}/tax${sp.ay ? `?ay=${encodeURIComponent(sp.ay)}` : ""}`, { orgId: active.id }) : null;
  const dates = on("ca_compliance_calendar") ? (await api<{ items: Due[] }>(`/org/ca/compliance/client/${id}`, { orgId: active.id })).items : null;
  const c = d.client;
  const flags = Object.entries(c.profile ?? {}).filter(([, v]) => v).map(([k]) => meta.profile_flags[k] ?? k);
  const open = d.filings.filter((f) => !["filed", "verified"].includes(f.status));
  const filingTitle = Object.fromEntries(d.filings.map((f) => [f.id, f.title]));
  return (
    <div className="space-y-6">
      <Link href="/ca-clients" className="text-sm text-muted hover:text-ink">← All clients</Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">{c.name}</h1>
          <p className="mt-1 text-muted">{[c.kind, c.pan, c.phone, c.email, c.gstin].filter(Boolean).join(" · ")}</p>
          {flags.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{flags.map((f) => <Badge key={f}>{f}</Badge>)}</div>}
        </div>
        {meta.can_work && <div className="flex gap-2"><Link href={sp.edit ? `/ca-clients/${id}` : `/ca-clients/${id}?edit=1`}
          className="inline-flex h-10 items-center rounded-xl border-2 border-line px-4 text-sm font-semibold hover:border-ink">{sp.edit ? "Close" : "Edit"}</Link>
          <DeleteClient id={id} name={c.name} /></div>}
      </header>
      {sp.edit && <Card><CardBody><ClientForm meta={meta} client={c} /></CardBody></Card>}

      <Card>
        <CardHeader><CardTitle>Filings</CardTitle><span className="text-sm text-muted">{open.length} open</span></CardHeader>
        <CardBody className="space-y-4">
          {d.filings.length === 0 && <p className="text-sm text-muted">No filings yet.</p>}
          {d.filings.map((f) => (
            <div key={f.id} className="space-y-2 rounded-xl border-2 border-line p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold">{f.title}{f.due_on && <span className="font-normal text-muted"> · due {day(f.due_on)}</span>}
                  {f.overdue && <Badge tone="danger" className="ml-2">overdue</Badge>}</p>
                <Badge tone={STATUS_TONE[f.status]}>{meta.statuses.find((s) => s.key === f.status)?.label}</Badge>
              </div>
              {on("ca_filing_tracker") && <FilingControls f={f} meta={meta} clientId={id} />}
              {on("ca_document_chaser") && (f.checklist?.length ?? 0) > 0 && <Checklist f={f} clientId={id} canWork={meta.can_work} />}
              {f.ack_no && <p className="text-sm text-muted">Acknowledgement {f.ack_no}{f.filed_on ? `, filed ${day(f.filed_on)}` : ""}</p>}
            </div>))}
          {meta.can_work && on("ca_filing_tracker") && <NewFiling meta={meta} clientId={id} />}
        </CardBody>
      </Card>

      {tax && (
        <Card>
          <CardHeader><CardTitle>Tax documents</CardTitle>
            <span className="flex items-center gap-3 text-sm">{tax.years.length > 1 && tax.years.map((y) => <Link key={y} href={`/ca-clients/${id}?ay=${y}`} className={sp.ay === y ? "font-semibold underline" : "underline"}>AY {y}</Link>)}
              {tax.documents.length > 0 && <a href={`/api/ca/clients/${id}/tax.xlsx${sp.ay ? `?ay=${sp.ay}` : ""}`} className="font-semibold underline">Download Excel</a>}</span></CardHeader>
          <CardBody className="space-y-4">
            {tax.documents.length === 0 ? (
              <div className="space-y-2 text-sm text-muted"><p>Upload Form 16, AIS, TIS or 26AS below (PDF with text, the JSON download, or a clear photo). Every number is kept with the line it came from,
                and the documents are compared: TDS per deductor, salary per employer, and income the department knows about that isn&apos;t in Form 16.</p>
                {meta.can_work && <TrySamples clientId={id} />}</div>
            ) : (
              <>
                <div>
                  <p className="mb-1.5 font-semibold">Points to check <span className="font-normal text-muted">({tax.points.length})</span></p>
                  {tax.points.length === 0 ? <p className="text-sm text-success">The documents agree.</p> : (
                    <ul className="space-y-2">{tax.points.map((p, n) => (
                      <li key={n} className={`rounded-xl border-2 p-3 text-sm ${p.severity === "high" ? "border-danger" : "border-line"}`}>
                        <p>{p.message}</p>
                        {p.sources.map((s, k) => <p key={k} className="mt-1 text-xs text-muted">{s.file}: “{s.quote}”</p>)}
                      </li>))}</ul>)}
                </div>
                {tax.summary && (
                  <div className="text-sm"><p className="mb-1 font-semibold">Income per {tax.summary.from}</p>
                    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-3">{Object.entries(tax.summary.income).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-2"><dt className="text-muted">{INCOME[k] ?? k}</dt><dd>{inr(v)}</dd></div>))}
                      <div className="flex justify-between gap-2"><dt className="text-muted">TDS</dt><dd>{inr(tax.summary.tds)}</dd></div></dl></div>)}
              </>
            )}
          </CardBody>
        </Card>
      )}

      <CaTools clientId={id} meta={meta} orgId={active.id} />

      <Card>
        <CardHeader><CardTitle>Files</CardTitle><span className="text-sm text-muted">{d.files.length}</span></CardHeader>
        <CardBody className="space-y-4">
          {meta.can_work && <UploadFile clientId={id} filings={open} reader={on("ca_tax_docs_reader")} />}
          {d.files.length > 0 && (
            <ul className="divide-y divide-line">{d.files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span><span className="font-medium">{f.filename}</span>
                  <span className="text-muted"> · {f.doc_type && f.doc_type !== "other" ? f.doc_type.toUpperCase() : "file"}{f.filing_id ? ` · ${filingTitle[f.filing_id] ?? ""}` : ""} · {f.source}</span></span>
                {meta.can_work && <FileActions id={f.id} clientId={id} canRead={on("ca_tax_docs_reader")} read={f.read} />}
              </li>))}</ul>)}
        </CardBody>
      </Card>

      {dates && (
        <Card>
          <CardHeader><CardTitle>Due dates in the next 12 months</CardTitle><span className="text-sm text-muted">from their profile</span></CardHeader>
          <CardBody>{dates.length === 0 ? <p className="text-sm text-muted">Nothing applies yet: tick GST, TDS, audit… when editing the client.</p> : (
            <ul className="grid gap-1 text-sm sm:grid-cols-2">{dates.slice(0, 40).map((x) => <li key={`${x.kind}${x.period}`}>{day(x.due_on)} · {x.title}</li>)}</ul>)}</CardBody>
        </Card>
      )}
    </div>
  );
}
