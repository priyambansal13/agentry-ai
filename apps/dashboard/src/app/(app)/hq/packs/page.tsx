import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { redirect } from "next/navigation";
import type { CatalogItem } from "@/components/new-client-form";
import { type Pack, PackEditor } from "@/components/packs";
import { api, getMe } from "@/lib/session";

export const metadata = { title: "Packs · Agentry HQ" };

const price = (p: Pack, c: string, sym: string) => (p.pricing[c]?.retainer ? `${sym}${Number(p.pricing[c]!.retainer).toLocaleString("en-IN")}/month` : null);

export default async function PacksPage({ searchParams }: { searchParams: Promise<{ edit?: string }> }) {
  const [me, { edit }] = await Promise.all([getMe(), searchParams]);
  if (!me.is_staff) redirect("/home");
  const { items, catalog } = await api<{ items: Pack[]; catalog: CatalogItem[] }>("/hq/agent-packs");
  const name = Object.fromEntries(catalog.map((c) => [c.key, c]));
  return (
    <div className="space-y-6">
      <header>
        <p className="font-hand text-xl text-muted">Agentry HQ</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Packs</h1>
        <p className="mt-1 max-w-3xl text-muted">Bundles of agents for one kind of business. Give a client a pack on their page and tick which of its agents they get;
          any agent can also be added on its own. Coming-soon agents can be in a pack: they&apos;re switched on for its clients once built.</p>
      </header>

      {items.map((p) => (
        <Card key={p.key}>
          <CardHeader>
            <CardTitle>{p.name}{!p.active && <Badge className="ml-2">archived</Badge>}</CardTitle>
            <span className="text-sm text-muted">{p.clients ?? 0} client{p.clients === 1 ? "" : "s"} · {[price(p, "INR", "₹"), price(p, "USD", "$")].filter(Boolean).join(" · ")}</span>
          </CardHeader>
          <CardBody className="space-y-3">
            {p.tagline && <p className="font-medium">{p.tagline}</p>}
            {p.audience && <p className="text-sm text-muted">For: {p.audience}</p>}
            {edit === p.key ? <PackEditor pack={p} catalog={catalog} /> : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {p.agents.map((a) => (
                    <span key={a.key} className={`rounded-full border-2 px-2.5 py-0.5 text-sm ${a.default_on ? "border-ink bg-lime-soft" : "border-line"}`}>
                      {name[a.key]?.name ?? a.key}{!name[a.key]?.available && <span className="text-muted"> · soon</span>}</span>
                  ))}
                </div>
                <p className="text-xs text-muted">Highlighted: on by default. {p.agents.filter((a) => name[a.key]?.available).length} of {p.agents.length} agents built today.</p>
                <a href={`/hq/packs?edit=${p.key}`} className="text-sm font-semibold underline">Edit pack</a>
              </>
            )}
          </CardBody>
        </Card>
      ))}

      <Card>
        <CardHeader><CardTitle>New pack</CardTitle></CardHeader>
        <CardBody><PackEditor catalog={catalog} /></CardBody>
      </Card>
    </div>
  );
}
