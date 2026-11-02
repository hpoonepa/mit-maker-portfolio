import type { Metadata } from "next";

/**
 * Site constants for canonical URLs and shared metadata.
 * Keep these in sync with the production deployment.
 */
export const SITE_URL = "https://papercrane.bio";
export const SITE_NAME = "Paper Crane";
export const TWITTER_HANDLE = "@papercranebio";

/**
 * Build a canonical URL for a given path.
 * Always returns an absolute URL with no trailing slash (except root).
 */
export function canonicalUrl(path: string = "/"): string {
  if (!path.startsWith("/")) path = `/${path}`;
  if (path === "/") return `${SITE_URL}/`;
  return `${SITE_URL}${path.replace(/\/$/, "")}`;
}

/**
 * Build the OG-image URL for a page.
 * Routes to /api/og?title=...&desc=... so previews are dynamic.
 */
export function ogImageUrl(title: string, desc?: string): string {
  const params = new URLSearchParams({ title });
  if (desc) params.set("desc", desc);
  return `/api/og?${params.toString()}`;
}

interface PageMetaInput {
  title: string;
  description: string;
  path: string;
  ogTitle?: string;
  ogDesc?: string;
  ogImage?: string;
  noindex?: boolean;
}

/**
 * Generate a complete `Metadata` object for a page.
 * Handles canonical URL, OG, Twitter card, and robots directives.
 */
export function pageMetadata(input: PageMetaInput): Metadata {
  const { title, description, path, ogTitle, ogDesc, ogImage, noindex } = input;
  const url = canonicalUrl(path);
  const image = ogImage ?? ogImageUrl(ogTitle ?? title, ogDesc ?? description);

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title: `${title} · ${SITE_NAME}`,
      description,
      url,
      siteName: SITE_NAME,
      type: "website",
      locale: "en_US",
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} · ${SITE_NAME}`,
      description,
      creator: TWITTER_HANDLE,
      images: [image],
    },
    robots: noindex
      ? { index: false, follow: false }
      : { index: true, follow: true },
  };
}
