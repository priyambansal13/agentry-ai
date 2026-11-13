"use client";

import { AlertTriangle, CheckCircle2, FileText, MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { type Any, Area, Bubble, Chips, Copyable, Field, fmtDate, inr, Panel, Presets, RunButton, Select, Severity, SheetEditor, Stat, TryShell, useRun, useSample } from "./kit";

/* ---------- ITR preparation: old vs new regime ---------- */

const ITR_FIELDS: [string, string][] = [
  ["salary_gross", "Gross salary"], ["exempt_allowances", "HRA / LTA exempt (old regime)"], ["interest_deposit", "FD / deposit interest"],
  ["interest_savings", "Savings interest"], ["self_occupied_interest", "Home loan interest (own house)"], ["d_80c", "80C (PF, PPF, ELSS, LIC…)"],
  ["d_80d", "80D health insurance"], ["d_80ccd1b", "80CCD(1B) own NPS"], ["ltcg_112a", "Long-term gains on shares / equity MF"], ["tds", "TDS already deducted"],
];

export function ItrBox() {
  const sample = useSample("itr");
  const [p, setP] = useState<Record<string, Any>>({});
  useEffect(() => { if (sample) setP(sample); }, [sample]);
  const r = useRun("itr", false);
  const x = r.result;
  return (
    <TryShell title="Old or new regime? Worked out in a second" live={false}
      intro="Change the figures (the sample is a salaried client with FD interest). It's the same computation the CA's portal runs for every client: slabs, rebate 87A with marginal relief, 112A exemption, surcharge and cess, for AY 2026-27."
      sell="In the portal this runs for every client from their Form 16 and AIS, picks the ITR form, and puts the working on the CA's desk to check and file.">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {ITR_FIELDS.map(([k, l]) => <Field key={k} id={`itr-${k}`} label={l} type="number" value={p[k] ?? ""} onChange={(v) => setP({ ...p, [k]: v === "" ? "" : Number(v) })} />)}
        <Select id="itr-age" label="Age" value={p.age ?? "below60"} onChange={(v) => setP({ ...p, age: v })} options={[["below60", "Below 60"], ["60to80", "60 to 80"], ["above80", "Above 80"]]} />
      </div>
      <div className="mt-5"><RunButton r={r} label="Compare the regimes" input={() => p} disabled={!sample} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="rounded-2xl border-2 border-ink bg-lime p-5 text-lime-ink">
            <p className="font-display text-2xl font-bold">{x.better === "new" ? "New" : "Old"} regime saves {inr(x.saving)}</p>
            <p className="mt-1">Return to file: <strong>{x.itr_form}</strong>. {x.new.payable || x.old.payable ? "" : ""}</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {(["old", "new"] as const).map((k) => {
              const c = x[k];
              return (
                <Panel key={k} title={`${k === "old" ? "Old" : "New"} regime${x.better === k ? " ✓" : ""}`} tone={x.better === k ? "good" : "card"}>
                  <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
                    <dt>Gross total income</dt><dd className="text-right tabular-nums">{inr(c.gross_total_income)}</dd>
                    <dt>Deductions</dt><dd className="text-right tabular-nums">−{inr(c.total_deductions)}</dd>
                    <dt className="font-semibold">Taxable income</dt><dd className="text-right font-semibold tabular-nums">{inr(c.total_income)}</dd>
                    <dt>Tax on slabs</dt><dd className="text-right tabular-nums">{inr(c.slab_tax)}</dd>
                    {c.special_rate_tax > 0 && <><dt>Tax on capital gains</dt><dd className="text-right tabular-nums">{inr(c.special_rate_tax)}</dd></>}
                    {c.rebate_87a > 0 && <><dt>Rebate 87A</dt><dd className="text-right tabular-nums">−{inr(c.rebate_87a)}</dd></>}
                    {c.surcharge > 0 && <><dt>Surcharge</dt><dd className="text-right tabular-nums">{inr(c.surcharge)}</dd></>}
                    <dt>Cess 4%</dt><dd className="text-right tabular-nums">{inr(c.cess)}</dd>
                    <dt className="border-t-2 border-ink pt-1 font-bold">Total tax</dt><dd className="border-t-2 border-ink pt-1 text-right font-bold tabular-nums">{inr(c.tax_liability)}</dd>
                    <dt>{c.refund ? "Refund due" : "Still to pay"}</dt><dd className={`text-right font-semibold tabular-nums ${c.refund ? "text-success" : "text-danger"}`}>{inr(c.refund || c.payable)}</dd>
                  </dl>
                  {c.notes?.map((n: string) => <p key={n} className="mt-2 text-xs text-muted">{n}</p>)}
                </Panel>);
            })}
          </div>
        </div>)}
    </TryShell>
  );
}

/* ---------- table-driven checks: the shared shape ---------- */

function useRows(kind: string) {
  const s = useSample(kind);
  const [rows, setRows] = useState<string[][]>([]);
  useEffect(() => { if (s?.rows) setRows(s.rows); }, [s]);
  return { s, rows, setRows };
}

