import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Caveat, Inter } from "next/font/google";
import { Analytics } from "@/components/analytics";
import { JsonLd } from "@/components/json-ld";
import { SITE_NAME, SITE_URL } from "@/lib/catalog";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display-family", display: "swap" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans-family", display: "swap" });
const hand = Caveat({ subsets: ["latin"], variable: "--font-hand-family", display: "swap" });

const DESCRIPTION = "AI agents for Indian businesses: WhatsApp and website chat, an AI receptionist, invoice follow-up, inbox triage, "
  + "content, and a 13-agent pack for CA firms. Built, set up and run for you, live in about a week.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "Agentry: AI agents for your business, done for you", template: "%s · Agentry" },
  description: DESCRIPTION,
  applicationName: SITE_NAME,
  keywords: ["AI agents for business India", "WhatsApp AI assistant", "AI receptionist", "AI automation agency India",
    "invoice follow up automation", "CA firm automation", "AI chatbot for website"],
  alternates: { canonical: "/" },
  openGraph: { type: "website", siteName: SITE_NAME, url: "/", locale: "en_IN", title: "Agentry: AI agents for your business, done for you", description: DESCRIPTION },
  twitter: { card: "summary_large_image", title: "Agentry: AI agents for your business, done for you", description: DESCRIPTION },
  robots: { index: true, follow: true, googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 } },
  verification: { google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION || undefined },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#fafaf7" }, { media: "(prefers-color-scheme: dark)", color: "#0e0f0c" }],
};

const ORG = [
  { "@context": "https://schema.org", "@type": "Organization", name: SITE_NAME, url: SITE_URL, logo: `${SITE_URL}/icon.svg`,
    description: DESCRIPTION, areaServed: "IN" },
  { "@context": "https://schema.org", "@type": "WebSite", name: SITE_NAME, url: SITE_URL, inLanguage: "en-IN" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${display.variable} ${sans.variable} ${hand.variable}`}>
      <body className="font-sans">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-ink focus:px-4 focus:py-2 focus:text-paper">Skip to content</a>
        {children}
        <JsonLd data={ORG} />
        <Analytics />
      </body>
    </html>
  );
}
