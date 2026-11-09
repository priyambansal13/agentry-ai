import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { catalog, groups, inGroup } from "@/lib/catalog";

/** Every agent, grouped. Plain links (crawlable), each to its own page. */
export function AllAgents({ heading = true }: { heading?: boolean }) {
  return (
    <section id="agents" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6" aria-labelledby={heading ? "agents-title" : undefined}>
      {heading && (
        <>
          <p className="font-hand text-2xl text-muted">meet the team</p>
          <h2 id="agents-title" className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">
            {catalog.length} agents. Each does one boring job <span className="highlight">really well.</span>
          </h2>
          <p className="mt-4 max-w-2xl text-lg text-ink-soft">Start with one. Add the next when it pays for itself. Every agent works alone or as part of a pack.</p>
        </>
      )}
      <div className="mt-12 grid gap-5 lg:grid-cols-2">
        {groups.map((g) => (
          <article key={g.key} id={`group-${g.key}`}
            className={`scroll-mt-24 rounded-3xl border-2 border-ink bg-card p-6 sm:p-7 ${g.key === "ca" ? "lg:col-span-2" : ""}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-display text-2xl font-bold tracking-tight">{g.name}</h3>
              <span className="rounded-full bg-lime px-3 py-0.5 text-sm font-semibold text-lime-ink">{inGroup(g.key).length} agents</span>
            </div>
            <p className="mt-1 font-hand text-xl text-muted">{g.hand}</p>
            <ul className={`mt-5 grid gap-2 ${g.key === "ca" ? "sm:grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2"}`}>
              {inGroup(g.key).map((a) => (
                <li key={a.slug}>
                  <Link href={`/agents/${a.slug}`}
                    className="group flex h-full items-start justify-between gap-3 rounded-2xl border-2 border-line px-4 py-3 transition hover:-translate-y-0.5 hover:border-ink hover:bg-lime-soft">
                    <span>
                      <span className="block font-semibold">{a.name}</span>
                      <span className="mt-0.5 block text-sm text-ink-soft">{a.line}</span>
                    </span>
                    <ArrowUpRight aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted transition group-hover:text-ink" />
                  </Link>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
