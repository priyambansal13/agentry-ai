import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AGENT_LABEL } from "@/components/ca-tools";
import { BankLineCategory, CopyText, DeleteWork } from "@/components/ca-tool-forms";
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
    </div>
  );
}
