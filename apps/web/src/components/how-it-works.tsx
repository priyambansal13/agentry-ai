const STEPS = [
  ["A demo with your name", "Tell us your website. We build your agent with your business name, services and FAQs, and send a 2-minute video."],
  ["Live in 7 days", "We connect your phone, inbox, WhatsApp and calendar, load your knowledge, and test everything with you."],
  ["You approve, agents work", "Agents start in approval mode. You see every draft until you trust them, then let them run."],
  ["Pay for results", "One login shows every call, lead, booking and rupee won back, next to what you pay us."],
];

export function HowItWorks() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <p className="font-hand text-2xl text-muted">how it works</p>
      <h2 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-5xl">Done for you, start to finish</h2>
      <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map(([title, body], i) => (
          <li key={title} className="rounded-3xl border-2 border-ink bg-card p-6">
            <span className="font-hand text-4xl text-muted">{i + 1}.</span>
            <h3 className="mt-2 font-display text-xl font-bold">{title}</h3>
            <p className="mt-2 text-ink-soft">{body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
