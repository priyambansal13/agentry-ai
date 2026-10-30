import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { type BrandKit, BrandForm, VoiceForm } from "@/components/content";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Brand kit" };

export default async function BrandKitPage() {
  const active = await requirePage("content");
  const kit = await api<BrandKit & { can_edit: boolean }>("/org/content/brand", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <Link href="/content" className="text-sm text-muted hover:text-ink">← Content</Link>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">Brand kit</h1>
        <p className="mt-1 text-muted">How your posts look and sound. Changing colours or the card style redraws every image not yet published.</p>
      </header>
      {!kit.can_edit && <p className="text-sm text-muted">Only owners and managers can change the brand kit.</p>}
      <Card><CardHeader><CardTitle>Look</CardTitle></CardHeader><CardBody>{kit.can_edit ? <BrandForm kit={kit} /> : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/api/content-preview?platform=instagram" alt="A sample quote card in your brand" className="max-w-sm rounded-lg border border-line" />
      )}</CardBody></Card>
      <Card><CardHeader><CardTitle>Voice</CardTitle></CardHeader><CardBody>
        {kit.can_edit ? <VoiceForm voice={kit.voice} samples={kit.voice_samples} /> : <p className="whitespace-pre-wrap text-sm">{kit.voice ?? "Not learned yet."}</p>}
      </CardBody></Card>
    </div>
  );
}
