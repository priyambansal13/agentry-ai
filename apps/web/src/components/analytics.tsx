"use client";

import Script from "next/script";
import { useEffect } from "react";

/**
 * Ads and analytics, all optional: nothing loads unless its ID is set at build time.
 *   NEXT_PUBLIC_GA_ID               Google Analytics 4 (G-XXXX)
 *   NEXT_PUBLIC_GOOGLE_ADS_ID       Google Ads (AW-XXXX); NEXT_PUBLIC_GOOGLE_ADS_LABEL = the demo-request conversion label
 *   NEXT_PUBLIC_META_PIXEL_ID       Meta (Facebook / Instagram) Pixel
 * Ad click details (utm_*, gclid, fbclid) are kept for the visit and sent with the demo request (docs/ADS.md).
 */
const GA = process.env.NEXT_PUBLIC_GA_ID;
const ADS = process.env.NEXT_PUBLIC_GOOGLE_ADS_ID;
const ADS_LABEL = process.env.NEXT_PUBLIC_GOOGLE_ADS_LABEL;
const PIXEL = process.env.NEXT_PUBLIC_META_PIXEL_ID;
const KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"] as const;
const STORE = "agentry_attribution";

type Win = Window & { gtag?: (...a: unknown[]) => void; fbq?: (...a: unknown[]) => void };

/** Where this visitor came from: the first ad click of the visit plus the page they landed on. */
export function attribution(): Record<string, string> {
  try {
    return JSON.parse(sessionStorage.getItem(STORE) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

/** A demo request was sent: count it as a conversion everywhere that's set up. */
export function trackDemoRequest(niche?: string) {
  const w = window as Win;
  w.gtag?.("event", "generate_lead", { niche: niche ?? "unknown" });
  if (ADS && ADS_LABEL) w.gtag?.("event", "conversion", { send_to: `${ADS}/${ADS_LABEL}` });
  w.fbq?.("track", "Lead", { content_category: niche ?? "unknown" });
}

export function Analytics() {
  useEffect(() => {
    try {
      if (sessionStorage.getItem(STORE)) return;
      const q = new URLSearchParams(window.location.search);
      const found: Record<string, string> = {};
      for (const k of KEYS) {
        const v = q.get(k);
        if (v) found[k] = v.slice(0, 120);
      }
      found.landing = window.location.pathname;
      if (document.referrer && !document.referrer.startsWith(window.location.origin)) found.referrer = document.referrer.slice(0, 200);
      sessionStorage.setItem(STORE, JSON.stringify(found));
    } catch {
      // storage blocked (private mode): attribution is best effort
    }
  }, []);

  const gtagId = GA ?? ADS;
  return (
    <>
      {gtagId && (
        <>
          <Script src={`https://www.googletagmanager.com/gtag/js?id=${gtagId}`} strategy="afterInteractive" />
          <Script id="gtag-init" strategy="afterInteractive">
            {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());${GA ? `gtag('config','${GA}');` : ""}${ADS ? `gtag('config','${ADS}');` : ""}`}
          </Script>
        </>
      )}
      {PIXEL && (
        <Script id="meta-pixel" strategy="afterInteractive">
          {`!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','${PIXEL}');fbq('track','PageView');`}
        </Script>
      )}
    </>
  );
}
