import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { StatementView } from "@/components/statement-view";
import type { StatementDetail } from "@/lib/billing";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe } from "@/lib/session";

export const metadata = { title: "Statement" };

export default async function StatementPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  let d: StatementDetail;
  try {
    d = await api(`/org/billing/statements/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) notFound();
    throw e;
  }
  return (
    <div className="space-y-4">
      <Link href="/billing" className="text-sm text-muted hover:text-ink print:hidden">← Billing</Link>
      <StatementView d={d} canDispute={me.is_staff || can(active.role, "billing", "manage")} company="Agentry" />
    </div>
  );
}
