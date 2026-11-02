import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/metadata";

/**
 * Static list of blog posts. Replace with a dynamic loader once the blog
 * has its own data source (MDX directory, CMS, or DB).
 */
function listBlogSlugs(): { slug: string; lastModified: Date }[] {
  // Published field-notes posts. Add new entries here as posts ship.
  return [
    { slug: "launching-paper-crane", lastModified: new Date("2026-04-30") },
  ];
}

/**
 * Per-model benchmark detail pages are not published while the benchmark is
 * pre-registration-only: `/benchmark/[slug]` redirects to `/benchmark`, so
 * those URLs are deliberately kept out of the sitemap. Repopulate this list
 * when the first reproducible run set ships.
 */
function listBenchmarkSlugs(): string[] {
  return [];
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "weekly", priority: 1.0 },
    { url: `${SITE_URL}/pricing`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${SITE_URL}/benchmark`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${SITE_URL}/benchmark/methodology`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${SITE_URL}/beta`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${SITE_URL}/faq`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${SITE_URL}/about`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${SITE_URL}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE_URL}/docs`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/docs/getting-started`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/docs/api`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/docs/cli`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/contact`, lastModified: now, changeFrequency: "yearly", priority: 0.5 },
    { url: `${SITE_URL}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${SITE_URL}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
  ];

  const benchmarkRoutes: MetadataRoute.Sitemap = listBenchmarkSlugs().map((slug) => ({
    url: `${SITE_URL}/benchmark/${slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  const blogRoutes: MetadataRoute.Sitemap = listBlogSlugs().map((post) => ({
    url: `${SITE_URL}/blog/${post.slug}`,
    lastModified: post.lastModified,
    changeFrequency: "monthly",
    priority: 0.5,
  }));

  return [...staticRoutes, ...benchmarkRoutes, ...blogRoutes];
}
