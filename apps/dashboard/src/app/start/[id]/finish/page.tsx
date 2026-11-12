import { redirect } from "next/navigation";
import { api, ApiError, getMe } from "@/lib/session";

export const metadata = { title: "Setting up your account" };

/** After the emailed link signed the owner in: switch the plan on for their new organisation, then onboarding. */
export default async function FinishSignup({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ k?: string }> }) {
  const [{ id }, { k }] = await Promise.all([params, searchParams]);
  const me = await getMe();
  const owned = me.organizations.filter((o) => o.role === "owner");
  let error: string | null = null;
  for (const o of owned) {
    try {
      await api(`/signups/${id}/provision`, { method: "POST", orgId: o.id, body: { k } });
      error = null;
      break;
    } catch (e) {
      error = e instanceof ApiError ? (() => { try { return JSON.parse(e.message).detail as string; } catch { return e.message; } })() : "Something went wrong";
    }
  }
  if (!error) redirect("/onboarding?welcome=1");
  return (
    <main className="mx-auto max-w-lg px-6 py-20 text-center">
      <h1 className="font-display text-3xl font-bold">We couldn&apos;t finish setting up</h1>
      <p className="mt-3 text-muted">{error}. Your payment is safe: reply to the email we sent and we&apos;ll finish it for you.</p>
    </main>
  );
}
