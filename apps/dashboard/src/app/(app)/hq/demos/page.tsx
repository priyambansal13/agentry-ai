import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { redirect } from "next/navigation";
import { DemoForm } from "@/components/demo-form";
import { formatDateTime } from "@/lib/format";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Demo Studio" };

type Demo = { id: string; name: string; slug: string; website: string | null; industry_pack: string; demo_expires_at: string; chats: number };

export default async function DemosPage() {
  const me = await getMe();
  if (!me.is_staff) redirect("/home");
  const [packs, demos] = await Promise.all([
    api<{ items: { key: string; name: string }[] }>("/hq/packs"),
    api<{ items: Demo[] }>("/hq/demos"),
  ]);
  const web = process.env.NEXT_PUBLIC_WEB_URL ?? "http://localhost:3200";
  return (
    <div className="space-y-8">
      <header>
        <p className="font-hand text-xl text-muted">Agentry HQ</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Demo Studio</h1>
        <p className="mt-1 text-muted">A prospect&apos;s website in, a working demo with <em>their</em> name out. Demos expire after 14 days and never send real messages.</p>
      </header>
      <Card><CardHeader><CardTitle>New demo</CardTitle></CardHeader><CardBody><DemoForm packs={packs.items} /></CardBody></Card>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-muted"><tr>
            <th className="px-5 py-3 font-medium">Prospect</th><th className="px-5 py-3 font-medium">Pack</th>
            <th className="px-5 py-3 text-right font-medium">Chats</th><th className="px-5 py-3 font-medium">Expires</th><th className="px-5 py-3 font-medium">Demo</th>
          </tr></thead>
          <tbody className="divide-y divide-line">
            {demos.items.length === 0 && <tr><td colSpan={5} className="px-5 py-8 text-center text-muted">No demos yet.</td></tr>}
            {demos.items.map((d) => (
              <tr key={d.id}>
                <td className="px-5 py-3"><div className="font-medium">{d.name}</div><div className="text-xs text-muted">{d.website}</div></td>
                <td className="px-5 py-3"><Badge>{d.industry_pack}</Badge></td>
                <td className="px-5 py-3 text-right tabular-nums">{d.chats}</td>
                <td className="px-5 py-3 text-muted">{formatDateTime(d.demo_expires_at)}</td>
                <td className="px-5 py-3"><a className="underline" href={`${web}/demo/${d.slug}`} target="_blank" rel="noopener">Open →</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
