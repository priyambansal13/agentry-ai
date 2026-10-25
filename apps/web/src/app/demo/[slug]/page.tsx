import { notFound } from "next/navigation";
import { SiteChat } from "@/components/site-chat";

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

type Demo = {
  name: string; website: string | null; brand: { color?: string; logo?: string; description?: string } | null;
  widget_key: string; agent_name: string | null; expires_at: string; services: { name: string; minutes: number; price: number | null }[];
};

export const dynamic = "force-dynamic";
export const metadata = { robots: { index: false, follow: false } };

async function getDemo(slug: string): Promise<Demo | "expired" | null> {
  const r = await fetch(`${API}/public/demos/${encodeURIComponent(slug)}`, { cache: "no-store" });
  if (r.status === 410) return "expired";
  return r.ok ? r.json() : null;
}

export default async function DemoPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const demo = await getDemo(slug);
  if (demo === null) notFound();
  if (demo === "expired") {
    return (
      <main className="grid min-h-dvh place-items-center px-6 text-center">
        <div><p className="font-hand text-3xl text-muted">this demo has expired</p>
          <p className="mt-2">Ask us for a fresh one: <a className="underline" href="/#demo">agentry</a></p></div>
      </main>
    );
  }
  const color = demo.brand?.color ?? "#1f2937";
  const days = Math.max(0, Math.ceil((new Date(demo.expires_at).getTime() - Date.now()) / 86_400_000));
  return (
    <>
      <div className="sticky top-0 z-40 border-b-2 border-ink bg-lime px-4 py-2.5 text-center text-sm text-lime-ink">
        <span className="font-semibold">Demo built for {demo.name} by Agentry.</span> Try the chat in the bottom corner: it knows your website.{" "}
        <a href="/#demo" className="font-semibold underline">Get this live in 7 days →</a>
        <span className="ml-2 opacity-70">({days} days left)</span>
      </div>
      <div style={{ ["--demo" as string]: color }} className="min-h-dvh bg-white text-[#111]">
        <header className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-6">
          {demo.brand?.logo
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={demo.brand.logo} alt="" className="h-10 w-10 rounded-lg object-contain" />
            : <span className="grid h-10 w-10 place-items-center rounded-lg font-bold text-white" style={{ background: color }}>{demo.name.charAt(0)}</span>}
          <span className="text-lg font-semibold">{demo.name}</span>
          <span className="ml-auto hidden text-sm text-gray-500 sm:inline">{demo.website?.replace(/^https?:\/\//, "")}</span>
        </header>
        <section className="mx-auto max-w-5xl px-6 py-16">
          <h1 className="max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">Welcome to {demo.name}</h1>
          {demo.brand?.description && <p className="mt-5 max-w-2xl text-lg text-gray-600">{demo.brand.description}</p>}
          <p className="mt-8 inline-block rounded-full px-5 py-3 font-semibold text-white" style={{ background: color }}>
            Questions? {demo.agent_name ?? "Our assistant"} answers instantly, day or night ↘
          </p>
        </section>
        {demo.services.length > 0 && (
          <section className="mx-auto max-w-5xl px-6 pb-24">
            <h2 className="text-2xl font-bold">Services</h2>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {demo.services.map((s) => (
                <div key={s.name} className="rounded-2xl border border-gray-200 p-5">
                  <div className="font-semibold">{s.name}</div>
                  <div className="mt-1 text-sm text-gray-500">{s.minutes} min{s.price ? ` · ₹${Number(s.price).toLocaleString("en-IN")}` : ""}</div>
                </div>
              ))}
            </div>
          </section>
        )}
        <footer className="border-t border-gray-200 py-8 text-center text-xs text-gray-400">
          Preview page generated from {demo.website ?? "your website"} for a private Agentry demo.
        </footer>
      </div>
      <SiteChat widgetKey={demo.widget_key} openAfter={1500} />
    </>
  );
}
