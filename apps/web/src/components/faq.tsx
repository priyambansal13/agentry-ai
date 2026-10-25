import { faqs } from "@/lib/content";

export function Faq() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
      <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">Questions</h2>
      <div className="mt-8 divide-y-2 divide-line border-y-2 border-line">
        {faqs.map(([q, a]) => (
          <details key={q} className="group py-5">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-lg font-semibold">
              {q}
              <span aria-hidden="true" className="font-hand text-3xl transition-transform group-open:rotate-45">+</span>
            </summary>
            <p className="mt-3 text-ink-soft">{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
