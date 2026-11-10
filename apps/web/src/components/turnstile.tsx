"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
type TS = { render: (el: HTMLElement, o: Record<string, unknown>) => string; reset: (id?: string) => void };
const ts = () => (window as Window & { turnstile?: TS }).turnstile;

/** Cloudflare Turnstile (the human check on public forms). Off when NEXT_PUBLIC_TURNSTILE_SITE_KEY isn't set. */
export function useTurnstile(dark = false) {
  const box = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const render = useCallback(() => {
    const t = ts();
    if (!SITE_KEY || !t || !box.current || widget.current) return;
    widget.current = t.render(box.current, { sitekey: SITE_KEY, theme: dark ? "dark" : "light", callback: (v: string) => setToken(v),
      "expired-callback": () => setToken(null), "error-callback": () => setToken(null) });
  }, [dark]);
  useEffect(render);
  const reset = () => { const t = ts(); if (widget.current && t) { t.reset(widget.current); setToken(null); } };
  const script = SITE_KEY ? <Script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" strategy="afterInteractive" onLoad={render} /> : null;
  return { enabled: !!SITE_KEY, token, reset, box, script };
}
