import type { HTMLAttributes } from "react";
import { cn } from "../cn";

type Tone = "neutral" | "lime" | "success" | "warning" | "danger";
const tones: Record<Tone, string> = {
  neutral: "bg-paper text-muted border-line",
  lime: "bg-lime-soft text-ink border-lime",
  success: "bg-transparent text-success border-success/40",
  warning: "bg-transparent text-warning border-warning/40",
  danger: "bg-transparent text-danger border-danger/40",
};

export function Badge({ tone = "neutral", className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}
      {...props}
    />
  );
}
