import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { type CatalogueEvent, MySettings, type Rule, RulesList } from "@/components/notification-rules";
import { api, getActiveOrg } from "@/lib/session";

export const metadata = { title: "Notification rules" };

type Center = { catalogue: CatalogueEvent[]; rules: Rule[]; settings: { quiet: { from: string; to: string } | null; max_per_hour: number };
                channels: string[]; people: { id: string; name: string; role: string }[]; can_edit_business: boolean };

export default async function NotificationRulesPage() {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  const d = await api<Center>("/org/notification-center", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Notification rules</h1>
        <p className="mt-1 text-muted">Choose what reaches whom, and how: Telegram, WhatsApp, email or just the bell.
          {d.can_edit_business ? " Rules here apply to the whole business; anyone can mute one for themselves or add their own." : " You can mute a rule for yourself or add your own."}</p>
      </header>
      <p className="text-sm text-muted">
        You can receive on: {d.channels.map((c) => ({ telegram: "Telegram", whatsapp: "WhatsApp", email: "email", in_app: "the bell" })[c] ?? c).join(", ")}.
        {!d.channels.includes("telegram") && <> Connect Telegram in <Link href="/settings/account" className="underline">Account &amp; notifications</Link> to get them on your phone for free.</>}
      </p>
      <Card><CardHeader><CardTitle>My quiet hours</CardTitle></CardHeader><CardBody>
        <MySettings quiet={d.settings.quiet} maxPerHour={d.settings.max_per_hour} />
      </CardBody></Card>
      <RulesList rules={d.rules} events={d.catalogue} people={d.people} canEditBusiness={d.can_edit_business} channels={d.channels} />
      <p className="text-xs text-muted">Urgent emails, escalations, digests and monthly reports are set in <Link href="/settings/account" className="underline">Account &amp; notifications</Link>.</p>
    </div>
  );
}
