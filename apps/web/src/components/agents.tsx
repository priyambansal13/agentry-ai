import { Badge } from "@agentry/ui";
import { agents } from "@/lib/content";
import { SketchFlow } from "./sketch";

export function Agents() {
  return (
    <section id="agents" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
      <p className="font-hand text-2xl text-muted">meet the team</p>
      <h2 className="mt-1 max-w-3xl font-display text-3xl font-bold tracking-tight sm:text-5xl">
        Eight agents. Each does one boring job <span className="highlight">really well.</span>
      </h2>
      <div className="mt-12 grid gap-5 md:grid-cols-2">
        {agents.map((a, i) => (
          <article key={a.key} className="group rounded-3xl border-2 border-ink bg-card p-6 transition-transform duration-200 hover:-translate-y-1 hover:shadow-[6px_6px_0_0_var(--ink)]">
            <div className="flex flex-col-reverse items-start justify-between gap-3 sm:flex-row">
              <div>
                <h3 className="font-display text-2xl font-bold tracking-tight">{a.name}</h3>
                <p className="mt-1 font-hand text-xl text-muted">{a.tagline}</p>
              </div>
              <Badge tone="lime" className="shrink-0">{a.pricing}</Badge>
            </div>
            <SketchFlow steps={a.flow} highlight={a.highlight} seed={i + 3} label={`${a.name}: ${a.flow.join(", then ")}`} className="mt-6" />
            <p className="mt-5 text-ink-soft"><span className="font-semibold text-ink">Result:</span> {a.outcome}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
