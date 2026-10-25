import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Caveat, Inter } from "next/font/google";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display-family" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans-family" });
const hand = Caveat({ subsets: ["latin"], variable: "--font-hand-family" });

export const metadata: Metadata = {
  title: { default: "Agentry", template: "%s · Agentry" },
  description: "Your AI workforce, done for you.",
  appleWebApp: { capable: true, title: "Agentry", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#FAFAF7" }, { media: "(prefers-color-scheme: dark)", color: "#0E0F0C" }],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${hand.variable}`}>
      <body className="min-h-dvh font-sans">{children}</body>
    </html>
  );
}
