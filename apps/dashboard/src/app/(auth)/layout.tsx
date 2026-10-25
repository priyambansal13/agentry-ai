import { Logo } from "@agentry/ui";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </div>
      <div className="relative hidden overflow-hidden border-l-2 border-ink bg-lime lg:flex lg:flex-col lg:justify-center lg:px-16">
        <p className="font-hand text-3xl text-lime-ink">while you were away…</p>
        <ul className="mt-6 space-y-4 font-display text-2xl font-semibold text-lime-ink">
          <li>☎ 31 calls answered, 9 after hours</li>
          <li>📅 12 appointments booked</li>
          <li>₹1.8L of overdue invoices recovered</li>
        </ul>
        <p className="mt-10 max-w-md text-lime-ink/80">Your AI workforce, done for you. Sign in to see what your agents did today.</p>
      </div>
    </div>
  );
}
