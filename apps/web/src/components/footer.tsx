import { Logo } from "@agentry/ui";
import Link from "next/link";
import { audiences, groups, inGroup } from "@/lib/catalog";

export function Footer() {
  return (
    <footer className="border-t-2 border-ink bg-card">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.2fr_repeat(3,1fr)]">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-sm text-muted">AI agents for the boring work your business hates. Built, set up and run for you.</p>
          </div>
          <nav aria-label="Industries">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">For</h2>
            <ul className="mt-3 space-y-2 text-sm">{audiences.map((a) => <li key={a.slug}><Link href={`/for/${a.slug}`} className="hover:underline">{a.name}</Link></li>)}</ul>
          </nav>
          <nav aria-label="Agent groups">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Agents</h2>
            <ul className="mt-3 space-y-2 text-sm">
              <li><Link href="/agents" className="hover:underline">All agents</Link></li>
              {groups.map((g) => <li key={g.key}><Link href={`/agents#group-${g.key}`} className="hover:underline">{g.name} ({inGroup(g.key).length})</Link></li>)}
            </ul>
          </nav>
          <nav aria-label="Company">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Agentry</h2>
            <ul className="mt-3 space-y-2 text-sm">
              <li><Link href="/#pricing" className="hover:underline">Pricing</Link></li>
              <li><Link href="/#calculator" className="hover:underline">What it&apos;s worth</Link></li>
              <li><Link href="/#demo" className="hover:underline">Free demo</Link></li>
              <li><Link href="/privacy" className="hover:underline">Privacy</Link></li>
              <li><Link href="/terms" className="hover:underline">Terms</Link></li>
            </ul>
          </nav>
        </div>
        <p className="mt-12 border-t border-line pt-6 text-sm text-muted">© {new Date().getFullYear()} Agentry · Made in India for businesses everywhere</p>
      </div>
    </footer>
  );
}
