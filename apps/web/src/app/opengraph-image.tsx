import { ImageResponse } from "next/og";
import { catalog } from "@/lib/catalog";

export const alt = "Agentry: AI agents for your business, done for you";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The share card for every page (brand: ink on paper, lime highlighter). */
export default function OpengraphImage() {
  const names = ["WhatsApp assistant", "AI receptionist", "Invoice follow-up", "Inbox triage", "CA firm pack", "AI video studio"];
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: 72,
        background: "#fafaf7", color: "#111111", fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 64, height: 64, borderRadius: 32, background: "#c9f24b", border: "4px solid #111111", display: "flex",
            alignItems: "center", justifyContent: "center", fontSize: 38, fontWeight: 800 }}>A</div>
          <div style={{ fontSize: 44, fontWeight: 800 }}>Agentry</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 84, fontWeight: 800, lineHeight: 1.02, letterSpacing: -2 }}>Your AI workforce,</div>
          <div style={{ display: "flex" }}>
            <div style={{ fontSize: 84, fontWeight: 800, lineHeight: 1.1, letterSpacing: -2, background: "#c9f24b", padding: "0 16px" }}>done for you.</div>
          </div>
          <div style={{ marginTop: 28, fontSize: 32, color: "#2a2a27" }}>{`${catalog.length} AI agents for Indian businesses, built and run for you`}</div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {names.map((n) => (
            <div key={n} style={{ fontSize: 24, padding: "8px 18px", borderRadius: 999, border: "3px solid #111111", background: "#ffffff" }}>{n}</div>
          ))}
        </div>
      </div>
    ),
    size,
  );
}
