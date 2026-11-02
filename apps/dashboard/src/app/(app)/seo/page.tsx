import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { RunAudit, WriteArticle } from "@/components/seo";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Local SEO" };

type Issue = { severity: "high" | "medium" | "low"; issue: string; fix: string; pages: string[] };
type D = { latest: { url: string; score: number; created_at: string; result: { issues: Issue[]; pages: { url: string }[] } } | null;
  history: { score: number; at: string }[]; articles: { id: string; topic: string; title: string; status: string; created_at: string }[];
  config: { city: string | null }; can_edit: boolean };
const TONE = { high: "danger", medium: "warning", low: "neutral" } as const;

export default async function SeoPage() {
  const active = await requirePage("seo");
  const d = await api<D>("/org/seo", { orgId: active.id });
  const l = d.latest;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Local SEO</h1>
        <p className="mt-1 max-w-3xl text-muted">What stops your website showing up for people nearby, in the order to fix it, and articles for the questions they search{d.config.city ? ` in ${d.config.city}` : ""},
          written only from your own facts.</p>
      </header>
      {d.can_edit && <Card><CardBody><RunAudit website={l?.url ?? null} /></CardBody></Card>}
      {l && (
        <Card><CardHeader><CardTitle>Website score: {l.score}/100</CardTitle>
          <span className="text-sm text-muted">{l.result.pages.length} pages checked · {new Date(l.created_at).toLocaleDateString("en-IN")}{d.history.length > 1 ? ` · previous ${d.history[1]!.score}` : ""}</span></CardHeader>
          <CardBody><ul className="space-y-3">{l.result.issues.map((i) => (
            <li key={i.issue} className="rounded-xl border-2 border-line p-3 text-sm">
              <p className="flex flex-wrap items-center gap-2 font-semibold"><Badge tone={TONE[i.severity]}>{i.severity}</Badge>{i.issue}</p>
              <p className="mt-1">{i.fix}</p>{i.pages.length > 0 && <p className="mt-1 text-xs text-muted">{i.pages.slice(0, 4).join(" · ")}{i.pages.length > 4 ? ` +${i.pages.length - 4}` : ""}</p>}
            </li>))}{l.result.issues.length === 0 && <li className="text-success">Nothing to fix. 🎉</li>}</ul></CardBody></Card>)}
      <Card><CardHeader><CardTitle>Articles</CardTitle></CardHeader><CardBody className="space-y-3">
        {d.can_edit && <WriteArticle />}
        <ul className="divide-y divide-line">{d.articles.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2 py-2"><Link href={`/seo/${a.id}`} className="font-medium hover:underline">{a.title}</Link>
            <Badge tone={a.status === "needs_attention" ? "warning" : a.status === "published" ? "success" : "neutral"}>{a.status.replace("_", " ")}</Badge></li>))}</ul>
      </CardBody></Card>
    </div>
  );
}
