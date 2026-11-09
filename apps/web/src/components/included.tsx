import { included } from "@/lib/catalog";

export function Included() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <p className="font-hand text-2xl text-muted">in every plan</p>
      <h2 className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">One portal. Your whole AI team.</h2>
      <ul className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {included.map((f, i) => (
          <li key={f.name} className="rounded-3xl border-2 border-ink bg-card p-6">
            <span aria-hidden="true" className="grid h-10 w-10 place-items-center rounded-full border-2 border-ink bg-lime font-display font-bold text-lime-ink">{i + 1}</span>
            <h3 className="mt-4 font-display text-xl font-bold">{f.name}</h3>
            <p className="mt-2 text-ink-soft">{f.line}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
