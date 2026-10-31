"use client";

import { cn } from "@agentry/ui";
import {
  Bell, BookOpen, Bot, Clapperboard, FileSignature, TrendingUp, Building2, CalendarDays, CreditCard, FileBarChart, Home, Inbox, Megaphone, MessagesSquare, Eye, Receipt, ReceiptText, Rocket, Star,
  ScrollText, Send, Settings, Sparkles, UserRoundSearch, Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type Item = { href: string; label: string; icon: React.ComponentType<{ className?: string }>; soon?: boolean; badge?: number };

const clientItems: Item[] = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/needs-you", label: "Needs you", icon: Inbox },
  { href: "/automations", label: "Automations", icon: Bot },
  { href: "/conversations", label: "Conversations", icon: MessagesSquare },
  { href: "/leads", label: "Leads", icon: UserRoundSearch },
  { href: "/invoices", label: "Invoices", icon: ReceiptText },
  { href: "/bookkeeping", label: "Bookkeeping", icon: Receipt },
  { href: "/reviews", label: "Reviews", icon: Star },
  { href: "/watch", label: "Competitor watch", icon: Eye },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/cold-email", label: "Cold email", icon: Send },
  { href: "/content", label: "Content", icon: Clapperboard },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/reports", label: "Reports", icon: FileBarChart },
  { href: "/team", label: "Team", icon: Users },
  { href: "/audit", label: "Audit log", icon: ScrollText },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings/connections", label: "Connections", icon: Settings },
  { href: "/settings/account", label: "Account & notifications", icon: Bell },
];

type NavProps = {
  isStaff: boolean; canAudit: boolean; canTeam: boolean; hasOrg: boolean; compact?: boolean;
  canConverse?: boolean; showOnboarding?: boolean; needsYou?: number; canInvoices?: boolean; canBilling?: boolean; canConnect?: boolean; canWork?: boolean; canCalendar?: boolean;
  pages?: string[]; // sections this client's automations bring (agentry/features.py)
};

const pageKey = (href: string) => (href === "/settings/connections" ? "connections" : href === "/settings/account" ? "notifications" : href.slice(1));

/** Sidebar navigation. `compact` = the phone layout: one horizontal row, only the sections that exist today. */
export function Nav({ isStaff, canAudit, canTeam, hasOrg, compact = false, canConverse = true, showOnboarding = false, needsYou = 0, canInvoices = true, canBilling = true, canConnect = true, canWork = canConverse, canCalendar = true, pages }: NavProps) {
  const pathname = usePathname();
  const base: Item[] = showOnboarding ? [{ href: "/onboarding", label: "Get live", icon: Rocket }, ...clientItems] : clientItems;
  const items = !hasOrg ? [] : base
    .filter((i) => !pages || i.href === "/onboarding" || pages.includes(pageKey(i.href)))
    .filter((i) => (i.href !== "/audit" || canAudit) && (i.href !== "/team" || canTeam))
    .filter((i) => canConverse || !["/leads", "/knowledge", "/cold-email", "/content", "/reviews"].includes(i.href))
    .filter((i) => canWork || !["/needs-you", "/conversations"].includes(i.href))
    .filter((i) => canConnect || i.href !== "/settings/connections")
    .filter((i) => canCalendar || i.href !== "/calendar")
    .filter((i) => canInvoices || !["/invoices", "/bookkeeping"].includes(i.href))
    .filter((i) => canBilling || i.href !== "/billing")
    .filter((i) => !(compact && i.soon))
    .map((i) => (i.href === "/needs-you" ? { ...i, badge: needsYou } : i));
  if (compact) {
    return (
      <nav className="flex w-max gap-1" aria-label="Main">
        {items.map((item) => <NavLink key={item.href} item={item} active={pathname.startsWith(item.href)} />)}
        {isStaff && <NavLink item={{ href: "/hq", label: "All clients", icon: Building2 }} active={pathname.startsWith("/hq")} />}
      </nav>
    );
  }
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {items.map((item) => <NavLink key={item.href} item={item} active={pathname.startsWith(item.href)} />)}
      {isStaff && (
        <>
          <div className={cn("mb-1 px-3 font-hand text-lg text-muted", hasOrg && "mt-5")}>Agentry HQ</div>
          <NavLink item={{ href: "/hq", label: "All clients", icon: Building2 }} active={pathname === "/hq" || /^\/hq\/(?!demos|proposal|billing)/.test(pathname)} />
          <NavLink item={{ href: "/hq/demos", label: "Demo Studio", icon: Sparkles }} active={pathname.startsWith("/hq/demos")} />
          <NavLink item={{ href: "/hq/proposal", label: "Proposal builder", icon: FileSignature }} active={pathname.startsWith("/hq/proposal")} />
          <NavLink item={{ href: "/hq/billing", label: "Revenue & margin", icon: TrendingUp }} active={pathname.startsWith("/hq/billing")} />
        </>
      )}
    </nav>
  );
}

function NavLink({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  const classes = cn(
    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
    active ? "bg-lime font-semibold text-lime-ink" : "text-ink-soft hover:bg-lime-soft",
    item.soon && "pointer-events-none text-muted",
  );
  if (item.soon) {
    return (
      <span className={classes} aria-disabled="true">
        <Icon className="h-4 w-4" />
        {item.label}
        <span className="ml-auto rounded-full border border-line px-1.5 text-[10px] uppercase tracking-wide">soon</span>
      </span>
    );
  }
  return (
    <Link href={item.href} className={classes} aria-current={active ? "page" : undefined}>
      <Icon className="h-4 w-4" />
      {item.label}
      {item.badge ? <span className="ml-auto rounded-full bg-ink px-2 text-xs font-semibold text-paper" aria-label={`${item.badge} waiting`}>{item.badge}</span> : null}
    </Link>
  );
}
