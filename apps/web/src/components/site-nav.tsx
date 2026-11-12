import { buttonClasses, Logo } from "@agentry/ui";
import Link from "next/link";

const DASHBOARD = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://localhost:3201";

export function SiteNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-line/70 bg-paper/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Agentry home"><Logo /></Link>
        <nav className="hidden items-center gap-7 text-sm text-ink-soft md:flex" aria-label="Main">
          <Link href="/audit" className="font-semibold text-ink hover:underline">Free audit</Link>
          <Link href="/try" className="hover:text-ink">Try it</Link>
          <Link href="/agents" className="hover:text-ink">Agents</Link>
          <Link href="/for/ca-firms" className="hover:text-ink">CA firms</Link>
          <Link href="/for/clinics" className="hover:text-ink">Clinics</Link>
          <Link href="/#for-you" className="hover:text-ink">Industries</Link>
          <Link href="/start" className="hover:text-ink">Pricing</Link>
        </nav>
        <div className="flex items-center gap-2">
          <a href={`${DASHBOARD}/sign-in`} className="hidden text-sm font-medium text-ink-soft hover:text-ink sm:inline">Client login</a>
          <a href="#demo" className={buttonClasses("primary", "sm")}>Get my demo</a>
        </div>
      </div>
    </header>
  );
}
