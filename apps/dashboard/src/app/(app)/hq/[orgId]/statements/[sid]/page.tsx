import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { StatementActions } from "@/components/hq-billing";
import { StatementView } from "@/components/statement-view";
import type { StatementDetail } from "@/lib/billing";
import { api, ApiError, getMe } from "@/lib/session";

export const metadata = { title: "Statement · Agentry HQ" };

export default async function HqStatement({ params }: { params: Promise<{ orgId: string; sid: string }> }) {
  const [{ orgId, sid }, me] = await Promise.all([params, getMe()]);
  if (!me.is_staff) redirect("/home");
  let d: StatementDetail;
  try {
    d = await api<StatementDetail>(`/hq/orgs/${orgId}/statements/${sid}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const s = d.statement;
  return (
    <div className="space-y-4">
      <Link href={`/hq/${orgId}`} className="text-sm text-muted hover:text-ink print:hidden">← {d.client.name}</Link>
      <StatementActions orgId={orgId} sid={sid} status={s.status} total={s.total} currency={s.currency}
        disputes={d.lines.filter((l) => l.disputed && !l.dispute_resolution)} evidence={d.evidence} />
      <StatementView d={d} canDispute={false} company="Agentry" />
    </div>
  );
}
