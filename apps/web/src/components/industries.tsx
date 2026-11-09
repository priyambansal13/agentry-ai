import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { audiences, bySlug, midSentence } from "@/lib/catalog";

export function Industries() {
  return (
    <section id="for-you" className="scroll-mt-20 border-y-2 border-ink bg-lime-soft">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <p className="font-hand text-2xl text-muted">start small, then grow</p>
        <h2 className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">Built for businesses like yours</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          {audiences.map((a) => (
            <Link key={a.slug} href={`/for/${a.slug}`}
              className="group flex flex-col rounded-3xl border-2 border-ink bg-card p-6 transition hover:-translate-y-1 hover:shadow-[6px_6px_0_0_var(--ink)] sm:p-8">
              <span className="font-hand text-xl text-muted">{a.hand}</span>
              <h3 className="mt-1 font-display text-2xl font-bold tracking-tight">{a.h1}</h3>
              <ul className="mt-4 flex flex-wrap gap-2">
                {a.agents.slice(0, 4).map((s) => <li key={s} className="rounded-full border border-line px-3 py-1 text-sm">{bySlug(s)?.name}</li>)}
              </ul>
              <span className="mt-6 inline-flex items-center gap-2 font-semibold">
                Agentry for {midSentence(a.name)} <ArrowRight aria-hidden="true" className="h-4 w-4 transition group-hover:translate-x-1" />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
