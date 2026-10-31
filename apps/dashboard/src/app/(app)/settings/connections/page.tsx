import { Badge, Card } from "@agentry/ui";
import { redirect } from "next/navigation";
import { AlertTemplateForm, type Connection, GmailInboxes, GoogleSheetsCard, InstagramCard, OutlookInboxes, TelegramCard, WhatsAppCard } from "@/components/connections";
import { GatewayCards } from "@/components/gateway-cards";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getFeatures, getMe, requirePage } from "@/lib/session";

export const metadata = { title: "Connections" };

type Data = {
  items: Connection[]; available: { gmail: boolean; outlook: boolean; whatsapp: boolean; instagram: boolean; google_sheets: boolean };
  whatsapp_webhook: { url: string; verify_token_set: boolean };
};

export default async function ConnectionsPage({ searchParams }: { searchParams: Promise<Record<string, string>> }) {
  const [sp, me, active] = await Promise.all([searchParams, getMe(), getActiveOrg()]);
  await requirePage("connections");
  if (!active) redirect("/home");
  const [d, features] = await Promise.all([api<Data>("/org/connections", { orgId: active.id }), getFeatures(active.id)]);
  const show = (k: string) => features.connections.includes(k);
  const canManage = me.is_staff || can(active.role, "connection", "manage");
  if (!canManage) redirect("/home");
  const find = (p: string) => d.items.find((c) => c.provider === p);
  const people = show("gmail")
    ? await api<{ items: { id: string; name: string }[] }>("/org/assignees", { orgId: active.id }).then((r) => r.items).catch(() => [])
    : [];
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Connections</h1>
        <p className="mt-1 text-muted">The accounts your agents work through. You can disconnect any of them at any time.</p>
      </header>
      {sp.connected && <p role="status" className="rounded-2xl border-2 border-ink bg-lime px-4 py-3 text-lime-ink">✓ {({ gmail: "Gmail", outlook: "Outlook", instagram: "Instagram", google_sheets: "Google Sheets" } as Record<string, string>)[sp.connected] ?? sp.connected} connected{sp.account ? `: ${sp.account}` : ""}.{["gmail", "outlook"].includes(sp.connected) ? " New mail is checked every minute." : sp.connected === "instagram" ? " Approved posts now go out at their scheduled time." : sp.connected === "google_sheets" ? " Filed receipts are added to the new spreadsheet." : ""}</p>}
      {sp.error && <p role="alert" className="rounded-2xl border-2 border-danger px-4 py-3 text-danger">{sp.error}</p>}
      {show("gmail") && <GmailInboxes conns={d.items.filter((c) => c.provider === "gmail")} available={d.available.gmail} canManage={canManage} people={people} />}
      {show("outlook") && <OutlookInboxes conns={d.items.filter((c) => c.provider === "outlook")} available={d.available.outlook} canManage={canManage} />}
      {show("whatsapp") && <WhatsAppCard conn={find("whatsapp")} available={d.available.whatsapp} canManage={canManage} />}
      {show("telegram") && <TelegramCard conn={find("telegram")} canManage={canManage} />}
      {show("google_sheets") && <GoogleSheetsCard conn={find("google_sheets")} available={d.available.google_sheets} canManage={canManage} />}
      {show("instagram") && <InstagramCard conn={find("instagram")} available={d.available.instagram} canManage={canManage} />}
      {find("whatsapp") && canManage && (
        <Card className="p-5"><p className="text-sm font-semibold">WhatsApp alerts</p>
          <p className="mt-1 text-sm text-muted">Urgent alerts and the Monday summary can go to each person&apos;s WhatsApp (they choose on Account &amp; notifications). Meta requires an approved template for this.</p>
          <AlertTemplateForm conn={find("whatsapp")!} /></Card>
      )}
      {show("phone") && <PhoneCard conn={find("phone")} staff={me.is_staff} />}
      {show("gateways") && <GatewayCards razorpay={find("razorpay")} stripe={find("stripe")} canManage={canManage} />}
      {me.is_staff && show("whatsapp") && (
        <Card className="p-5 text-sm">
          <p className="font-semibold">Agentry staff: Meta webhook (configured once for the Agentry app, not per client)</p>
          <p className="mt-1 text-muted">Callback URL: <code>{d.whatsapp_webhook.url}</code> · verify token {d.whatsapp_webhook.verify_token_set ? "set in .env" : "MISSING"}. Subscribe the <code>messages</code> field. See docs/setup/whatsapp.md.</p>
        </Card>
      )}
    </div>
  );
}

function PhoneCard({ conn, staff }: { conn?: Connection; staff: boolean }) {
  const n = conn?.status === "connected" ? conn.account_ref : null;
  return (
    <Card className="space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">Phone number</h2>
        <Badge tone={n ? "success" : "neutral"}>{n ? "Answering calls" : "Not assigned yet"}</Badge>
      </div>
      {n ? (
        <>
          <p className="text-sm">Your AI receptionist answers calls to <span className="font-mono font-semibold">{n}</span>.</p>
          <div className="text-sm text-muted">
            <p className="font-medium text-ink">Send your calls to it with call forwarding (most mobiles; dial from your business phone):</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              <li>When you don&apos;t answer: <code>**61*{n}#</code></li>
              <li>When you&apos;re busy: <code>**67*{n}#</code></li>
              <li>When you&apos;re unreachable: <code>**62*{n}#</code></li>
              <li>Always (e.g. after hours): <code>**21*{n}#</code> · turn off with <code>##21#</code></li>
            </ul>
            <p className="mt-1">Or give this number out directly. Each call shows up in Conversations with a recording and summary.</p>
          </div>
        </>
      ) : (
        <p className="text-sm text-muted">{staff ? "Assign a number from Agentry HQ → this client → Phone number." : "Agentry is setting up your receptionist's phone number."}</p>
      )}
    </Card>
  );
}
