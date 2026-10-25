/** The proposal a prospect reads: in the HQ proposal builder (live) and on the public proposal page (a sent snapshot).
 *  Display-only: every figure arrives already formatted, so a sent proposal never changes when pricing logic does. */

export type ProposalSnapshot = {
  business: string;
  contact: string;
  date: string; // e.g. "25 October 2026"
  preparedBy: string;
  lost: string; // money lost per month, formatted
  leads: number;
  missed: number;
  closePct: number;
  lostCustomers: string; // e.g. "11.3"
  valuePerCustomer: string;
  cards: { label: string; value: string; note: string }[]; // lost today / win back / return on fee
  agents: string[]; // display names
  modelLabel: string;
  investment: { label: string; amount: string }[];
  gstNote: boolean;
  startSmall: boolean;
};

export function ProposalDocument({ p }: { p: ProposalSnapshot }) {
  return (
    <div>
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-6">
        <div><p className="font-display text-2xl font-bold">Agentry</p><p className="text-sm text-muted">Your AI workforce, done for you.</p></div>
        <div className="text-right text-sm text-muted"><p>Proposal for <span className="font-semibold text-ink">{p.business || "your business"}</span></p><p>{p.date}</p></div>
      </header>
      <section className="mt-8">
        <p className="font-hand text-2xl text-muted">{p.contact ? `Dear ${p.contact},` : "Hello,"}</p>
        <h2 className="mt-2 font-display text-3xl font-bold leading-tight">
          Right now about <span className="bg-lime px-1">{p.lost}</span> a month walks out of the door.
        </h2>
        <p className="mt-3 max-w-2xl text-ink-soft">
          Of your {p.leads} enquiries a month, roughly {p.missed} are missed or followed up too late. At a {p.closePct}% close rate that is
          about {p.lostCustomers} customers, each worth {p.valuePerCustomer}.
        </p>
      </section>
      <section className="mt-8 grid gap-4 sm:grid-cols-3">
        {p.cards.map((c) => (
          <div key={c.label} className="rounded-2xl border-2 border-ink p-5 first:bg-paper last:bg-lime last:text-lime-ink">
            <p className="text-sm font-semibold">{c.label}</p><p className="mt-1 text-3xl font-bold">{c.value}</p><p className="text-sm opacity-80">{c.note}</p>
          </div>
        ))}
      </section>
      <section className="mt-10">
        <h3 className="font-display text-xl font-semibold">What we&apos;ll set up for you</h3>
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">{p.agents.map((a) => (
          <li key={a} className="flex gap-2 rounded-xl bg-paper px-4 py-3 text-sm"><span aria-hidden="true">✓</span>{a}</li>
        ))}{p.agents.length === 0 && <li className="text-sm text-muted">Choose agents on the left.</li>}</ul>
      </section>
      <section className="mt-10">
        <h3 className="font-display text-xl font-semibold">Investment</h3>
        <p className="mt-1 text-sm text-muted">{p.modelLabel}</p>
        <table className="mt-3 w-full text-sm"><tbody className="divide-y divide-line">
          {p.investment.map((i) => (
            <tr key={i.label}><td className="py-2.5">{i.label}</td><td className="py-2.5 text-right font-semibold">{i.amount}</td></tr>
          ))}
        </tbody></table>
        {p.gstNote && <p className="mt-2 text-xs text-muted">Prices exclude 18% GST.</p>}
        {p.startSmall && <p className="mt-3 rounded-xl bg-lime-soft px-4 py-3 text-sm">Step 1 is inbox triage, live in a day. After 30 days you get an opportunity report showing the leads and overdue invoices hiding in your inbox. Then we decide on step 2 together.</p>}
      </section>
      <section className="mt-10 grid gap-6 text-sm sm:grid-cols-2">
        <div><h3 className="font-semibold">How it works</h3><ol className="mt-2 list-decimal space-y-1 pl-5 text-ink-soft">
          <li>We build a demo with your business name (done).</li><li>Live in 7 days: we connect your channels and train the agents on your business.</li>
          <li>You approve anything sensitive from your phone; the agents do the rest.</li><li>Every month you get a results report with evidence for every line you pay for.</li></ol></div>
        <div><h3 className="font-semibold">Our promises</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-ink-soft">
          <li>You see every message the agents send.</li><li>Dispute any charge within 7 days: if it isn&apos;t backed by evidence, it&apos;s removed.</li>
          <li>Your data is yours: export it any time.</li><li>Pause or cancel with 30 days&apos; notice.</li></ul></div>
      </section>
      <footer className="mt-10 border-t border-line pt-4 text-xs text-muted">Prepared by {p.preparedBy} · Agentry · Figures are estimates based on the numbers you shared; your monthly report shows the real ones.</footer>
    </div>
  );
}
