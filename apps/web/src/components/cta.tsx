import { buttonClasses } from "@agentry/ui";

/** The closing call to action on agent and industry pages. */
export function Cta({ title = "See it with your own business name", hand = "free, no call needed" }: { title?: string; hand?: string }) {
  return (
    <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
      <div className="rounded-3xl border-2 border-ink bg-lime p-8 text-lime-ink shadow-[6px_6px_0_0_var(--ink)] sm:p-12">
        <p className="font-hand text-2xl">{hand}</p>
        <h2 className="mt-1 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">{title}</h2>
        <p className="mt-3 max-w-xl">Tell us your website. Within one working day you get a short video of your own agent answering your customers.</p>
        <a href="#demo" className={`${buttonClasses("primary", "lg")} mt-6`}>Build my free demo</a>
      </div>
    </section>
  );
}
