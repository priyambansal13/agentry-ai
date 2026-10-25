import { buttonClasses, Logo } from "@agentry/ui";

const DASHBOARD = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://localhost:3201";

export function SiteNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-line/70 bg-paper/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <a href="#top" aria-label="Agentry home"><Logo /></a>
        <nav className="hidden items-center gap-7 text-sm text-ink-soft md:flex" aria-label="Sections">
          <a href="#agents" className="hover:text-ink">Agents</a>
          <a href="#for-you" className="hover:text-ink">Who it&apos;s for</a>
          <a href="#calculator" className="hover:text-ink">What it&apos;s worth</a>
          <a href="#pricing" className="hover:text-ink">Pricing</a>
        </nav>
        <div className="flex items-center gap-2">
          <a href={`${DASHBOARD}/sign-in`} className="hidden text-sm font-medium text-ink-soft hover:text-ink sm:inline">Client login</a>
          <a href="#demo" className={buttonClasses("primary", "sm")}>Get my demo</a>
        </div>
      </div>
    </header>
  );
}
