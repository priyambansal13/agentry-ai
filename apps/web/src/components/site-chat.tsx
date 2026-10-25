"use client";

import { useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";

/** Loads the chat widget with the given key, or Agentry's own site key when none is passed. */
export function SiteChat({ widgetKey, openAfter }: { widgetKey?: string; openAfter?: number }) {
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const key = widgetKey ?? (await fetch(`${API}/public/site-chat`).then((r) => (r.ok ? r.json() : null)).catch(() => null))?.widget_key;
      if (!key || cancelled || document.getElementById("agentry-widget-script")) return;
      const s = document.createElement("script");
      s.id = "agentry-widget-script";
      s.src = "/widget.js";
      s.async = true;
      s.dataset.key = key;
      s.dataset.api = API;
      if (openAfter) s.onload = () => setTimeout(() => (window as unknown as { AgentryChat?: { open(): void } }).AgentryChat?.open(), openAfter);
      document.body.appendChild(s);
    })();
    return () => { cancelled = true; };
  }, [widgetKey, openAfter]);
  return null;
}
