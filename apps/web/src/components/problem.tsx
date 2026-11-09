// The India example from docs/PRICING.md §2 (a dental clinic).
const STEPS: [string, string][] = [["150", "enquiries / month"], ["45", "missed (30%)"], ["1 in 4", "would book"], ["~11", "patients lost"]];

export function Problem() {
  return (
    <section className="border-y-2 border-ink bg-ink text-paper">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <p className="font-hand text-2xl text-lime">what is it worth?</p>
        <h2 className="mt-2 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">
          The leads you miss are costing you more than you think.
        </h2>
        <ol className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STEPS.map(([n, l], i) => (
            <li key={l} className="relative rounded-2xl border border-paper/20 p-5">
              <div className="font-display text-4xl font-bold">{n}</div>
              <div className="mt-1 font-hand text-xl text-paper/70">{l}</div>
              {i < STEPS.length - 1 && <span aria-hidden="true" className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-xl text-lime sm:block">→</span>}
            </li>
          ))}
        </ol>
        <p className="mt-8 text-xl">
          ~11 × ₹8,000 each = <span className="rounded-md bg-lime px-2 py-0.5 font-display font-bold text-lime-ink">₹90,000 / month walking away</span>
        </p>
        <p className="mt-3 max-w-2xl text-paper/70">
          Example numbers for a clinic. Our fee is a slice of the money we win back for you; you keep the rest.{" "}
          <a href="#calculator" className="text-lime underline underline-offset-4">Work out your own →</a>
        </p>
      </div>
    </section>
  );
}
