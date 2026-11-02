import { Card, CardBody } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DocEditor } from "@/components/docs";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Document" };

export default async function DocPage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("docs");
  const { id } = await params;
  let d: { id: string; title: string; content: string; diagram: string | null; status: string; checks: string[] };
  try {
    d = await api(`/org/docs/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <div className="space-y-5">
      <Link href="/docs" className="text-sm text-muted hover:text-ink">← Documents</Link>
      <h1 className="font-display text-3xl font-bold tracking-tight">{d.title}</h1>
      {d.checks.length > 0 && <p className="rounded-2xl border-2 border-warning px-4 py-3 text-sm">Check: {d.checks.join("; ")}</p>}
      <Card><CardBody><DocEditor d={d} /></CardBody></Card>
    </div>
  );
}
