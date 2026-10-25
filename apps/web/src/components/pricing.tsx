const MODELS = [
  { title: "Retainer", hand: "paid every month", points: ["One-time setup fee", "Fixed monthly retainer", "Minutes and messages included"], best: "Content, inbox triage, receptionist" },
  { title: "Pay per result", hand: "you win when they win", points: ["Pay per booked appointment", "10–20% of what a customer is worth", "Every charge shows its proof"], best: "Speed-to-lead, reactivation, chat" },
  { title: "Start small", hand: "foot in the door", points: ["One agent, live in a week", "See the numbers in your dashboard", "Add the next agent when it pays"], best: "Everyone, honestly" },
];

export function Pricing() {
  return (
    <section id="pricing" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
      <p className="font-hand text-2xl text-muted">how to pay</p>
      <h2 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-5xl">Three ways to work with us</h2>
      <div className="mt-12 grid gap-5 lg:grid-cols-3">
        {MODELS.map((m, i) => (
          <article key={m.title} className={`rounded-3xl border-2 border-ink p-7 ${i === 1 ? "bg-lime text-lime-ink shadow-[6px_6px_0_0_var(--ink)]" : "bg-card"}`}>
            <h3 className="font-display text-2xl font-bold">{m.title}</h3>
            <p className="font-hand text-xl opacity-75">{m.hand}</p>
            <ul className="mt-6 space-y-2">
              {m.points.map((p) => <li key={p} className="flex gap-2"><span aria-hidden="true">✓</span>{p}</li>)}
            </ul>
            <p className="mt-6 border-t-2 border-current/15 pt-4 text-sm opacity-80">Best for: {m.best}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