export function CapitalGainsBox() {
  const { s, rows, setRows } = useRows("capital-gains");
  const r = useRun("capital-gains", false);
  const x = r.result;
  return (
    <TryShell title="Broker P&L in, Schedule CG out"
      intro="A Zerodha-style tax P&L (sample below: edit dates or prices, add a sale). Each sale is classified short or long term, grandfathered to 31 Jan 2018 where it applies, and split at 23 July 2024 for the new rates."
      sell="In the portal clients send Zerodha, Groww, Upstox or CAMS statements on WhatsApp; the figures flow straight into their ITR working.">
      <SheetEditor rows={rows} onChange={setRows} caption="Broker statement" />
      <div className="mt-4"><RunButton r={r} label="Work out the gains" input={() => ({ rows })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Short-term, 111A" value={inr(x.summary.stcg_111a)} note="20% after 23 Jul 2024" />
            <Stat label="Long-term, 112A" value={inr(x.summary.ltcg_112a)} note="12.5% above ₹1.25 lakh" />
            <Stat label="Other short-term" value={inr(x.summary.stcg_other)} note="at slab rates" />
            <Stat label="Sales checked" value={`${x.summary.sales}`} note={`${x.summary.flagged} need a look`} />
          </div>
          <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card">
            <table className="w-full min-w-[640px] text-sm"><thead><tr className="bg-paper text-left text-xs">{["Scrip", "Held", "Term", "Section", "Cost used", "Gain", "Note"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
              <tbody>{x.rows.map((t: Any) => (
                <tr key={t.row} className="border-t border-line"><td className="px-3 py-2 font-medium">{t.name}</td><td className="px-3 py-2">{t.held_months ?? "–"} mo</td>
                  <td className="px-3 py-2">{t.term ?? "–"}</td><td className="px-3 py-2">{t.section ?? "–"}</td><td className="px-3 py-2 tabular-nums">{inr(t.cost)}</td>
                  <td className={`px-3 py-2 tabular-nums ${t.gain < 0 ? "text-danger" : ""}`}>{inr(t.gain)}</td><td className="px-3 py-2 text-xs text-ink-soft">{t.flags?.join("; ")}</td></tr>))}</tbody></table>
          </div>
          {x.summary.notes?.map((n: string) => <p key={n} className="text-sm text-ink-soft">• {n}</p>)}
        </div>)}
    </TryShell>
  );
}

export function TdsBox() {
  const { s, rows, setRows } = useRows("tds");
  const r = useRun("tds", false);
  const x = r.result;
  return (
    <TryShell title="Catch TDS mistakes before the return goes in"
      intro="A quarter's payment register (sample: try a wrong rate, a missing PAN or a late deposit date). Rates, thresholds, PAN, late deduction (1%) and late deposit (1.5%) interest are checked, and the 24Q / 26Q totals are built."
      sell="In the portal every client's register is checked each quarter; the problems land on the CA's board with the interest worked out.">
      <SheetEditor rows={rows} onChange={setRows} caption="TDS payment register" />
      <div className="mt-4"><RunButton r={r} label="Check the register" input={() => ({ rows })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Problems found" value={x.issues.length} /><Stat label="Interest payable" value={inr(x.interest)} note="late deduction and deposit" />
            <Stat label="Deductees" value={new Set(x.rows.map((t: Any) => t.pan || t.name)).size} />
          </div>
          {x.issues.length > 0 && <Panel title="Fix before filing" tone="warn"><ul className="space-y-3 text-sm">{x.issues.map((i: Any) => (
            <li key={i.row}><p className="font-semibold">{i.name} · {i.section}</p><ul className="ml-4 list-disc text-ink-soft">{i.problems.map((p: string) => <li key={p}>{p}</li>)}</ul></li>))}</ul></Panel>}
          <Panel title="Return summary"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted">{["Form", "Quarter", "Section", "Paid", "TDS", "Interest"].map((h) => <th key={h} className="py-1">{h}</th>)}</tr></thead>
            <tbody>{x.summary.map((q: Any, i: number) => <tr key={i} className="border-t border-line"><td className="py-1">{q.form}</td><td>{q.quarter}</td><td>{q.section} <span className="text-xs text-muted">{q.label}</span></td><td className="tabular-nums">{inr(q.amount)}</td><td className="tabular-nums">{inr(q.tds)}</td><td className="tabular-nums">{inr(q.interest)}</td></tr>)}</tbody></table></Panel>
        </div>)}
    </TryShell>
  );
}

export function Audit3cdBox() {
  const { s, rows, setRows } = useRows("audit-3cd");
  const r = useRun("audit-3cd", false);
  const x = r.result;
  return (
    <TryShell title="Clause 3CD tests, straight from the ledger"
      intro="A ledger extract for FY 2025-26 (sample: edit amounts, payment modes or dates). Cash over ₹10,000 a day (40A(3)), MSME dues past 45 days (43B(h)), statutory dues, employees' PF / ESI, TDS not deducted and cash loans are tested."
      sell="In the portal the whole ledger is tested and every exception is listed with its rows, ready for the auditor's working papers.">
      <SheetEditor rows={rows} onChange={setRows} caption="Ledger" />
      <div className="mt-4"><RunButton r={r} label="Run the tests" input={() => ({ rows, fy_start: s?.fy_start ?? 2025 })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="Entries tested" value={x.entries} /><Stat label="Clauses with exceptions" value={x.clauses.length} /><Stat label="Possible disallowance" value={inr(x.disallowance)} /></div>
          {x.clauses.map((c: Any) => (
            <Panel key={c.clause} title={c.label} tone="warn"><ul className="space-y-2 text-sm">{c.items.map((i: Any, n: number) => (
              <li key={n} className="flex flex-wrap justify-between gap-2"><span><strong>{i.party}</strong> · {fmtDate(i.date)}: {i.why}</span><span className="tabular-nums">{i.disallow ? `disallow ${inr(i.disallow)}` : "penalty risk"}</span></li>))}</ul></Panel>))}
          {!x.clauses.length && <Panel tone="good"><p className="flex items-center gap-2"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" /> No exceptions in these entries.</p></Panel>}
        </div>)}
    </TryShell>
  );
}

const GST_LABEL: Record<string, string> = { matched: "Matched", amount_differs: "Amount differs", missing_in_2b: "Not in GSTR-2B", missing_in_books: "In 2B, not in books", gstin_differs: "GSTIN differs" };

