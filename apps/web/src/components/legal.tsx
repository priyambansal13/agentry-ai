import { Logo } from "@agentry/ui";
import Link from "next/link";
import { Footer } from "@/components/footer";

export const CONTACT = "pbansal.agentry@gmail.com";

/** Plain reading layout for the privacy policy and terms. */
export function LegalPage({ title, updated, children }: { title: string; updated: string; children: React.ReactNode }) {
  return (
    <>
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-6 sm:px-6">
        <Link href="/" aria-label="Agentry home"><Logo /></Link>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-16 sm:px-6">
        <h1 className="font-display text-4xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-muted">Last updated {updated}</p>
        <div className="mt-8 space-y-6 leading-relaxed text-ink-soft [&_h2]:mt-10 [&_h2]:font-display [&_h2]:text-xl [&_h2]:font-bold [&_h2]:text-ink [&_li]:ml-5 [&_li]:list-disc [&_a]:underline">
          {children}
        </div>
      </main>
      <Footer />
    </>
  );
}
