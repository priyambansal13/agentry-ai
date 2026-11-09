import type { MetadataRoute } from "next";
import { audiences, catalog, SITE_URL } from "@/lib/catalog";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: SITE_URL, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/agents`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    ...audiences.map((a) => ({ url: `${SITE_URL}/for/${a.slug}`, lastModified: now, changeFrequency: "monthly" as const, priority: 0.9 })),
    ...catalog.map((a) => ({ url: `${SITE_URL}/agents/${a.slug}`, lastModified: now, changeFrequency: "monthly" as const, priority: 0.7 })),
    { url: `${SITE_URL}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${SITE_URL}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];
}
