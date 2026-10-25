import { Card } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { type Approval, ApprovalCard, type Assignee, type OpenInvoice, type SavedReply } from "@/components/approval-card";
import { canOnItem } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Needs you" };

export default async function NeedsYouPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const [me, active, sp] = await Promise.all([getMe(), getActiveOrg(), searchParams]);
  await requirePage("needs-you");
  if (!active) redirect("/home");
  const view = sp.view === "snoozed" || sp.view === "mine" ? sp.view : "now";
  let data: { items: Approval[]; pending_by_kind: Record<string, number>; snoozed: number };
  try {
    data = await api(`/org/approvals?view=${view}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  const canActOn = (key: string | null) => me.is_staff || canOnItem(active.role, key, "act");
  const needsInvoices = data.items.some((a) => a.kind === "payment_review" && (a.payload as { payment_id?: string })?.payment_id);
  const openInvoices: OpenInvoice[] = needsInvoices
    ? await api<{ items: { id: string; number: string; balance: number; company: string | null; status: string }[] }>("/org/invoices", { orgId: active.id })
        .then((r) => r.items.filter((i) => ["open", "partially_paid", "disputed"].includes(i.status)).map((i) => ({ id: i.id, number: i.number, balance: Number(i.balance), company: i.company })))
        .catch(() => [])
    : [];
  const [templates, assignees] = await Promise.all([
    api<{ items: SavedReply[] }>("/org/reply-templates", { orgId: active.id }).then((r) => r.items).catch(() => [] as SavedReply[]),
    api<{ items: Assignee[] }>("/org/assignees", { orgId: active.id }).then((r) => r.items).catch(() => [] as Assignee[]),
  ]);
  const tab = (v: string, label: string) => (
    <Link href={v === "now" ? "/needs-you" : `/needs-you?view=${v}`} aria-current={view === v ? "page" : undefined}
      className={`rounded-full border-2 px-3 py-1 text-sm ${view === v ? "border-ink bg-lime font-semibold" : "border-line text-muted hover:text-ink"}`}>{label}</Link>
  );
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Needs you</h1>
        <p className="mt-1 text-muted">Drafts waiting for your OK and conversations that need a person. Nothing is sent until you approve it.</p>
        <nav className="mt-4 flex flex-wrap items-center gap-2" aria-label="Needs you views">
          {tab("now", "Waiting")}{tab("mine", "Mine")}{tab("snoozed", `Snoozed${data.snoozed ? ` (${data.snoozed})` : ""}`)}
          <Link href="/saved-replies" className="ml-auto text-sm text-muted underline-offset-4 hover:text-ink hover:underline">Saved replies →</Link>
        </nav>
      </header>
      {data.items.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="font-hand text-3xl text-muted">{view === "snoozed" ? "nothing snoozed" : "all clear!"}</p>
          <p className="mt-1 text-muted">{view === "snoozed" ? "Snoozed cards come back here at their time." : "Nothing is waiting for you right now."}</p>
        </Card>
      ) : (
        <div className="space-y-4">{data.items.map((a) => <ApprovalCard key={a.id} a={a} canAct={canActOn(a.automation_key)} templates={templates} assignees={assignees} openInvoices={openInvoices} />)}</div>
      )}
    </div>
  );
}
