import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { redirect } from "next/navigation";
import { AddFaqForm, AddTextForm, DeleteDoc, LearnWebsiteForm, UploadFileForm } from "@/components/knowledge-forms";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Knowledge" };

type Doc = { id: string; source_type: "faq" | "url" | "text" | "file"; source_ref: string | null; title: string | null; preview: string; chunks: number };

const SOURCE: Record<Doc["source_type"], string> = { faq: "FAQ", url: "Web page", text: "Text", file: "Document" };

export default async function KnowledgePage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  await requirePage("knowledge");
  if (!active) redirect("/home");
  if (!(me.is_staff || can(active.role, "conversation", "read"))) redirect("/home");
  const [{ items }, profile] = await Promise.all([
    api<{ items: Doc[] }>("/org/knowledge", { orgId: active.id }),
    api<{ website: string | null }>("/org/profile", { orgId: active.id }),
  ]);
  const canEdit = me.is_staff || can(active.role, "automation", "configure");
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Knowledge</h1>
        <p className="mt-1 text-muted">Everything your agents know about {active.name}. They only answer from this, never from guesswork.</p>
      </header>
      {canEdit && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Add an answer</CardTitle></CardHeader><CardBody><AddFaqForm /></CardBody></Card>
          <Card><CardHeader><CardTitle>Read your website</CardTitle></CardHeader><CardBody>
            <p className="mb-3 text-sm text-muted">We read up to 8 pages (services, prices, FAQs, contact) and keep them up to date.</p>
            <LearnWebsiteForm defaultUrl={profile.website} />
          </CardBody></Card>
          <Card><CardHeader><CardTitle>Paste text</CardTitle></CardHeader><CardBody><AddTextForm /></CardBody></Card>
          <Card><CardHeader><CardTitle>Upload a document</CardTitle></CardHeader><CardBody><UploadFileForm /></CardBody></Card>
        </div>
      )}
      <Card className="divide-y divide-line">
        {items.length === 0 && <p className="p-8 text-center text-muted">Nothing yet. Add an answer, paste text, upload a document or read your website above.</p>}
        {items.map((d) => (
          <div key={d.id} className="flex items-start gap-4 px-5 py-4">
            <Badge className="mt-0.5 shrink-0">{SOURCE[d.source_type]}</Badge>
            <div className="min-w-0 flex-1">
              <div className="font-medium">{d.title ?? d.source_ref}</div>
              <p className="line-clamp-2 text-sm text-muted">{d.preview}</p>
            </div>
            {canEdit && <DeleteDoc id={d.id} title={d.title ?? "this"} />}
          </div>
        ))}
      </Card>
    </div>
  );
}
