import type { Metadata } from "next";
import { Bricolage_Grotesque, Caveat, Inter } from "next/font/google";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display-family" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans-family" });
const hand = Caveat({ subsets: ["latin"], variable: "--font-hand-family" });

export const metadata: Metadata = {
  title: "Agentry: your AI workforce, done for you",
  description: "AI agents that answer your calls, follow up every lead, chase invoices and fill your calendar. Built and run for you.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${hand.variable}`}>
      <body className="font-sans">{children}</body>
    </html>
  );
}
