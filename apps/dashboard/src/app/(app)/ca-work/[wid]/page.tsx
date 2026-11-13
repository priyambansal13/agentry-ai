import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AGENT_LABEL } from "@/components/ca-tools";
import { BankLineCategory, CopyText, DeleteWork, LedgerLine, TaxOpening } from "@/components/ca-tool-forms";
import { api, ApiError, getActiveOrg, getFeatures } from "@/lib/session";

export const metadata = { title: "Result" };

/* eslint-disable @typescript-eslint/no-explicit-any -- each agent's result has its own shape (agentry/automations/ca/*.py) */
type Work = { id: string; client_id: string | null; agent: string; title: string; result: any; params: any; created_at: string; file_ids: string[] };

const inr = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${v < 0 ? "-" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`);
const Row = ({ k, v, strong }: { k: string; v: React.ReactNode; strong?: boolean }) => (
  <div className={`flex justify-between gap-4 py-1 ${strong ? "font-semibold" : ""}`}><dt className={strong ? "" : "text-muted"}>{k}</dt><dd className="text-right">{v}</dd></div>);
const Table = ({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) => (
  <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-muted"><tr>{head.map((h) => <th key={h} className="whitespace-nowrap p-2">{h}</th>)}</tr></thead>
    <tbody className="divide-y divide-line">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="p-2 align-top">{c}</td>)}</tr>)}</tbody></table></div>);

const GST_LABEL: Record<string, [string, "success" | "warning" | "danger" | "neutral"]> = {
  matched: ["Matched", "success"], amount_differs: ["Amount differs", "warning"], missing_in_2b: ["Not in 2B", "danger"],
  missing_in_books: ["Not in books", "warning"], gstin_differs: ["GSTIN differs", "warning"] };

function Gst({ r }: { r: any }) {
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-3">
      <Row k="ITC in the books" v={inr(r.itc_in_books)} /><Row k="ITC in GSTR-2B" v={inr(r.itc_in_2b)} /><Row k="ITC at risk" v={inr(r.itc_at_risk)} strong />
      {Object.entries(r.totals).map(([k, v]: [string, any]) => <Row key={k} k={GST_LABEL[k]?.[0] ?? k} v={`${v.count} · ${inr(v.tax)}`} />)}</dl></CardBody></Card>
    <Card><CardHeader><CardTitle>Invoices</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["", "Supplier", "Invoice", "Date", "Tax (books)", "Tax (2B)", "Difference"]} rows={r.rows.map((x: any) => {
        const b = x.books ?? {}, g = x.gstr2b ?? {};
        return [<Badge key="s" tone={GST_LABEL[x.status]?.[1]}>{GST_LABEL[x.status]?.[0]}</Badge>, <span key="n">{b.name || g.name}<span className="block text-xs text-muted">{b.gstin || g.gstin}</span></span>,
          b.invoice || g.invoice, b.date || g.date, inr(b.tax), inr(g.tax), x.status === "matched" ? "" : inr(x.tax_difference)];
      })} /></CardBody></Card>
    {r.messages?.length > 0 && <Card><CardHeader><CardTitle>Messages to suppliers</CardTitle></CardHeader><CardBody className="space-y-3">
      {r.messages.map((m: any) => <div key={m.gstin} className="rounded-xl border-2 border-line p-3 text-sm"><p className="flex justify-between font-semibold">{m.supplier} · {inr(m.tax)} at risk <CopyText text={m.message} /></p>
        <pre className="mt-1 whitespace-pre-wrap font-sans text-ink-soft">{m.message}</pre></div>)}</CardBody></Card>}
  </>);
}

function Itr({ r }: { r: any }) {
  const keys: [string, string][] = [["gross_total_income", "Gross total income"], ["total_deductions", "Deductions"], ["total_income", "Total income"], ["slab_tax", "Tax at slab rates"],
    ["special_rate_tax", "Tax on capital gains (111A / 112A)"], ["rebate_87a", "Rebate 87A"], ["surcharge", "Surcharge"], ["cess", "Cess 4%"], ["tax_liability", "Tax liability"],
    ["taxes_paid", "TDS and taxes paid"], ["payable", "Payable"], ["refund", "Refund"]];
  return (<>
    <Card><CardBody className="space-y-1"><p className="text-lg font-semibold">The {r.better} regime costs less, by {inr(r.saving)}.</p><p className="text-sm text-muted">Form: {r.itr_form}</p></CardBody></Card>
    <Card><CardBody className="p-0"><Table head={["", "Old regime", "New regime"]} rows={[
      ...Array.from(new Set([...r.old.heads, ...r.new.heads].map((h: any) => h.label))).map((l) => [l, inr(r.old.heads.find((h: any) => h.label === l)?.amount ?? 0), inr(r.new.heads.find((h: any) => h.label === l)?.amount ?? 0)]),
      ...keys.map(([k, l]) => [<span key={k} className={["tax_liability", "payable", "refund"].includes(k) ? "font-semibold" : ""}>{l}</span>, inr(r.old[k]), inr(r.new[k])]),
    ]} /></CardBody></Card>
    <Card><CardHeader><CardTitle>Deductions</CardTitle></CardHeader><CardBody className="text-sm">{Object.keys(r.old.deductions).length === 0 ? "None" :
      Object.entries(r.old.deductions).map(([k, v]: [string, any]) => <Row key={k} k={k} v={`${inr(v)} (old) · ${inr(r.new.deductions[k] ?? 0)} (new)`} />)}</CardBody></Card>
    {[...r.old.notes, ...r.new.notes].map((n: string) => <p key={n} className="text-sm text-warning">{n}</p>)}
  </>);
}

function CapGains({ r }: { r: any }) {
  const s = r.summary;
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="STCG 111A before 23 Jul 2024 (15%)" v={inr(s.by_section.stcg_111a_pre ?? 0)} /><Row k="STCG 111A from 23 Jul 2024 (20%)" v={inr(s.by_section.stcg_111a_post ?? 0)} />
      <Row k="LTCG 112A before 23 Jul 2024 (10%)" v={inr(s.by_section.ltcg_112a_pre ?? 0)} /><Row k="LTCG 112A from 23 Jul 2024 (12.5%)" v={inr(s.by_section.ltcg_112a_post ?? 0)} />
      <Row k="Other LTCG (12.5%)" v={inr(s.ltcg_other)} /><Row k="Other STCG (slab)" v={inr(s.stcg_other)} />
      <Row k="Sales" v={s.sales} /><Row k="Rows to check" v={s.flagged} strong={s.flagged > 0} /></dl>
      {s.notes.map((n: string) => <p key={n} className="mt-2 text-sm text-warning">{n}</p>)}</CardBody></Card>
    <Card><CardBody className="p-0"><Table head={["Name", "Bought", "Sold", "Cost used", "Sale value", "Gain", "Section", "Check"]} rows={r.rows.map((x: any) => [
      x.name, x.buy_date, x.sell_date, inr(x.cost), inr(x.sell_value), inr(x.gain), x.section ?? "-", <span key="f" className="text-xs text-warning">{(x.flags ?? []).join("; ")}</span>])} /></CardBody></Card>
  </>);
}

function Bank({ r, wid }: { r: any; wid: string }) {
  const t = r.totals;
  const categories = Object.keys(t.by_category).concat(["Sales / receipts", "Professional fees received", "Salary received", "Interest received", "Dividend", "Refund", "Loan received",
    "Transfer (own accounts)", "Cash deposit", "Cash withdrawal", "Purchases / suppliers", "Salaries paid", "Rent", "Utilities & phone", "Travel & fuel", "Meals & entertainment",
    "Software & subscriptions", "Professional fees paid", "Bank charges", "Loan EMI", "GST paid", "Income tax / TDS paid", "Insurance", "Investments", "Drawings / personal", "Other"]);
  const cats = Array.from(new Set(categories));
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Business receipts" v={inr(t.receipts)} strong /><Row k="of which cash" v={inr(t.cash_receipts)} />
      <Row k="44AD presumptive income (6% digital + 8% cash)" v={inr(t.presumptive_44ad)} /><Row k="44ADA presumptive income (50%)" v={inr(t.presumptive_44ada)} />
      <Row k="Total in / out" v={`${inr(t.total_in)} / ${inr(t.total_out)}`} /><Row k="Lines to glance at (AI or default)" v={t.to_glance} /></dl>
      {t.flags.map((f: string) => <p key={f} className="mt-2 text-sm text-warning">{f}</p>)}</CardBody></Card>
    <Card><CardHeader><CardTitle>By category</CardTitle></CardHeader><CardBody className="p-0"><Table head={["Category", "In", "Out", "Lines"]}
      rows={Object.entries(t.by_category).map(([k, v]: [string, any]) => [k, inr(v.in), inr(v.out), v.count])} /></CardBody></Card>
    <Card><CardHeader><CardTitle>Lines</CardTitle><span className="text-sm text-muted">change a category; &quot;learn&quot; applies it to this payee from now on</span></CardHeader><CardBody className="p-0">
      <Table head={["Date", "Narration", "Out", "In", "Category"]} rows={r.lines.map((l: any) => [l.date, <span key="n" className="text-xs">{l.narration}</span>, l.out ? inr(l.out) : "", l.in ? inr(l.in) : "",
        <span key="c" className="flex items-center gap-1"><BankLineCategory wid={wid} row={l.row} category={l.category} categories={cats} />{l.by !== "rule" && l.by !== "pattern" && l.by !== "you" && <span className="text-xs text-muted">{l.by}</span>}</span>])} />
    </CardBody></Card>
  </>);
}

function Notice({ r }: { r: any }) {
  return (<>
    <Card><CardBody className="space-y-2">
      <p className="text-lg font-semibold">{r.summary}</p>
      <dl className="grid gap-x-8 sm:grid-cols-2"><Row k="Section" v={r.section ?? "-"} /><Row k="Assessment year" v={r.assessment_year ?? "-"} /><Row k="DIN" v={r.din ?? "-"} />
        <Row k="Issued" v={r.issued_on ?? "-"} /><Row k="Respond by" v={r.respond_by ?? "not printed"} strong /><Row k="Demand" v={inr(r.demand)} /></dl>
      {r.flags?.map((f: string) => <p key={f} className="text-sm text-warning">{f}</p>)}
      {r.filing_id && <p className="text-sm">A reply card is on the <Link href="/filings" className="underline">filing board</Link>, due a few days before the deadline.</p>}
    </CardBody></Card>
    <Card><CardHeader><CardTitle>Why it was sent</CardTitle></CardHeader><CardBody className="space-y-3 text-sm"><p>{r.why}</p>
      {r.what_to_do?.length > 0 && <><p className="font-semibold">What to do</p><ol className="list-decimal space-y-1 pl-5">{r.what_to_do.map((x: string) => <li key={x}>{x}</li>)}</ol></>}
      {r.documents_needed?.length > 0 && <><p className="font-semibold">Documents to collect</p><ul className="list-disc pl-5">{r.documents_needed.map((x: string) => <li key={x}>{x}</li>)}</ul></>}
      {r.quotes?.length > 0 && <><p className="font-semibold">From the notice</p>{r.quotes.map((q: string) => <p key={q} className="text-xs text-muted">“{q}”</p>)}</>}
    </CardBody></Card>
    {r.draft_reply && <Card><CardHeader><CardTitle>Draft reply</CardTitle><CopyText text={r.draft_reply} /></CardHeader><CardBody>
      <pre className="whitespace-pre-wrap font-sans text-sm">{r.draft_reply}</pre></CardBody></Card>}
  </>);
}

function Tds({ r }: { r: any }) {
  return (<>
    <Card><CardBody><dl><Row k="Interest under 201(1A) to pay with the return" v={inr(r.interest)} strong /><Row k="Checks" v={r.issues.length} /></dl></CardBody></Card>
    <Card><CardHeader><CardTitle>By quarter and section</CardTitle></CardHeader><CardBody className="p-0"><Table head={["Form", "Quarter", "Section", "Deductees", "Amount", "TDS", "Interest"]}
      rows={r.summary.map((s: any) => [s.form, s.quarter, <span key="s">{s.section}<span className="block text-xs text-muted">{s.label}</span></span>, s.deductees, inr(s.amount), inr(s.tds), inr(s.interest)])} /></CardBody></Card>
    {r.issues.length > 0 && <Card><CardHeader><CardTitle>To fix before filing</CardTitle></CardHeader><CardBody className="p-0"><Table head={["Row", "Deductee", "Section", "Check"]}
      rows={r.issues.map((i: any) => [i.row, i.name, i.section, i.problems.join("; ")])} /></CardBody></Card>}
  </>);
}

function Audit({ r }: { r: any }) {
  return (<>
    <Card><CardBody><dl><Row k={`Disallowance found (FY ${r.fy})`} v={inr(r.disallowance)} strong /><Row k="Ledger entries tested" v={r.entries} /></dl></CardBody></Card>
    {r.clauses.length === 0 ? <p className="text-success">No exceptions in the clauses tested.</p> : r.clauses.map((c: any) => (
      <Card key={c.clause}><CardHeader><CardTitle>{c.label}</CardTitle><span className="text-sm text-muted">{c.items.length} · {inr(c.disallow)} disallowed</span></CardHeader>
        <CardBody className="p-0"><Table head={["Party", "Date", "Amount", "Why"]} rows={c.items.map((i: any) => [i.party, i.date, inr(i.amount), i.why])} /></CardBody></Card>))}
  </>);
}

function Excel({ r, title }: { r: any; title: string }) {
  if (r.counts) {
    return (<>
      <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">{Object.entries(r.counts).map(([k, v]: [string, any]) => <Row key={k} k={k.replace(/_/g, " ")} v={v} />)}
        <Row k="Matched on" v={`${r.key_columns[0].join(" + ")} ↔ ${r.key_columns[1].join(" + ")}`} /><Row k="Amounts" v={r.amount_columns.filter(Boolean).join(" ↔ ") || "none"} /></dl></CardBody></Card>
      {r.amount_differs.length > 0 && <Card><CardHeader><CardTitle>Amounts differ</CardTitle></CardHeader><CardBody className="p-0"><Table head={["Key", "Difference"]} rows={r.amount_differs.map((x: any) => [x.key, inr(x.difference)])} /></CardBody></Card>}
      {r.only_first.length > 0 && <Card><CardHeader><CardTitle>Only in the first</CardTitle></CardHeader><CardBody className="p-0"><Table head={r.headers[0]} rows={r.only_first.map((x: any) => x.first)} /></CardBody></Card>}
      {r.only_second.length > 0 && <Card><CardHeader><CardTitle>Only in the second</CardTitle></CardHeader><CardBody className="p-0"><Table head={r.headers[1]} rows={r.only_second.map((x: any) => x.second)} /></CardBody></Card>}
    </>);
  }
  if (r.columns) {
    return <Card><CardHeader><CardTitle>{r.rows.length} rows</CardTitle>{r.photo && <span className="text-sm text-warning">from a photo: check the numbers</span>}</CardHeader>
      <CardBody className="p-0"><Table head={[...r.columns, ""]} rows={r.rows.map((row: string[], i: number) => [...row, r.checked[i] ? "" : <Badge key="c" tone="warning">check</Badge>])} /></CardBody></Card>;
  }
  const a = r.answer;
  return (<Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardBody className="space-y-2">
    {"value" in a && <p className="text-2xl font-semibold">{typeof a.value === "number" && r.spec.agg !== "count" ? inr(a.value) : a.value}</p>}
    {a.groups && <Table head={[r.spec.group_by, r.spec.agg]} rows={a.groups.map((g: any[]) => [g[0], r.spec.agg === "count" ? g[1] : inr(g[1])])} />}
    {a.rows && <Table head={a.rows[0]} rows={a.rows.slice(1)} />}
    <p className="text-xs text-muted">{a.count} matching rows · {r.spec.agg}{r.spec.measure ? ` of ${r.spec.measure}` : ""}{r.spec.filter?.length ? ` where ${r.spec.filter.map((f: any) => `${f.column} ${f.op} ${f.value}`).join(" and ")}` : ""} (worked out from the sheet, not by the AI)</p>
  </CardBody></Card>);
}

function Cleaner({ r }: { r: any }) {
  const s = r.summary;
  const shown = r.rows.slice(0, 100);
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Rows in → clean rows out" v={`${s.rows_in} → ${s.rows_out}`} /><Row k="Header found on line" v={s.header_row} />
      <Row k="Columns" v={`${s.columns} (${s.dates} date, ${s.numbers} number)`} /><Row k="To check" v={r.issue_count ? <Badge tone="warning">{r.issue_count}</Badge> : "nothing"} /></dl></CardBody></Card>
    <Card><CardHeader><CardTitle>What was done</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Change", "How many", "Examples"]} rows={r.changes.map((c: any) => [c.what, c.count, <span key="e" className="text-muted">{c.examples.join(" · ")}</span>])} /></CardBody></Card>
    {r.issues.length > 0 && <Card><CardHeader><CardTitle>To check</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Row", "Column", "Value", "Why"]} rows={r.issues.map((i: any) => [i.row ?? "whole column", i.column, i.value, i.problem])} /></CardBody></Card>}
    {r.name_groups.length > 0 && <Card><CardHeader><CardTitle>Similar names{r.name_column ? ` (${r.name_column})` : ""}</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Use", "Also written as", "Rows"]} rows={r.name_groups.map((g: any) => [g.use, g.variants.join(" · "), g.rows])} /></CardBody></Card>}
    <Card><CardHeader><CardTitle>Clean sheet{r.rows.length > shown.length ? ` (first ${shown.length} of ${r.rows.length} rows; download for all)` : ""}</CardTitle></CardHeader>
      <CardBody className="p-0"><Table head={r.columns} rows={shown.map((row: any[]) => row.map((v) => (v === null ? "" : String(v))))} /></CardBody></Card>
  </>);
}

const SEV: Record<string, "danger" | "warning" | "neutral"> = { high: "danger", medium: "warning", low: "neutral" };
function Anomalies({ r }: { r: any }) {
  const s = r.summary;
  const used = Object.entries(r.columns).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(" · ");
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Rows checked" v={s.rows} /><Row k="Total of the amounts" v={inr(s.total)} />
      <Row k="Serious" v={s.high ? <Badge tone="danger">{s.high} rows</Badge> : "none"} /><Row k="Worth a look" v={s.medium ? <Badge tone="warning">{s.medium} rows</Badge> : "none"} />
      <Row k="Minor" v={s.low || "none"} />{r.fy_start && <Row k="Year" v={`FY ${r.fy_start}-${String(r.fy_start + 1).slice(2)}`} />}</dl>
      <p className="mt-2 text-xs text-muted">Columns read: {used}</p>
      {r.skipped.map((x: string) => <p key={x} className="text-xs text-muted">Not checked: {x}</p>)}</CardBody></Card>
    {r.findings.length === 0 && <Card><CardBody>Nothing found by any check.</CardBody></Card>}
    {r.findings.map((f: any) => (
      <Card key={f.key}><CardHeader><CardTitle><Badge tone={SEV[f.severity]}>{f.severity}</Badge> {f.title} ({f.count})</CardTitle></CardHeader>
        <CardBody className="space-y-2 p-0"><p className="px-4 text-sm text-muted">{f.why}</p>
          <Table head={["Row", "Date", "Voucher", "Party", "Amount", "Why"]} rows={f.rows.slice(0, 50).map((x: any) => [x.row ?? "", x.date ?? "", x.voucher ?? "", x.party ?? "", typeof x.amount === "number" ? inr(x.amount) : "", x.note])} />
          {f.rows.length > 50 && <p className="px-4 pb-3 text-xs text-muted">and {f.count - 50} more in the Excel download</p>}</CardBody></Card>))}
    {r.benford && <Card><CardHeader><CardTitle>Benford first-digit test: {r.benford.verdict}</CardTitle></CardHeader><CardBody>
      <p className="mb-2 text-sm text-muted">{r.benford.n} amounts; chi-square {r.benford.chi2} (above 20.1 doesn&apos;t fit at 1%). Natural amounts start with 1 about 30% of the time and with 9 about 5%.</p>
      <Table head={["First digit", "Expected", "In this sheet"]} rows={r.benford.digits.map((d: any) => [d.digit, `${d.expected}%`, `${d.actual}%`])} /></CardBody></Card>}
  </>);
}

const HUB_STATUS: Record<string, [string, "success" | "warning" | "danger" | "neutral"]> = {
  filed: ["filed", "success"], duplicate: ["already had it", "neutral"], skipped: ["skipped", "warning"], error: ["couldn't take", "danger"] };
function Hub({ r }: { r: any }) {
  const s = r.summary;
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Files" v={s.files} /><Row k="Filed on the client" v={s.filed} /><Row k="Checklist items ticked" v={s.ticked} /><Row k="Agents run" v={s.agents} />
      {s.duplicates > 0 && <Row k="Already had (not stored again)" v={s.duplicates} />}{s.problems > 0 && <Row k="Need a look" v={<Badge tone="warning">{s.problems}</Badge>} />}
      <Row k="Sent from" v={r.source === "client_portal" ? "the client's portal" : "the firm"} /></dl></CardBody></Card>
    <Card><CardHeader><CardTitle>Every file</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["File", "", "Taken as", "Ticked", "What happened"]} rows={r.files.map((f: any) => [
        f.file_id ? <a key="f" href={`/api/ca/files/${f.file_id}`} className="font-medium hover:underline">{f.filename}</a> : f.filename,
        <Badge key="s" tone={HUB_STATUS[f.status]?.[1] ?? "neutral"}>{HUB_STATUS[f.status]?.[0] ?? f.status}</Badge>,
        f.recognised ?? "-", f.ticked ?? "",
        f.ran ? (f.ran.work_id ? <Link key="w" href={`/ca-work/${f.ran.work_id}`} className="underline">{AGENT_LABEL[f.ran.agent] ?? f.ran.agent}</Link> : `${AGENT_LABEL[f.ran.agent] ?? f.ran.agent}: ${f.ran.note ?? "done"}`)
          : <span key="n" className={f.agent_error ? "text-danger" : "text-muted"}>{f.agent_error ?? f.why ?? f.next ?? ""}</span>])} /></CardBody></Card>
  </>);
}

const G1_TABLES: [string, string, string[], (x: any[]) => React.ReactNode[]][] = [
  ["b2b", "B2B (4A)", ["GSTIN", "Customer", "Invoice", "Date", "Value", "Place of supply", "Rate", "Taxable"], (x) => [x[0], x[1], x[2], x[3], inr(x[4]), x[5], `${x[10]}%`, inr(x[11])]],
  ["b2cl", "B2C large (5)", ["Invoice", "Date", "Value", "Place of supply", "Rate", "Taxable"], (x) => [x[0], x[1], inr(x[2]), x[3], `${x[5]}%`, inr(x[6])]],
  ["b2cs", "B2C small (7)", ["Place of supply", "Rate", "Taxable"], (x) => [x[1], `${x[3]}%`, inr(x[4])]],
  ["exp", "Exports (6A)", ["Type", "Invoice", "Date", "Value", "Port", "Shipping bill", "Rate", "Taxable"], (x) => [x[0], x[1], x[2], inr(x[3]), x[4], x[5] ? `${x[5]} (${x[6]})` : "-", `${x[7]}%`, inr(x[8])]],
  ["cdnr", "Credit / debit notes, registered (9B)", ["GSTIN", "Customer", "Note", "Date", "C/D", "Value", "Rate", "Taxable"], (x) => [x[0], x[1], x[2], x[3], x[4], inr(x[8]), `${x[10]}%`, inr(x[11])]],
  ["cdnur", "Credit / debit notes, unregistered (9B)", ["Type", "Note", "Date", "C/D", "Place of supply", "Value", "Rate", "Taxable"], (x) => [x[0], x[1], x[2], x[3], x[4], inr(x[5]), `${x[7]}%`, inr(x[8])]],
  ["hsn_b2b", "HSN summary, B2B (12)", ["HSN", "Description", "UQC", "Qty", "Rate", "Taxable", "IGST", "CGST", "SGST"], (x) => [x[0], x[1], x[2], x[3], `${x[5]}%`, inr(x[6]), inr(x[7]), inr(x[8]), inr(x[9])]],
  ["hsn_b2c", "HSN summary, B2C (12)", ["HSN", "Description", "UQC", "Qty", "Rate", "Taxable", "IGST", "CGST", "SGST"], (x) => [x[0], x[1], x[2], x[3], `${x[5]}%`, inr(x[6]), inr(x[7]), inr(x[8]), inr(x[9])]],
  ["docs", "Documents issued (13)", ["Nature", "From", "To", "Total", "Cancelled"], (x) => x],
];
function Gstr1({ r }: { r: any }) {
  const s = r.summary;
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Period" v={r.period ?? "-"} /><Row k="Client's state" v={r.client_state || "-"} /><Row k="Register rows" v={s.rows} />
      <Row k="B2CL above" v={inr(r.b2cl_limit)} />
      <Row k="To fix before filing" v={s.high ? <Badge tone="danger">{s.high}</Badge> : "none"} /><Row k="To check" v={s.medium + s.low || "none"} /></dl></CardBody></Card>
    {r.issues.length > 0 && <Card><CardHeader><CardTitle>Checks</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["", "Row", "Invoice", "Problem", "Value"]} rows={r.issues.map((i: any) => [<Badge key="s" tone={SEV[i.severity]}>{i.severity}</Badge>, i.row ?? "", i.invoice, i.problem, i.value])} /></CardBody></Card>}
    <Card><CardHeader><CardTitle>Totals by table</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Table", "Documents", "Taxable", "IGST", "CGST", "SGST", "Cess"]} rows={Object.entries(r.totals).map(([k, v]: [string, any]) => [k === "all" ? <b key="a">All</b> : k.toUpperCase(), v.count, inr(v.taxable), inr(v.igst), inr(v.cgst), inr(v.sgst), inr(v.cess)])} /></CardBody></Card>
    {G1_TABLES.filter(([k]) => r.tables[k]?.length).map(([k, title, head, row]) => (
      <Card key={k}><CardHeader><CardTitle>{title} ({r.tables[k].length})</CardTitle></CardHeader><CardBody className="p-0">
        <Table head={head} rows={r.tables[k].slice(0, 100).map(row)} /></CardBody></Card>))}
    <p className="text-xs text-muted">Download Excel gives each table as a sheet of the GST offline tool&apos;s workbook (headings on row 4): check it against the latest tool before importing.</p>
  </>);
}

const FS_LINES: [string, string][] = [["share_capital", "Share capital / capital"], ["reserves", "Reserves and surplus"], ["lt_borrowings", "Long-term borrowings"],
  ["deferred_tax_liab", "Deferred tax liabilities"], ["lt_provisions", "Long-term provisions"], ["st_borrowings", "Short-term borrowings"], ["trade_payables", "Trade payables"],
  ["other_cl", "Other current liabilities"], ["st_provisions", "Short-term provisions"], ["ppe", "Property, plant and equipment"], ["intangibles", "Intangible assets"],
  ["cwip", "Capital work-in-progress"], ["nc_investments", "Non-current investments"], ["deferred_tax_asset", "Deferred tax assets"], ["lt_loans_adv", "Long-term loans and advances"],
  ["other_nca", "Other non-current assets"], ["current_investments", "Current investments"], ["inventories", "Inventories"], ["trade_receivables", "Trade receivables"],
  ["cash_bank", "Cash and cash equivalents"], ["st_loans_adv", "Short-term loans and advances"], ["other_ca", "Other current assets"], ["revenue", "Revenue from operations"],
  ["other_income", "Other income"], ["purchases", "Purchases / materials"], ["opening_stock", "Opening stock"], ["employee", "Employee benefits"], ["finance", "Finance costs"],
  ["depreciation", "Depreciation"], ["other_expenses", "Other expenses"], ["tax", "Tax expense"], ["suspense", "Suspense (to clear)"]];
const PL_ROWS: [string, string, boolean?][] = [["revenue", "Revenue from operations"], ["other_income", "Other income"], ["total_income", "Total income", true],
  ["purchases", "Purchases / materials"], ["change_inventory", "Changes in inventories"], ["employee", "Employee benefits expense"], ["finance", "Finance costs"],
  ["depreciation", "Depreciation and amortisation"], ["other_expenses", "Other expenses"], ["total_expenses", "Total expenses", true], ["pbt", "Profit before tax", true],
  ["tax", "Tax expense"], ["pat", "Profit for the year", true]];
function Financials({ r, wid }: { r: any; wid: string }) {
  const py = r.has_py;
  const bs = r.balance_sheet;
  const cols = (cy: number, p: number) => [inr(cy), ...(py ? [inr(p)] : [])];
  const head = ["", "This year", ...(py ? ["Previous year"] : [])];
  const side = (secs: any[], total: any) => [...secs.flatMap((s: any) => [[<b key="s">{s.section}</b>, ...cols(s.cy, s.py)],
    ...s.lines.map((l: any) => [<span key="l" className="pl-4">{l.label}</span>, ...cols(l.cy, l.py)])]), [<b key="t">Total</b>, ...cols(total.cy, total.py)]];
  const unplaced = r.ledgers.filter((x: any) => !x.line || x.how === "ai");
  return (<>
    {r.checks.length > 0 && <Card><CardHeader><CardTitle>Checks</CardTitle></CardHeader><CardBody><ul className="space-y-1.5 text-sm">{r.checks.map((c: any, i: number) =>
      <li key={i} className="flex gap-2"><Badge tone={SEV[c.severity]}>{c.severity}</Badge>{c.what}</li>)}</ul></CardBody></Card>}
    {unplaced.length > 0 && <Card><CardHeader><CardTitle>Ledgers to place or check ({unplaced.length})</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Ledger", "Group", "This year (Dr +)", "Line"]} rows={unplaced.map((x: any) => [x.name, x.group || "-", inr(x.cy),
        <LedgerLine key="l" wid={wid} ledger={x.name} line={x.line} lines={FS_LINES} />])} /></CardBody></Card>}
    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>Balance sheet {bs.balanced ? "" : "(doesn't balance yet)"}</CardTitle></CardHeader><CardBody className="space-y-3 p-0">
        <Table head={["Equity and liabilities", ...head.slice(1)]} rows={side(bs.equity_liabilities, { cy: bs.totals.cy.el, py: bs.totals.py.el })} />
        <Table head={["Assets", ...head.slice(1)]} rows={side(bs.assets, { cy: bs.totals.cy.a, py: bs.totals.py.a })} /></CardBody></Card>
      <Card><CardHeader><CardTitle>Statement of profit and loss</CardTitle></CardHeader><CardBody className="p-0">
        <Table head={head} rows={PL_ROWS.map(([k, l, b]) => [b ? <b key="b">{l}</b> : l, ...cols(r.profit_and_loss.cy[k], r.profit_and_loss.py[k])])} />
        <p className="px-4 pb-3 text-xs text-muted">Profit for the year is added to {r.profit_to.toLowerCase()}.</p></CardBody></Card>
    </div>
    {r.review.length > 0 && <Card><CardHeader><CardTitle>Questions for the client ({r.review.length})</CardTitle></CardHeader><CardBody>
      <ol className="ml-5 list-decimal space-y-1.5 text-sm">{r.review.map((q: any) => <li key={q.key}>{q.question}</li>)}</ol>
      <div className="mt-2"><CopyText text={r.review.map((q: any, i: number) => `${i + 1}. ${q.question}`).join("\n")} /></div></CardBody></Card>}
    <Card><CardHeader><CardTitle>Ratios</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Ratio", "This year", ...(py ? ["Previous year", "Change"] : [])]} rows={r.ratios.map((x: any) => [x.name, x.cy ?? "-",
        ...(py ? [x.py ?? "-", x.change_pct === null ? "-" : <span key="c" className={x.explain ? "font-semibold text-danger" : ""}>{x.change_pct}%{x.explain ? " (explain)" : ""}</span>] : [])])} />
      <p className="px-4 pb-3 text-xs text-muted">Schedule III asks companies to explain any ratio that changed by more than 25%.</p></CardBody></Card>
    <details className="rounded-xl border-2 border-line p-3"><summary className="cursor-pointer font-semibold">Every ledger and where it went ({r.ledgers.length})</summary>
      <Table head={["Ledger", "Group", "This year", "Line", "By"]} rows={r.ledgers.map((x: any) => [x.name, x.group || "-", inr(x.cy),
        <LedgerLine key="l" wid={wid} ledger={x.name} line={x.line} lines={FS_LINES} />, x.how ?? ""])} /></details>
  </>);
}

const DEP_SEV: Record<string, "danger" | "warning" | "neutral"> = { serious: "danger", warning: "warning", info: "neutral" };
function Depreciation({ r, wid }: { r: any; wid: string }) {
  const s = r.summary;
  const d = r.deferred_tax;
  const pct = (x: number) => `${+(x * 100).toFixed(3)}%`;
  const t = r.book_total;
  return (<>
    <Card><CardBody><dl className="grid gap-x-8 sm:grid-cols-2">
      <Row k="Year" v={`${r.year.label} (${r.year.start} to ${r.year.end})`} /><Row k="Assets" v={`${s.assets} (${s.additions} added, ${s.sold} sold)`} />
      <Row k="Book depreciation (Schedule II)" v={inr(s.book_depreciation)} /><Row k="Tax depreciation (blocks)" v={inr(s.tax_depreciation)} />
      <Row k={`Deferred tax ${d.charge >= 0 ? "charge" : "credit"}`} v={inr(Math.abs(d.charge))} />
      <Row k="Capital work in progress" v={s.cwip ? inr(s.cwip) : "none"} /></dl></CardBody></Card>
    {r.checks.length > 0 && <Card><CardHeader><CardTitle>Checks</CardTitle></CardHeader><CardBody><ul className="space-y-1.5 text-sm">{r.checks.map((c: any, i: number) =>
      <li key={i} className="flex gap-2"><Badge tone={DEP_SEV[c.severity]}>{c.severity}</Badge>{c.what}</li>)}</ul></CardBody></Card>}
    <Card><CardHeader><CardTitle>Income-tax: written-down value by block</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Block", "Rate", "Opening WDV", `Added (${r.half_days}+ days)`, `Added (under ${r.half_days})`, "Sales", "Depreciation", "Closing WDV"]}
        rows={[...r.blocks.map((b: any) => [<span key="b">{b.label}{b.stcg ? <Badge tone="danger"> STCG {inr(b.stcg)}</Badge> : null}{b.stcl ? <Badge tone="warning"> STCL {inr(b.stcl)}</Badge> : null}</span>,
          pct(b.rate), inr(b.opening), inr(b.additions_full), inr(b.additions_half), inr(b.sales), inr(b.depreciation), inr(b.closing)]),
          [<b key="t">Total</b>, "", ...["opening", "additions_full", "additions_half", "sales", "depreciation", "closing"].map((k) => <b key={k}>{inr(r.blocks.reduce((a: number, b: any) => a + b[k], 0))}</b>)]]} />
    </CardBody></Card>
    <Card><CardHeader><CardTitle>Opening tax WDV by block</CardTitle></CardHeader><CardBody>
      <p className="mb-3 text-sm text-muted">Use last year&apos;s closing WDV from the tax computation. Changing a figure works out the blocks and the deferred tax again.</p>
      <TaxOpening wid={wid} blocks={r.blocks} /></CardBody></Card>
    <Card><CardHeader><CardTitle>Books: Schedule II, straight line</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["Class", "Life (years)", "Opening WDV", "Additions", "Depreciation", "Disposals", "Closing WDV"]}
        rows={[...r.classes.map((c: any) => [c.class, c.life ?? "-", inr(c.opening), inr(c.additions), inr(c.depreciation), inr(c.disposals), inr(c.closing)]),
          [<b key="t">Total</b>, "", ...["opening", "additions", "depreciation", "disposals", "closing"].map((k) => <b key={k}>{inr(t[k])}</b>)]]} /></CardBody></Card>
    <Card><CardHeader><CardTitle>Deferred tax (AS 22)</CardTitle></CardHeader><CardBody className="p-0">
      <Table head={["", "Opening", "Closing"]} rows={[["Book WDV (depreciable assets)", inr(d.book_wdv_opening), inr(d.book_wdv_closing)],
        ["Tax WDV", inr(d.tax_wdv_opening), inr(d.tax_wdv_closing)], ["Timing difference", inr(d.difference_opening), inr(d.difference_closing)],
        [`Deferred tax ${d.position === "asset" ? "asset" : "liability"} at ${pct(d.tax_rate)}`, inr(d.dtl_opening), inr(d.dtl_closing)],
        [<b key="c">{d.charge >= 0 ? "Charge" : "Credit"} for the year</b>, "", <b key="v">{inr(Math.abs(d.charge))}</b>]]} />
      <p className="px-4 pb-3 text-xs text-muted">Land and assets paid in cash over ₹10,000 are left out: neither ever gets tax depreciation, so there&apos;s no timing difference.</p></CardBody></Card>
    <details className="rounded-xl border-2 border-line p-3"><summary className="cursor-pointer font-semibold">Asset by asset ({r.assets.length})</summary>
      <Table head={["Asset", "Class", "Cost", "Put to use", "Opening", "Depreciation", "Closing", "Tax"]} rows={r.assets.map((x: any) => [x.name, x.class + (x.assumed ? " (assumed)" : ""),
        inr(x.cost), x.in_use ?? x.acquired ?? "-", inr(x.book.opening), inr(x.book.depreciation), x.sold ? `sold ${x.sold}` : x.cwip ? "CWIP" : inr(x.book.closing),
        x.tax.cash_disallowed ? "cash: not allowed" : x.tax.half ? "half rate" : x.block ? "" : "no depreciation"])} /></details>
  </>);
}

export default async function WorkPage({ params }: { params: Promise<{ wid: string }> }) {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  const pages = (await getFeatures(active.id)).pages;
  if (!pages.includes("ca-clients") && !pages.includes("excel")) notFound();
  const { wid } = await params;
  let w: Work;
  try {
    w = await api<Work>(`/org/ca/work/${wid}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const client = w.client_id ? await api<{ client: { name: string } }>(`/org/ca/clients/${w.client_id}`, { orgId: active.id }).catch(() => null) : null;
  const r = w.result;
  return (
    <div className="space-y-5">
      <Link href={w.client_id ? `/ca-clients/${w.client_id}` : "/excel"} className="text-sm text-muted hover:text-ink">← {client?.client.name ?? "Excel desk"}</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="font-hand text-lg text-muted">{AGENT_LABEL[w.agent] ?? w.agent}</p><h1 className="font-display text-3xl font-bold tracking-tight">{w.title}</h1>
          <p className="text-sm text-muted">{new Date(w.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</p></div>
        <div className="flex items-center gap-3">
          {w.agent !== "ca_notice_handler" && <a href={`/api/ca/work/${w.id}/sheet.xlsx`} className="inline-flex h-10 items-center rounded-xl border-2 border-ink px-4 text-sm font-semibold hover:bg-lime-soft">Download Excel</a>}
          <DeleteWork wid={w.id} clientId={w.client_id ?? undefined} /></div>
      </header>
      {w.agent === "ca_gst_reconciliation" && <Gst r={r} />}
      {w.agent === "ca_itr_prep" && <Itr r={r} />}
      {w.agent === "ca_capital_gains" && <CapGains r={r} />}
      {w.agent === "ca_bank_classifier" && <Bank r={r} wid={w.id} />}
      {w.agent === "ca_notice_handler" && <Notice r={r} />}
      {w.agent === "ca_tds_returns" && <Tds r={r} />}
      {w.agent === "ca_tax_audit" && <Audit r={r} />}
      {w.agent === "excel_desk" && <Excel r={r} title={w.title} />}
      {w.agent === "excel_cleaner" && <Cleaner r={r} />}
      {w.agent === "ca_anomaly_finder" && <Anomalies r={r} />}
      {w.agent === "ca_upload_hub" && <Hub r={r} />}
      {w.agent === "ca_gstr1" && <Gstr1 r={r} />}
      {w.agent === "ca_financial_statements" && <Financials r={r} wid={w.id} />}
      {w.agent === "ca_depreciation" && <Depreciation r={r} wid={w.id} />}
    </div>
  );
}
