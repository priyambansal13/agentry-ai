"use client";

import { type InputHTMLAttributes, useState } from "react";
import { cn } from "../cn";
import { Input } from "./input";

/** A password field with an eye button to show or hide what was typed. */
export function PasswordInput({ className, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input type={shown ? "text" : "password"} className={cn("pr-11", className)} {...props} />
      <button type="button" onClick={() => setShown((s) => !s)} aria-label={shown ? "Hide password" : "Show password"} aria-pressed={shown}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-xl text-muted hover:text-ink focus-visible:text-ink focus-visible:outline-none">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
          <circle cx="12" cy="12" r="3" />
          {shown && <path d="M3 3l18 18" />}
        </svg>
      </button>
    </div>
  );
}
