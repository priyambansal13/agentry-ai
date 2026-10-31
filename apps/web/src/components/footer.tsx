import { Logo } from "@agentry/ui";

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-4 py-10 text-sm text-muted sm:flex-row sm:items-center sm:px-6">
        <Logo />
        <p>AI agents for the boring work your business hates. © {new Date().getFullYear()} Agentry</p>
        <nav className="flex gap-4" aria-label="Legal">
          <a href="/privacy" className="hover:text-ink">Privacy</a>
          <a href="/terms" className="hover:text-ink">Terms</a>
        </nav>
      </div>
    </footer>
  );
}