export function GstBox() {
  const { s, rows, setRows } = useRows("gst");
  const r = useRun("gst", false);
  const x = r.result;
  return (
    <TryShell title="Purchase register vs GSTR-2B, in seconds"
      intro={`Your purchase register for October (edit it) is matched invoice by invoice against the GSTR-2B downloaded from the portal (${s?.gstr2b?.length ?? "…"} invoices). Missing invoices, amount differences and wrong GSTINs come out, with a message drafted for each supplier.`}
      sell="In the portal clients' registers and 2B files are matched every month, and the supplier messages go out on WhatsApp or email after the CA approves them.">
      <SheetEditor rows={rows} onChange={setRows} caption="Purchase register" />
      <div className="mt-4"><RunButton r={r} label="Reconcile" input={() => ({ rows })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="ITC at risk" value={inr(x.itc_at_risk)} note="not claimable until fixed" /><Stat label="ITC in your books" value={inr(x.itc_in_books)} /><Stat label="ITC in GSTR-2B" value={inr(x.itc_in_2b)} /></div>
          <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card"><table className="w-full min-w-[600px] text-sm"><thead><tr className="bg-paper text-left text-xs">{["Status", "Supplier", "Invoice", "Tax in books", "Tax in 2B"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{x.rows.map((row: Any, i: number) => { const b = row.books ?? row.gstr2b; return (
              <tr key={i} className="border-t border-line"><td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${row.status === "matched" ? "bg-lime-soft" : "bg-danger text-paper"}`}>{GST_LABEL[row.status]}</span></td>
                <td className="px-3 py-2">{b.name}</td><td className="px-3 py-2">{b.invoice}</td><td className="px-3 py-2 tabular-nums">{row.books ? inr(row.books.tax) : "–"}</td><td className="px-3 py-2 tabular-nums">{row.gstr2b ? inr(row.gstr2b.tax) : "–"}</td></tr>); })}</tbody></table></div>
          {x.messages.map((m: Any) => (
            <Panel key={m.gstin} title={`Message to ${m.supplier}`} action={<Copyable text={m.message} />}><p className="text-sm whitespace-pre-line">{m.message}</p></Panel>))}
        </div>)}
    </TryShell>
  );
}

export function BankBox() {
  const { s, rows, setRows } = useRows("bank");
  const r = useRun("bank", true);
  const x = r.result;
  return (
    <TryShell live title="A bank statement, tagged and summed"
      intro="An HDFC-style statement (edit narrations or amounts). Rules tag what they can (GST paid, EMI, rent, salaries…) and the AI tags the rest. Receipts are split digital vs cash, and the 44AD / 44ADA presumptive income is worked out."
      sell="In the portal it learns from every correction you make (“Patel Enterprises is a customer”), so next month's statement needs almost nothing from you.">
      <SheetEditor rows={rows} onChange={setRows} caption="Bank statement" />
      <div className="mt-4"><RunButton r={r} label="Tag the statement" input={() => ({ rows })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Turnover (receipts)" value={inr(x.totals.receipts)} note={`${inr(x.totals.digital_receipts)} digital`} />
            <Stat label="44AD income" value={inr(x.totals.presumptive_44ad)} note="6% digital + 8% cash" />
            <Stat label="44ADA income" value={inr(x.totals.presumptive_44ada)} note="50% of receipts" />
            <Stat label="Lines" value={x.totals.lines} note={`${x.totals.to_glance} tagged by the AI: worth a glance`} />
          </div>
          <div className="max-h-96 overflow-auto rounded-2xl border-2 border-ink bg-card"><table className="w-full min-w-[620px] text-sm"><thead className="sticky top-0 bg-paper"><tr className="text-left text-xs">{["Date", "Narration", "In", "Out", "Tagged as"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{x.lines.map((l: Any) => (<tr key={l.row} className="border-t border-line"><td className="px-3 py-1.5 whitespace-nowrap">{fmtDate(l.date)}</td><td className="max-w-[18rem] truncate px-3 py-1.5" title={l.narration}>{l.narration}</td>
              <td className="px-3 py-1.5 tabular-nums">{l.in ? inr(l.in) : ""}</td><td className="px-3 py-1.5 tabular-nums">{l.out ? inr(l.out) : ""}</td>
              <td className="px-3 py-1.5"><span className="font-medium">{l.category}</span> <span className="text-xs text-muted">{l.by === "ai" ? "AI" : l.by === "default" ? "guess" : "rule"}</span></td></tr>))}</tbody></table></div>
          {x.totals.flags.map((f: string) => <p key={f} className="flex gap-2 text-sm"><AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0 text-danger" />{f}</p>)}
        </div>)}
    </TryShell>
  );
}

/* ---------- compliance calendar ---------- */

export function CalendarBox() {
  const [kind, setKind] = useState("company");
  const [prof, setProf] = useState<Record<string, boolean>>({ gst: true, tds: true, pf_esi: true, audit: true });
  const [name, setName] = useState("Ramesh Gupta");
  const [gstin, setGstin] = useState("27AAPFM4321Q1Z5");
  const r = useRun("calendar", false);
  const x = r.result;
  return (
    <TryShell title="Every due date for a client, from today, with its source"
      intro="Pick what kind of client and what applies. Every GST, TDS, TCS, PF / ESI, advance tax, ITR, audit and ROC date for the next four months comes out, with the WhatsApp reminder the client would get. Each date shows where it comes from: the standard date in the law, or the government's extension."
      sell="In the portal official sources are checked every morning. When CBDT, CBIC or MCA extend a date, it's verified on the official page and every client's card, reminder and calendar moves with it.">
      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <div className="space-y-3"><Select id="cal-kind" label="Client type" value={kind} onChange={setKind} options={[["individual", "Individual"], ["firm", "Partnership firm"], ["llp", "LLP"], ["company", "Private limited company"]]} />
          <Field id="cal-name" label="Client name" value={name} onChange={setName} />
          <Field id="cal-gstin" label="GSTIN (sets the state)" value={gstin} onChange={(v) => setGstin(v.toUpperCase())} /></div>
        <Chips label="What applies" value={prof} onChange={setProf} options={[["gst", "GST (monthly)"], ["gst_qrmp", "GST quarterly (QRMP)"], ["gst_composition", "GST composition"], ["tds", "TDS"], ["tcs", "TCS"], ["pf_esi", "PF / ESI"], ["advance_tax", "Advance tax"], ["business", "Business income"], ["audit", "Tax audit"], ["transfer_pricing", "Transfer pricing"]]} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Show the dates" input={() => ({ client_kind: kind, profile: prof, name, gstin })} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel title={`${x.deadlines.length} due dates in the next 4 months`}><ol className="max-h-[28rem] space-y-1 overflow-auto text-sm">{x.deadlines.map((d: Any, i: number) => (
            <li key={i} className="border-b border-line py-1.5 last:border-0">
              <div className="flex items-center justify-between gap-3"><span>{d.title}</span>
                <span className={`shrink-0 tabular-nums ${d.days_left <= 7 ? "font-bold text-danger" : "text-ink-soft"}`}>{fmtDate(d.due_on)} · {d.days_left}d</span></div>
              <p className="text-xs text-muted">{d.source.type === "extension"
                ? <><span className="font-semibold text-success">Extended</span> from {fmtDate(d.source.was)}: {d.source.url ? <a href={d.source.url} target="_blank" rel="noreferrer" className="underline">{d.source.label}</a> : d.source.label}</>
                : d.source.label}{d.note ? ` · ${d.note}` : ""}</p>
            </li>))}</ol></Panel>
          {x.deadlines[0] && <Panel title="What the client gets on WhatsApp"><Bubble meta="7 days before">{x.deadlines[0].reminder}</Bubble></Panel>}
        </div>)}
    </TryShell>
  );
}

/* ---------- document chaser ---------- */

export function ChaserBox() {
  const [prof, setProf] = useState<Record<string, boolean>>({ salaried: true, capital_gains: true, deductions: true, rent_paid: true });
  const [received, setReceived] = useState<string[]>([]);
  const [name, setName] = useState("Ramesh Gupta");
  const r = useRun("chaser", false);
  const x = r.result;
  useEffect(() => { void r.run({ kind: "itr", profile: prof, received, name }); }, [prof, received]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <TryShell title="The documents chase themselves"
      intro="Describe the client: the ITR checklist builds itself. Tick off what's arrived and watch the next reminder shrink to only what's still missing."
      sell="In the portal clients reply on WhatsApp with photos and PDFs; each one is recognised, matched to the checklist item and filed. After 5 reminders the client goes on your call list.">
      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <Field id="ch-name" label="Client name" value={name} onChange={setName} />
        <Chips label="This client has" value={prof} onChange={setProf} options={[["salaried", "Salary"], ["rent_paid", "Pays rent (HRA)"], ["house_property", "Own house / rent income"], ["capital_gains", "Shares / MF sold"], ["deductions", "80C / 80D"], ["business", "Business"], ["foreign", "Foreign income"]]} />
      </div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <Panel title={`Checklist: ${x.title}`}><ul className="space-y-2 text-sm">{x.checklist.map((i: Any) => (
            <li key={i.key}><label className="flex cursor-pointer items-start gap-2"><input type="checkbox" className="mt-1 h-4 w-4 accent-current" checked={i.status === "received"}
              onChange={(e) => setReceived(e.target.checked ? [...received, i.key] : received.filter((k) => k !== i.key))} />
              <span className={i.status === "received" ? "text-muted line-through" : ""}>{i.label}</span></label></li>))}</ul></Panel>
          <Panel title="Reminders on WhatsApp">{x.reminders.length ? <div className="space-y-3">{x.reminders.slice(0, 2).map((m: Any) => <Bubble key={m.day} meta={m.day === 0 ? "today" : `day ${m.day}`}>{m.text}</Bubble>)}</div>
            : <p className="flex items-center gap-2 text-sm"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" /> Everything's in: the filing moves to "ready to prepare".</p>}
            <p className="mt-3 text-xs text-muted">{x.after}</p></Panel>
        </div>)}
      {r.error && <p role="alert" className="mt-3 text-sm text-danger">{r.error}</p>}
    </TryShell>
  );
}

/* ---------- tax documents reader ---------- */

export function TaxDocsBox() {
  const s = useSample("tax-docs");
  const [f16, setF16] = useState<number | "">("");
  const [ais, setAis] = useState<number | "">("");
  useEffect(() => { if (s) { setF16(s.form16_tds); setAis(s.ais_interest); } }, [s]);
  const r = useRun("tax-docs", false);
  const x = r.result;
  return (
    <TryShell title="Form 16 vs AIS: every mismatch, with the line it came from"
      intro="A sample client's Form 16 and AIS (both shown below). Change the TDS in Form 16 or the deposit interest in AIS and see what the reader flags. Every figure is traced back to the exact line in the document."
      sell="In the portal clients' PDFs are read as they arrive (Form 16, 16A, AIS, TIS, 26AS), and the mismatches go to the CA before the return is prepared.">
      <div className="grid gap-4 md:grid-cols-2">
        <Field id="td-f16" label="TDS shown in Form 16 (₹)" type="number" value={f16} onChange={(v) => setF16(v === "" ? "" : Number(v))} hint="AIS says ₹2,41,500" />
        <Field id="td-ais" label="Deposit interest in AIS (₹)" type="number" value={ais} onChange={(v) => setAis(v === "" ? "" : Number(v))} />
      </div>
      {s && <details className="mt-3 text-sm"><summary className="cursor-pointer font-semibold">See the two documents</summary>
        <div className="mt-2 grid gap-3 md:grid-cols-2"><pre className="max-h-64 overflow-auto rounded-xl border-2 border-line bg-card p-3 text-xs whitespace-pre-wrap">{s.form16}</pre><pre className="max-h-64 overflow-auto rounded-xl border-2 border-line bg-card p-3 text-xs whitespace-pre-wrap">{s.ais}</pre></div></details>}
      <div className="mt-4"><RunButton r={r} label="Compare the documents" input={() => ({ form16_tds: f16 === "" ? null : f16, ais_interest: ais === "" ? null : ais })} disabled={!s} /></div>
      {x && <div className="mt-6 space-y-3">{x.points.map((p: Any, i: number) => (
        <Panel key={i} tone={p.severity === "high" ? "warn" : "card"}><p className="text-sm"><Severity level={p.severity} /> <span className="ml-1">{p.message}</span></p>
          <ul className="mt-2 space-y-1">{p.sources.map((src: Any, j: number) => <li key={j} className="text-xs text-ink-soft"><FileText aria-hidden="true" className="mr-1 inline h-3.5 w-3.5" />{src.file}: “{src.quote}”</li>)}</ul></Panel>))}</div>}
    </TryShell>
  );
}

/* ---------- notice handler (AI) ---------- */

export function NoticeBox() {
  const s = useSample("notice");
  const [t, setT] = useState("");
  useEffect(() => { if (s) setT(s.text); }, [s]);
  const r = useRun("notice", true);
  const x = r.result;
  return (
    <TryShell live title="An income-tax notice, explained and answered"
      intro="A sample 143(1)(a) intimation is filled in: or paste the text of your own (remove the PAN and name first). The deadline, demand and DIN are read and then checked against the notice's own text; a reply is drafted for the CA."
      sell="In the portal the notice becomes a card on the board, due 5 days before the deadline, with the documents to collect from the client already on its checklist.">
      <Area id="nt-text" label="The notice's text" value={t} onChange={setT} rows={9} />
      <div className="mt-4"><RunButton r={r} label="Read the notice" input={() => ({ text: t })} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="Section" value={x.section ?? "–"} note={x.assessment_year ? `AY ${x.assessment_year}` : undefined} /><Stat label="Reply by" value={fmtDate(x.respond_by)} /><Stat label="Demand" value={inr(x.demand)} /></div>
          <Panel title="In plain words"><p className="text-sm">{x.summary}</p><p className="mt-2 text-sm text-ink-soft">{x.why}</p></Panel>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="What to do"><ol className="ml-5 list-decimal space-y-1 text-sm">{x.what_to_do?.map((w: string) => <li key={w}>{w}</li>)}</ol></Panel>
            <Panel title="Ask the client for"><ul className="ml-5 list-disc space-y-1 text-sm">{x.documents_needed?.map((w: string) => <li key={w}>{w}</li>)}</ul></Panel>
          </div>
          {x.draft_reply && <Panel title="Draft reply" action={<Copyable text={x.draft_reply} />}><p className="text-sm whitespace-pre-line">{x.draft_reply}</p></Panel>}
          {x.flags?.map((f: string) => <p key={f} className="text-sm text-danger">⚠ {f}</p>)}
        </div>)}
    </TryShell>
  );
}

/* ---------- Excel desk (AI turns the question into a query; code computes the answer) ---------- */

export function ExcelBox() {
  const s = useSample("excel");
  const [rows, setRows] = useState<string[][]>([]);
  const [q, setQ] = useState("");
  useEffect(() => { if (s) { setRows(s.rows); setQ(s.questions[0]); } }, [s]);
  const r = useRun("excel", true);
  const x = r.result;
  return (
    <TryShell live title="Ask your spreadsheet a question"
      intro="A TDS register (edit it if you like). Ask in plain words. The AI only decides which columns to filter, group and add up; the numbers are computed by code, so they're exact."
      sell="In the portal you also convert PDFs (bank statements, ledgers, invoices) into Excel in your firm's layout, and reconcile books against bank or debtors in one click.">
      <SheetEditor rows={rows} onChange={setRows} caption="Sheet" />
      <div className="mt-4 space-y-3">
        {s && <Presets items={s.questions.map((v: string) => ({ label: v, value: v }))} onPick={setQ} label="Questions" />}
        <Field id="xl-q" label="Your question" value={q} onChange={setQ} />
        <RunButton r={r} label="Ask" input={() => ({ question: q, rows })} disabled={!s} />
      </div>
      {x && (
        <div className="mt-6 grid gap-4 md:grid-cols-[1fr_16rem]">
          <Panel title="Answer">{"value" in x.answer ? <p className="font-display text-3xl font-bold">{x.spec.agg === "count" ? x.answer.value : inr(x.answer.value, 2)}</p>
            : x.answer.groups ? <table className="w-full text-sm"><tbody>{x.answer.groups.map(([g, v]: [string, number]) => <tr key={g} className="border-b border-line last:border-0"><td className="py-1.5">{g || "(blank)"}</td><td className="py-1.5 text-right font-semibold tabular-nums">{x.spec.agg === "count" ? v : inr(v, 2)}</td></tr>)}</tbody></table>
            : <table className="w-full text-xs"><tbody>{x.answer.rows.slice(0, 12).map((row: string[], i: number) => <tr key={i} className={i === 0 ? "font-semibold" : "border-t border-line"}>{row.map((c, j) => <td key={j} className="px-1 py-1">{c}</td>)}</tr>)}</tbody></table>}
            <p className="mt-2 text-xs text-muted">from {x.answer.count} rows</p></Panel>
          <Panel title="How it was worked out"><dl className="space-y-1 text-xs"><dt className="font-semibold">Calculation</dt><dd>{x.spec.agg} {x.spec.measure ? `of "${x.spec.measure}"` : ""}</dd>
            {x.spec.group_by && <><dt className="font-semibold">Grouped by</dt><dd>{x.spec.group_by}</dd></>}
            {x.spec.filter?.length > 0 && <><dt className="font-semibold">Only rows where</dt><dd>{x.spec.filter.map((f: Any) => `${f.column} ${f.op} ${f.value}`).join(", ")}</dd></>}</dl></Panel>
        </div>)}
    </TryShell>
  );
}

/* ---------- GSTR-1 preparation (fixed rules, no AI) ---------- */

const G1: [string, string, (x: Any[]) => string[]][] = [
  ["b2b", "B2B", (x) => [x[2], x[1], x[5], `${x[10]}%`, inr(x[11])]], ["b2cl", "B2C large", (x) => [x[0], "", x[3], `${x[5]}%`, inr(x[6])]],
  ["b2cs", "B2C small", (x) => ["", "", x[1], `${x[3]}%`, inr(x[4])]], ["exp", "Exports", (x) => [x[1], x[0], x[4] || "", `${x[7]}%`, inr(x[8])]],
  ["cdnr", "Notes (registered)", (x) => [x[2], x[1], x[5], `${x[10]}%`, inr(x[11])]], ["cdnur", "Notes (unregistered)", (x) => [x[1], x[0], x[4], `${x[7]}%`, inr(x[8])]],
];

export function Gstr1Box() {
  const s = useSample("gstr1");
  const [rows, setRows] = useState<string[][]>([]);
  useEffect(() => { if (s) setRows(s.rows); }, [s]);
  const r = useRun("gstr1", false);
  const x = r.result;
  return (
    <TryShell title="October's sales register, ready for GSTR-1"
      intro="A Maharashtra trader's 22 entries for the month: local and other-state customers, walk-ins, an export under LUT and one with IGST, credit and debit notes. Each line is placed in its GSTR-1 table and checked first; edit any cell (try changing a place of supply) and prepare again."
      sell="In the portal you upload the client's register from their page (or it arrives through the upload hub), and download every table as the GST offline tool's Excel workbook, with the HSN summary and documents issued filled in.">
      <SheetEditor rows={rows} onChange={setRows} caption="Sales register (Oct 2026)" maxRows={30} />
      <div className="mt-4"><RunButton r={r} label="Prepare GSTR-1" input={() => ({ rows, gstin: s?.gstin, period: s?.period })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="Taxable value" value={inr(x.totals.all.taxable)} note={`${x.totals.all.count} documents, ${x.period}`} />
            <Stat label="Tax" value={inr(x.totals.all.igst + x.totals.all.cgst + x.totals.all.sgst)} note={`IGST ${inr(x.totals.all.igst)} · CGST ${inr(x.totals.all.cgst)} · SGST ${inr(x.totals.all.sgst)}`} />
            <Stat label="To fix first" value={x.summary.high} note={`${x.summary.medium + x.summary.low} more to check`} /></div>
          {x.issues.length > 0 && <Panel title="Checks before filing" tone="warn"><ul className="space-y-1.5 text-sm">{x.issues.map((i: Any, n: number) => <li key={n} className="flex gap-2">
            <Severity level={i.severity} /><span>{i.invoice && <span className="font-semibold">{i.invoice}: </span>}{i.problem}{i.value && !i.invoice ? ` (${i.value})` : ""}</span></li>)}</ul></Panel>}
          <Panel title="Where each line went"><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted"><th className="py-1 pr-2">Table</th><th className="pr-2">Invoice / note</th><th className="pr-2">Customer / type</th><th className="pr-2">Place of supply</th><th className="pr-2">Rate</th><th className="text-right">Taxable</th></tr></thead>
            <tbody>{G1.flatMap(([k, label, f]) => (x.tables[k] ?? []).map((row: Any[], i: number) => { const c = f(row); return (
              <tr key={`${k}${i}`} className="border-t border-line"><td className="py-1.5 pr-2 font-semibold">{label}</td>{c.slice(0, 4).map((v, j) => <td key={j} className="pr-2">{v}</td>)}<td className="text-right tabular-nums">{c[4]}</td></tr>); }))}</tbody></table></div></Panel>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="HSN summary (B2B / B2C)"><ul className="space-y-1 text-sm">{[...x.tables.hsn_b2b.map((h: Any[]) => ["B2B", h]), ...x.tables.hsn_b2c.map((h: Any[]) => ["B2C", h])].map(([p, h]: Any, i: number) =>
              <li key={i} className="flex justify-between gap-2"><span><span className="text-muted">{p}</span> {h[0] || "(none)"} {h[1]} · {h[3]} {h[2]} · {h[5]}%</span><span className="tabular-nums">{inr(h[6])}</span></li>)}</ul></Panel>
            <Panel title="Documents issued (Table 13)"><ul className="space-y-1 text-sm">{x.tables.docs.map((d: Any[]) => <li key={d[0]}><span className="font-semibold">{d[0]}</span>: {d[1]} to {d[2]}, {d[3]} issued{d[4] ? `, ${d[4]} cancelled` : ""}</li>)}</ul></Panel>
          </div>
        </div>)}
    </TryShell>
  );
}

/* ---------- upload hub (recognition preview: nothing stored, no AI) ---------- */

export function HubBox() {
  const s = useSample("upload-hub");
  const r = useRun("upload-hub", false);
  const x = r.result;
  return (
    <TryShell title="A client's zip, sorted in seconds"
      intro="Mehta Traders sends one zip at month end: a bank statement, a broker P&L, the purchase register, the GSTR-2B, a TDS register, the day book, Form 16, the AIS and an income-tax notice, with names like “Purchases Oct.csv”. See what each file is taken as and which agent picks it up."
      sell="In the portal (and from the client's own portal link) every file is also filed on the client, ticked off their checklist, and the agent actually runs: the GST reconciliation, the bank classification, the anomaly scan, the notice reply are waiting when you open the client.">
      {s && <Panel title="documents-from-client.zip"><ul className="grid gap-1 text-sm sm:grid-cols-2">{s.files.map((f: string) => <li key={f} className="flex items-center gap-2"><FileText aria-hidden="true" className="h-4 w-4 text-muted" />{f}</li>)}</ul></Panel>}
      <div className="mt-4"><RunButton r={r} label="Sort the zip" input={() => ({})} disabled={!s} /></div>
      {x && (
        <div className="mt-6 overflow-x-auto rounded-2xl border-2 border-ink bg-card">
          <table className="w-full text-sm"><thead><tr className="text-left"><th className="p-3">File</th><th className="p-3">Taken as</th><th className="p-3">Picked up by</th></tr></thead>
            <tbody>{x.files.map((f: Any) => <tr key={f.filename} className="border-t border-line"><td className="p-3 font-medium">{f.filename}</td><td className="p-3">{f.recognised ?? "–"}</td>
              <td className="p-3">{f.agent_label ? <span className="inline-flex items-center gap-1.5"><CheckCircle2 aria-hidden="true" className="h-4 w-4 text-success" />{f.agent_label}</span> : <span className="text-muted">{f.next ?? "filed for the team"}</span>}</td></tr>)}</tbody></table>
          <p className="border-t border-line p-3 text-xs text-muted">The GSTR-2B and the purchase register arrived together, so they go to GST reconciliation as a pair; the day book goes to the anomaly finder.</p>
        </div>)}
    </TryShell>
  );
}

/* ---------- anomaly finder (fixed rules, no AI) ---------- */

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const cells: string[] = [];
    let cur = "", q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; }
      else if ((ch === "," || ch === "\t") && !q) { cells.push(cur); cur = ""; }
      else cur += ch;
    }
    rows.push([...cells, cur]);
  }
  return rows;
}

export function AnomalyBox() {
  const s = useSample("anomalies");
  const [own, setOwn] = useState("");
  const r = useRun("anomalies", false);
  const x = r.result;
  const ownRows = own.trim() ? parseCsv(own) : null;
  return (
    <TryShell title="A purchase day book, checked like a reviewer would"
      intro={`A sample day book of ${s?.rows ?? 167} entries for a Maharashtra trader, with the slips real books have hidden in it. Every check runs in seconds, most serious first, each with its rows and why it matters. Or paste up to 60 rows of your own.`}
      sell="In the portal you run it on a client's full ledger or register (up to 20,000 rows) from their page: the client's own GSTIN decides same-state vs other-state, the file stays on the client, and the findings download as Excel for the review file.">
      {s && <Panel title={`The sample (first ${s.preview.length - 3} of ${s.rows} entries)`}><div className="overflow-x-auto"><table className="w-full text-xs"><tbody>
        {s.preview.map((row: string[], i: number) => <tr key={i} className={i === 2 ? "font-semibold" : "border-t border-line"}>{row.map((c, j) => <td key={j} className="whitespace-nowrap px-1.5 py-1">{c}</td>)}</tr>)}</tbody></table></div></Panel>}
      <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold">Or paste your own (CSV, header first, up to 60 rows)</summary>
        <div className="mt-2"><Area id="an-own" label="Rows copied from Excel or a CSV" value={own} onChange={setOwn} rows={6} placeholder="Date,Voucher No,Party,GSTIN,Taxable Value,IGST,CGST,SGST,Amount,Mode" /></div></details>
      <div className="mt-4"><RunButton r={r} label={ownRows ? "Check my rows" : "Check the sample"} input={() => (ownRows ? { rows: ownRows } : { use_sample: true })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="Rows checked" value={x.summary.rows} note={x.fy_start ? `FY ${x.fy_start}-${String(x.fy_start + 1).slice(2)}` : undefined} />
            <Stat label="To fix" value={x.summary.high} note="rows with a serious finding" /><Stat label="To look at" value={x.summary.medium + x.summary.low} /></div>
          {x.findings.length === 0 && <Panel title="Nothing found"><p className="text-sm">No check found anything in these rows.</p></Panel>}
          {x.findings.map((f: Any) => (
            <Panel key={f.key} tone={f.severity === "high" ? "warn" : "card"} title={<span className="flex items-center gap-2"><Severity level={f.severity} /> {f.title} ({f.count})</span>}>
              <p className="text-sm text-ink-soft">{f.why}</p>
              <ul className="mt-2 space-y-1 text-sm">{f.rows.slice(0, 6).map((row: Any, i: number) => <li key={i} className="flex flex-wrap gap-x-2">
                {row.row && <span className="text-muted">row {row.row}</span>}{row.date && <span>{fmtDate(row.date)}</span>}{row.voucher && <span>{row.voucher}</span>}
                {row.party && <span className="font-semibold">{row.party}</span>}{typeof row.amount === "number" && <span className="tabular-nums">{inr(row.amount)}</span>}<span className="text-muted">· {row.note}</span></li>)}
                {f.count > 6 && <li className="text-xs text-muted">and {f.count - 6} more</li>}</ul>
            </Panel>))}
          {x.benford && <Panel title={`Benford first-digit test: ${x.benford.verdict}`}>
            <div className="flex items-end gap-1.5" role="img" aria-label="First-digit shares, expected vs this sheet">{x.benford.digits.map((d: Any) => (
              <div key={d.digit} className="flex flex-1 flex-col items-center gap-1 text-[11px]">
                <div className="flex h-24 w-full items-end justify-center gap-0.5"><div className="w-1/3 rounded-t bg-line" style={{ height: `${d.expected * 3}%` }} title={`expected ${d.expected}%`} />
                  <div className="w-1/3 rounded-t bg-ink" style={{ height: `${d.actual * 3}%` }} title={`actual ${d.actual}%`} /></div>{d.digit}</div>))}</div>
            <p className="mt-2 text-xs text-muted">Grey: expected in natural amounts · black: this sheet ({x.benford.n} amounts, chi-square {x.benford.chi2}). Not proof of anything; a sign of how amounts were made.</p></Panel>}
          {x.skipped?.map((m: string) => <p key={m} className="text-xs text-muted">Not checked: {m}</p>)}
        </div>)}
    </TryShell>
  );
}

/* ---------- Excel cleaner (fixed rules, no AI) ---------- */

export function CleanerBox() {
  const s = useSample("excel-clean");
  const [rows, setRows] = useState<string[][]>([]);
  const [one, setOne] = useState(false);
  useEffect(() => { if (s) setRows(s.rows); }, [s]);
  const r = useRun("excel-clean", false);
  const x = r.result;
  return (
    <TryShell title="A messy sales register, cleaned in one click"
      intro="The kind of sheet clients send: the firm's name and period on top, a page-break header in the middle, a Total row, amounts as “1,18,000.00 Dr” and “(2,000)”, dates written four ways, a lowercase GSTIN, one wrong GSTIN, a duplicate row and the same party spelt twice. Edit anything, then clean it."
      sell="In the portal you upload the client's own .xlsx or .csv (up to 20,000 rows) and download the clean workbook: the clean sheet, every change made, what to check and the similar names, ready for Tally import or the next agent.">
      <SheetEditor rows={rows} onChange={setRows} caption="Sheet as received" maxRows={30} />
      <label className="mt-4 flex items-center gap-2 text-sm"><input type="checkbox" checked={one} onChange={(e) => setOne(e.target.checked)} /> Use one spelling for similar party names</label>
      <div className="mt-4"><RunButton r={r} label="Clean it" input={() => ({ rows, standardise_names: one })} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3"><Stat label="Rows" value={`${x.summary.rows_in} → ${x.summary.rows_out}`} note={`header found on line ${x.summary.header_row}`} />
            <Stat label="Changes made" value={x.changes.reduce((a: number, c: Any) => a + c.count, 0)} note={`${x.changes.length} kinds`} />
            <Stat label="To check" value={x.issue_count} note={x.name_groups.length ? `${x.name_groups.length} similar-name group` : undefined} /></div>
          <Panel title="Clean sheet"><div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr>{x.columns.map((c: string) => <th key={c} className="whitespace-nowrap px-1.5 py-1 text-left">{c}</th>)}</tr></thead>
            <tbody>{x.rows.map((row: Any[], i: number) => <tr key={i} className="border-t border-line">{row.map((v, j) => <td key={j} className="whitespace-nowrap px-1.5 py-1 tabular-nums">{v === null ? "" : String(v)}</td>)}</tr>)}</tbody></table></div></Panel>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="What was done"><ul className="space-y-1.5 text-sm">{x.changes.map((c: Any) => <li key={c.what}><span className="font-semibold">{c.count}×</span> {c.what}
              <span className="block text-xs text-muted">{c.examples.join(" · ")}</span></li>)}</ul></Panel>
            <div className="space-y-4">
              {x.issues.length > 0 && <Panel title="For you to check" tone="warn"><ul className="space-y-1.5 text-sm">{x.issues.map((i: Any, n: number) => <li key={n}>
                <span className="font-semibold">{i.row ? `Row ${i.row}` : "Whole column"}, {i.column}{i.value ? `: ${i.value}` : ""}</span><span className="block text-xs text-muted">{i.problem}</span></li>)}</ul></Panel>}
              {x.name_groups.length > 0 && <Panel title="Same party, different spellings"><ul className="space-y-1 text-sm">{x.name_groups.map((g: Any) => <li key={g.use}>
                <span className="font-semibold">{g.use}</span> also written as {g.variants.join(", ")}</li>)}</ul></Panel>}
            </div>
          </div>
        </div>)}
    </TryShell>
  );
}

/* ---------- filing tracker (the board and the WhatsApp status answer) ---------- */

type Card = { client: string; filing: string; owner: string; due: string; status: string };
const STATUSES = ["Documents pending", "Ready to prepare", "Prepared", "Client review", "Filed", "Verified"];
const CARDS: Card[] = [
  { client: "Ramesh Gupta", filing: "ITR AY 2026-27", owner: "Priya", due: "2026-07-31", status: "Documents pending" },
  { client: "Anita Desai", filing: "ITR AY 2026-27", owner: "Priya", due: "2026-07-31", status: "Filed" },
  { client: "Mehta Traders", filing: "GSTR-3B Oct 2026", owner: "Karan", due: "2026-11-20", status: "Prepared" },
  { client: "Sunrise Clinic LLP", filing: "TDS 26Q Q2", owner: "Karan", due: "2026-10-31", status: "Client review" },
  { client: "Vikram Shah", filing: "ITR AY 2026-27", owner: "Priya", due: "2026-07-31", status: "Verified" },
];

const STATUS_REPLY: Record<string, string> = {
  "Documents pending": "we're still waiting for a few documents from you. Reply here with them and we'll get started.",
  "Ready to prepare": "we have everything and will prepare it this week.", Prepared: "it's prepared and with the partner for a final check.",
  "Client review": "it's ready for your review: please check the summary we sent and reply OK.", Filed: "it's been filed. You'll get the acknowledgement here once it's verified.",
  Verified: "it's filed and verified. Nothing more needed from you.",
};

export function FilingTrackerBox() {
  const [cards, setCards] = useState(CARDS);
  const [who, setWho] = useState(CARDS[0]!.client);
  const [asked, setAsked] = useState<string | null>(null);
  const c = cards.find((x) => x.client === who)!;
  const first = who.split(" ")[0];
  return (
    <TryShell title="One board for every return, and clients who stop asking"
      intro="Move a card along the board. Then play the client: ask “is my ITR filed?” on WhatsApp and see the answer the assistant gives from the board, without anyone in your office picking up the phone."
      sell="In the portal the board fills itself each season (ITR, GST, TDS) for the clients they apply to, with owners and due dates; overdue cards alert the partner.">
      <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card"><table className="w-full min-w-[640px] text-sm"><thead><tr className="bg-paper text-left text-xs">{["Client", "Filing", "Owner", "Due", "Status"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
        <tbody>{cards.map((k, i) => (<tr key={k.client} className="border-t border-line"><td className="px-3 py-2 font-medium">{k.client}</td><td className="px-3 py-2">{k.filing}</td><td className="px-3 py-2">{k.owner}</td><td className="px-3 py-2">{fmtDate(k.due)}</td>
          <td className="px-3 py-1.5"><select aria-label={`Status for ${k.client}`} value={k.status} onChange={(e) => setCards(cards.map((x, j) => (j === i ? { ...x, status: e.target.value } : x)))}
            className="rounded-lg border-2 border-line bg-paper px-2 py-1 text-sm">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td></tr>))}</tbody></table></div>
      <div className="mt-6 grid gap-4 md:grid-cols-[16rem_1fr]">
        <div className="space-y-3"><Select id="ft-who" label="You are" value={who} onChange={(v) => { setWho(v); setAsked(null); }} options={cards.map((k) => [k.client, k.client])} />
          <Presets label="Ask" items={["is my ITR filed?", "GST ka kya status hai?", "any update on my return?"].map((v) => ({ label: v, value: v }))} onPick={setAsked} /></div>
        <Panel title={<span className="inline-flex items-center gap-2"><MessageCircle aria-hidden="true" className="h-5 w-5" /> WhatsApp</span>}>
          {asked ? <div className="space-y-3"><Bubble from="them">{asked}</Bubble><Bubble meta="instant, from the board">{`Hi ${first}, about your ${c.filing}: ${STATUS_REPLY[c.status]}\n– Sharma & Associates`}</Bubble></div>
            : <p className="text-sm text-muted">Pick a question to ask as {first}.</p>}</Panel>
      </div>
    </TryShell>
  );
}

/* ---------- recurring entries & budgets (EMI split, schedule, 80% alert) ---------- */

export function RecurringBooksBox() {
  const [rent, setRent] = useState(45000);
  const [retainer, setRetainer] = useState(25000);
  const [loan, setLoan] = useState(1500000);
  const [rate, setRate] = useState(9.5);
  const [years, setYears] = useState(5);
  const [budget, setBudget] = useState(60000);
  const [spent, setSpent] = useState(51000);
  const i = rate / 1200, n = years * 12;
  const emi = loan > 0 && i > 0 && n > 0 ? (loan * i * (1 + i) ** n) / ((1 + i) ** n - 1) : 0;
  let bal = loan;
  const start = new Date();
  const months = Array.from({ length: 6 }, (_, k) => {
    const d = new Date(start.getFullYear(), start.getMonth() + k + 1, 1);
    const interest = bal * i, principal = emi - interest;
    bal = Math.max(0, bal - principal);
    return { d, interest, principal };
  });
  const pct = budget > 0 ? Math.round((spent / budget) * 100) : 0;
  const m = (d: Date, day: number) => new Date(d.getFullYear(), d.getMonth(), day).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return (
    <TryShell title="Rent, retainers and EMIs, booked on their dates"
      intro="Enter a client's regular entries. The next six months of journal entries come out, with each EMI split into interest and principal from the loan schedule, and the budget alert fires at 80%."
      sell="In the portal the entries post themselves on their dates (to the books or a Tally export), and the budget alerts go to the owner on WhatsApp.">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <Field id="rb-rent" label="Office rent / month" type="number" value={rent} onChange={(v) => setRent(Number(v) || 0)} />
        <Field id="rb-ret" label="Retainer received" type="number" value={retainer} onChange={(v) => setRetainer(Number(v) || 0)} />
        <Field id="rb-loan" label="Loan amount" type="number" value={loan} onChange={(v) => setLoan(Number(v) || 0)} />
        <Field id="rb-rate" label="Interest % a year" type="number" value={rate} onChange={(v) => setRate(Number(v) || 0)} />
        <Field id="rb-yrs" label="Years" type="number" value={years} onChange={(v) => setYears(Math.max(1, Number(v) || 1))} />
        <Field id="rb-bud" label="Marketing budget" type="number" value={budget} onChange={(v) => setBudget(Number(v) || 0)} />
        <Field id="rb-spent" label="Spent so far" type="number" value={spent} onChange={(v) => setSpent(Number(v) || 0)} />
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card"><table className="w-full min-w-[560px] text-sm"><thead><tr className="bg-paper text-left text-xs">{["Date", "Entry", "Debit", "Credit", "Amount"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
          <tbody>{months.slice(0, 3).flatMap(({ d, interest, principal }) => [
            rent > 0 && <tr key={`r${d.getMonth()}`} className="border-t border-line"><td className="px-3 py-1.5">{m(d, 1)}</td><td className="px-3 py-1.5">Office rent</td><td className="px-3 py-1.5">Rent</td><td className="px-3 py-1.5">Bank</td><td className="px-3 py-1.5 tabular-nums">{inr(rent)}</td></tr>,
            retainer > 0 && <tr key={`t${d.getMonth()}`} className="border-t border-line"><td className="px-3 py-1.5">{m(d, 5)}</td><td className="px-3 py-1.5">Retainer invoice</td><td className="px-3 py-1.5">Debtors</td><td className="px-3 py-1.5">Fees</td><td className="px-3 py-1.5 tabular-nums">{inr(retainer)}</td></tr>,
            emi > 0 && <tr key={`e${d.getMonth()}`} className="border-t border-line"><td className="px-3 py-1.5">{m(d, 10)}</td><td className="px-3 py-1.5">Loan EMI</td><td className="px-3 py-1.5">Interest {inr(interest)} + Loan {inr(principal)}</td><td className="px-3 py-1.5">Bank</td><td className="px-3 py-1.5 tabular-nums">{inr(emi)}</td></tr>,
          ])}</tbody></table></div>
        <div className="space-y-3">
          <Stat label="EMI" value={inr(emi)} note={`Interest this year ≈ ${inr(months.reduce((a, x) => a + x.interest, 0) * 2)} (deductible for a business loan)`} />
          <div className={`rounded-2xl border-2 p-4 ${pct >= 80 ? "border-danger bg-card" : "border-ink bg-card"}`}>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Marketing budget</p>
            <div className="mt-2 h-3 overflow-hidden rounded-full bg-paper"><div className={`h-full ${pct >= 80 ? "bg-danger" : "bg-ink"}`} style={{ width: `${Math.min(100, pct)}%` }} /></div>
            <p className="mt-2 text-sm">{pct}% used{pct >= 80 ? ": the owner gets an alert on WhatsApp." : "."}</p>
          </div>
        </div>
      </div>
    </TryShell>
  );
}
