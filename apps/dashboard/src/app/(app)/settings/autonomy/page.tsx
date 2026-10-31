import { redirect } from "next/navigation";
import { AutonomyRow, type GovAction } from "@/components/autonomy";
import { api, ApiError, getActiveOrg } from "@/lib/session";

export const metadata = { title: "Autonomy & limits" };

export default async function AutonomyPage() {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  let d: { actions: GovAction[]; can_change: boolean };
  try {
    d = await api("/org/governance", { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Autonomy &amp; limits</h1>
        <p className="mt-1 text-muted">How much each agent may do on its own. Everything starts as a suggestion you approve; give an action more
          freedom once its track record earns it. Daily limits and quiet hours always apply, and anything held back becomes a card.</p>
      </header>
      {d.actions.length === 0 ? <p className="text-muted">None of this business&apos;s agents send anything on their own.</p>
        : d.actions.map((a) => <AutonomyRow key={a.action} a={a} canChange={d.can_change} />)}
    </div>
  );
}
