import type { ReactNode } from "react";
import { cn } from "../cn";

export interface StatProps {
  label: string;
  value: string;
  delta?: number | null; // fraction vs previous period, e.g. 0.18 = +18%
  deltaLabel?: string; // the named comparison period, e.g. "vs previous 30 days"
  higherIsBetter?: boolean;
  trend?: ReactNode; // optional sparkline
  className?: string;
}

/** Stat tile: label · value (sans semibold, proportional figures) · signed delta vs a named period · trend. */
export function Stat({ label, value, delta, deltaLabel, higherIsBetter = true, trend, className }: StatProps) {
  const good = delta == null ? null : higherIsBetter ? delta >= 0 : delta <= 0;
  return (
    <div className={cn("flex flex-col rounded-2xl border border-line bg-card p-5 shadow-card", className)}>
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-2 font-sans text-3xl font-semibold tracking-tight text-ink">{value}</div>
      <div className="mt-1.5 flex min-h-4 items-center gap-1.5 text-xs">
        {delta != null ? (
          <>
            <span className={cn("font-semibold", good ? "text-success" : "text-danger")}>
              <span aria-hidden="true">{delta >= 0 ? "▲" : "▼"}</span> {delta >= 0 ? "+" : "−"}
              {Math.abs(delta * 100).toFixed(0)}%
            </span>
            {deltaLabel && <span className="text-muted">{deltaLabel}</span>}
          </>
        ) : (
          deltaLabel && <span className="text-muted">no previous data</span>
        )}
      </div>
      {trend && <div className="mt-3">{trend}</div>}
    </div>
  );
}
