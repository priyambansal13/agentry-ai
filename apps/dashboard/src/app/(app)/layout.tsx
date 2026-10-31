import { Logo } from "@agentry/ui";
import { Bell } from "@/components/bell";
import { Nav } from "@/components/nav";
import { OrgSwitcher } from "@/components/org-switcher";
import { SignOut } from "@/components/sign-out";
import { can } from "@/lib/permissions";
import { ExitClientView } from "@/components/view-as";
import { api, getActiveOrg, getFeatures, getMe } from "@/lib/session";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  const features = active ? await getFeatures(active.id).catch(() => null) : null;
  const role = active?.role;
  const canConverse = me.is_staff || can(role, "conversation", "read");
  // finance works the invoice items in Needs you and Conversations
  const canWork = canConverse || (can(role, "invoice", "read") && !!(features?.pages.includes("invoices") || features?.pages.includes("bookkeeping")));
  const needsYou = active && canWork
    ? await api<{ pending_by_kind: Record<string, number> }>("/org/approvals?limit=1", { orgId: active.id })
        .then((r) => Object.values(r.pending_by_kind).reduce((a, b) => a + b, 0)).catch(() => 0)
    : 0;
  const showOnboarding = !!active && ["onboarding", "pending_setup"].includes(active.status) && (me.is_staff || can(role, "automation", "configure"));
  const navProps = { hasOrg: !!active, isStaff: me.is_staff, canAudit: me.is_staff || can(role, "audit", "read"), canTeam: !!role,
                     canConverse, canWork, showOnboarding, needsYou, canInvoices: me.is_staff || can(role, "invoice", "read"),
                     canBilling: me.is_staff || can(role, "billing", "read"), pages: features?.pages,
                     canConnect: me.is_staff || can(role, "connection", "manage"),
                     canCalendar: me.is_staff || can(role, "calendar", "read") };
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[260px_1fr]">
      <aside className="border-b border-line bg-card px-4 py-5 lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:border-r lg:border-b-0">
        <div className="flex items-center justify-between px-2">
          <Logo />
          <span className="flex items-center gap-2">{active && <Bell />}<span className="lg:hidden"><SignOut /></span></span>
        </div>
        <div className="mt-6">
          {active?.viewing_as_staff
            ? <ExitClientView name={active.name} />
            : <OrgSwitcher orgs={me.organizations} activeId={active?.id ?? null} />}
        </div>
        <div className="-mx-2 mt-6 hidden min-h-0 flex-1 overflow-y-auto px-2 pb-4 lg:block">
          <Nav {...navProps} />
        </div>
        <div className="hidden shrink-0 items-center gap-3 border-t border-line px-2 pt-4 lg:flex">
          <span className="grid h-9 w-9 place-items-center rounded-full border-2 border-ink font-semibold">{me.user.name.charAt(0)}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{me.user.name}</span>
            <span className="block truncate text-xs text-muted">{me.is_staff ? "Agentry staff" : me.user.email}</span>
          </span>
          <SignOut />
        </div>
      </aside>
      <div className="lg:hidden overflow-x-auto border-b border-line bg-card px-4 py-2">
        <Nav compact {...navProps} />
      </div>
      <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-8">{children}</main>
    </div>
  );
}
