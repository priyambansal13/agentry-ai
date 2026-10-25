import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { SavedReply } from "@/components/approval-card";
import { SavedReplyEditor } from "@/components/saved-replies";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Saved replies" };

export default async function SavedRepliesPage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  await requirePage("needs-you");
  if (!active) redirect("/home");
  let items: SavedReply[];
  try {
    items = (await api<{ items: SavedReply[] }>("/org/reply-templates", { orgId: active.id })).items;
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  const canEdit = me.is_staff || can(active.role, "automation", "configure");
  return (
    <div className="space-y-6">
      <Link href="/needs-you" className="text-sm text-muted hover:text-ink">← Needs you</Link>
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Saved replies</h1>
        <p className="mt-1 max-w-2xl text-muted">Answers you give again and again (prices, timings, documents needed). Pick one on any draft in Needs you, and the AI uses them when it writes drafts.</p>
      </header>
      {canEdit && <Card><CardHeader><CardTitle>Add a saved reply</CardTitle></CardHeader><CardBody><SavedReplyEditor /></CardBody></Card>}
      {items.length === 0 && <Card className="p-8 text-center text-muted">No saved replies yet.</Card>}
      <div className="space-y-3">{items.map((t) => (
        <Card key={t.id}><CardBody>{canEdit ? <SavedReplyEditor t={t} /> : <><p className="font-semibold">{t.title}</p><p className="mt-1 whitespace-pre-wrap text-sm text-ink-soft">{t.body}</p></>}</CardBody></Card>
      ))}</div>
    </div>
  );
}
