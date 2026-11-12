import { Bot, Check, User, Users, X } from "lucide-react";
import { stories, WHO_LABEL, type Who } from "@/lib/agent-story";
import { midSentence } from "@/lib/catalog";
import { SketchFlow } from "./sketch";

const WHO_STYLE: Record<Who, string> = {
  agent: "bg-lime text-lime-ink border-ink", you: "bg-ink text-paper border-ink", team: "bg-card text-ink border-ink", customer: "bg-paper text-ink border-ink/40",
};
const WHO_ICON: Record<Who, typeof Bot> = { agent: Bot, you: User, team: Users, customer: User };

/** How the agent works, step by step, and what changes in your week: plain words for the agent's page. */
export function AgentStory({ slug, name }: { slug: string; name: string }) {
  const s = stories[slug];
  if (!s) return null;
  return (
    <section aria-labelledby="how-it-works" className="mt-16">
      <p className="font-hand text-2xl text-muted">how it works</p>
      <h2 id="how-it-works" className="mt-1 font-display text-3xl font-bold tracking-tight">From the first message to the result</h2>
      <SketchFlow steps={s.flow} highlight={s.highlight} seed={slug.length} label={`${name}: ${s.flow.join(", then ")}`} className="mt-6" />

      <div className="mt-10 grid gap-8 lg:grid-cols-[1.25fr_1fr]">
        <ol className="space-y-4">
          {s.steps.map(([who, text], i) => {
            const Icon = WHO_ICON[who];
            return (
              <li key={i} className="flex gap-4">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border-2 border-ink bg-card font-display font-bold">{i + 1}</span>
                <div className="pt-0.5">
                  <span className={`inline-flex items-center gap-1 rounded-full border-2 px-2 py-0.5 text-xs font-semibold ${WHO_STYLE[who]}`}>
                    <Icon aria-hidden="true" className="h-3.5 w-3.5" />{WHO_LABEL[who]}</span>
                  <p className="mt-1.5 text-ink-soft">{text}</p>
                </div>
              </li>);
          })}
        </ol>

        <div className="rounded-3xl border-2 border-ink bg-card p-6 shadow-[6px_6px_0_0_var(--ink)]">
          <h3 className="font-display text-xl font-bold">Your week, before and after</h3>
          <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-1">
            <div>
              <p className="text-sm font-semibold uppercase tracking-wide text-muted">Without it</p>
              <ul className="mt-2 space-y-2">{s.before.map((b) => (
                <li key={b} className="flex gap-2 text-sm"><X aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-danger" />{b}</li>))}</ul>
            </div>
            <div className="rounded-2xl bg-lime-soft p-4">
              <p className="text-sm font-semibold uppercase tracking-wide">With {midSentence(name)}</p>
              <ul className="mt-2 space-y-2">{s.after.map((b) => (
                <li key={b} className="flex gap-2 text-sm font-medium"><Check aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-success" />{b}</li>))}</ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
