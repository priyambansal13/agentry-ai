import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/catalog";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/demo/", "/proposal/", "/unsubscribe/"] }, // private, per-prospect pages
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
