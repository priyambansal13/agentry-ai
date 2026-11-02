import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArticleEditor } from "@/components/seo";
import { api, ApiError, requirePage } from "@/lib/session";

export const metadata = { title: "Article" };

type A = { id: string; topic: string; title: string; meta: string | null; body: string; status: string; faqs: { q: string; a: string }[]; checks: string[] };

export default async function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const active = await requirePage("seo");
  const { id } = await params;
  let a: A;
  try {
    a = await api<A>(`/org/seo/articles/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <div className="space-y-5">
      <Link href="/seo" className="text-sm text-muted hover:text-ink">← Local SEO</Link>
      <h1 className="font-display text-3xl font-bold tracking-tight">{a.title}</h1>
      {a.checks.length > 0 && <p className="rounded-2xl border-2 border-warning px-4 py-3 text-sm">Check before approving: {a.checks.join("; ")}</p>}
      <Card><CardBody><ArticleEditor a={a} /></CardBody></Card>
      <Card><CardHeader><CardTitle>FAQs (added as structured data)</CardTitle></CardHeader><CardBody className="space-y-2 text-sm">
        {a.faqs.map((f) => <p key={f.q}><span className="font-semibold">{f.q}</span><span className="block">{f.a}</span></p>)}</CardBody></Card>
    </div>
  );
}
