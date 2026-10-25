import type { ButtonHTMLAttributes } from "react";
import { cn } from "../cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-lime text-lime-ink border-ink hover:-translate-y-0.5 hover:shadow-[3px_3px_0_0_var(--ink)]",
  secondary: "bg-card text-ink border-ink hover:-translate-y-0.5 hover:shadow-[3px_3px_0_0_var(--ink)]",
  ghost: "bg-transparent text-ink border-transparent hover:bg-lime-soft",
  danger: "bg-danger text-white border-danger hover:opacity-90",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

export function buttonClasses(variant: Variant = "primary", size: Size = "md", className?: string) {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-xl border-2 font-semibold transition-all duration-150",
    "disabled:pointer-events-none disabled:opacity-50 whitespace-nowrap",
    variants[variant],
    sizes[size],
    className,
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({ variant, size, className, ...props }: ButtonProps) {
  return <button className={buttonClasses(variant, size, className)} {...props} />;
}
