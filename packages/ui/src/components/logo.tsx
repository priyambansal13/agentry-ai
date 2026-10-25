import { cn } from "../cn";

/** Agentry wordmark: a hand-drawn "A" spark inside a lime blob, then the name. */
export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-display font-bold tracking-tight text-ink", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden="true">
        <path
          d="M5 17c-1-7 5-13 12-12.5 7 .6 11.5 6.4 10.5 13S20 28.5 14.5 27.5 6 23.5 5 17Z"
          fill="var(--lime)"
          stroke="var(--ink)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path
          d="M10.5 22.5 16 9.5l5.5 13M12.8 17.6h6.6"
          fill="none"
          stroke="var(--lime-ink)"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {!compact && <span className="text-xl">Agentry</span>}
    </span>
  );
}
