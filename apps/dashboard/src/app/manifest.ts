import type { MetadataRoute } from "next";

/** Installable client portal: owners mostly check results on their phone (Add to Home Screen / Install app). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Agentry",
    short_name: "Agentry",
    description: "What your AI agents did today, what needs you, and the results.",
    id: "/home",
    start_url: "/home",
    scope: "/",
    display: "standalone",
    background_color: "#FAFAF7",
    theme_color: "#FAFAF7",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Needs you", url: "/needs-you", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
      { name: "Conversations", url: "/conversations", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
    ],
  };
}
