import { notFound } from "next/navigation";
import { ConfirmUnsubscribe } from "./confirm";

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

export const dynamic = "force-dynamic";
export const metadata = { title: "Unsubscribe", robots: { index: false, follow: false } };

/** The link at the bottom of every cold email. One button, no sign-in, no questions. (Mail apps use the one-click header.) */
export default async function UnsubscribePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const r = await fetch(`${API}/public/unsubscribe/${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!r.ok) notFound();
  const d = (await r.json()) as { business: string; email: string; unsubscribed: boolean };
  return (
    <main className="mx-auto max-w-lg px-4 py-16 sm:py-24">
      <h1 className="font-display text-3xl font-bold tracking-tight">Stop emails from {d.business}</h1>
      {d.unsubscribed ? (
        <p className="mt-4 text-muted">{d.email} is already unsubscribed. You won&apos;t hear from {d.business} again.</p>
      ) : (
        <>
          <p className="mt-4 text-muted">{d.email} will be removed straight away and never emailed by {d.business} again.</p>
          <ConfirmUnsubscribe token={token} email={d.email} />
        </>
      )}
    </main>
  );
}
