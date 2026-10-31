import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { NotificationPrefs, PasswordForm, TelegramLink, WhatsAppNumberForm } from "@/components/settings-forms";
import { hasPassword } from "@/lib/clients";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe } from "@/lib/session";

export const metadata = { title: "Notifications & data" };

const SAVED: Record<string, string> = {
  "password-set": "Password set. You can now sign in with it or with an emailed link.",
  "password-changed": "Password changed. Your other devices were signed out.",
};

export default async function AccountSettings({ searchParams }: { searchParams: Promise<{ saved?: string }> }) {
  const { saved } = await searchParams;
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  const [n, tg] = await Promise.all([
    api<{ prefs: Record<string, string[]>; channels: string[]; whatsapp_to: string | null }>("/org/notifications", { orgId: active.id }),
    api<{ available: boolean; bot: string | null; linked: boolean; username: string | null }>("/org/telegram", { orgId: active.id }),
  ]);
  const canExport = me.is_staff || can(active.role, "data", "export");
  const withPassword = await hasPassword(me.user.id);
  return (
    <div className="space-y-6">
      <header><h1 className="font-display text-3xl font-bold tracking-tight">Account, notifications &amp; data</h1></header>
      <Card><CardHeader><CardTitle>Notifications for you</CardTitle><Link href="/settings/notifications" className="text-sm font-medium underline">Notification rules →</Link></CardHeader><CardBody>
        {Object.keys(n.prefs).length
          ? <>{n.channels.includes("whatsapp") && <WhatsAppNumberForm number={n.whatsapp_to} />}<NotificationPrefs prefs={n.prefs} channels={n.channels} /></>
          : <p className="text-sm text-muted">There are no alerts for your role. Your dashboard and reports are always up to date.</p>}
        <p className="mt-3 text-xs text-muted">These settings are yours alone; teammates choose their own.</p>
      </CardBody></Card>
      <Card><CardHeader><CardTitle>Telegram</CardTitle></CardHeader><CardBody><TelegramLink status={tg} /></CardBody></Card>
      <Card><CardHeader><CardTitle>Password</CardTitle><span className="text-sm text-muted">{me.user.email}</span></CardHeader><CardBody>
        {saved && SAVED[saved] && <p role="status" className="mb-4 rounded-xl border-2 border-ink bg-lime px-4 py-2 text-sm text-lime-ink">✓ {SAVED[saved]}</p>}
        <PasswordForm hasPassword={withPassword} />
      </CardBody></Card>
      {canExport && (
        <Card><CardHeader><CardTitle>Export your data</CardTitle></CardHeader><CardBody>
          <p className="text-sm text-muted">Your data is yours. Download it any time as CSV (opens in Excel or Google Sheets).</p>
          <div className="mt-4 flex flex-wrap gap-2">{["contacts", "leads", "invoices", "conversations"].map((k) => (
            <a key={k} href={`/api/export/${k}`} className="rounded-xl border-2 border-ink px-4 py-2 text-sm font-semibold hover:bg-lime-soft">{k}.csv</a>
          ))}</div>
        </CardBody></Card>
      )}
    </div>
  );
}
