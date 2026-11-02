import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/metadata";

/**
 * robots.txt for the Paper Crane landing site.
 * Allows the public marketing pages and disallows OG image generation,
 * sign-in/sign-up gates, and any future admin surfaces.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/"],
        disallow: ["/api/", "/signup", "/login", "/admin"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
