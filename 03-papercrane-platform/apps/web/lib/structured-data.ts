import { SITE_NAME, SITE_URL } from "./metadata";

/**
 * JSON-LD generators for Paper Crane.
 * Each function returns a plain object suitable for serializing into a
 * `<script type="application/ld+json">` tag. Keep schemas tight — only
 * include fields we can support without bloating each page.
 */

export function organizationJsonLd() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE_NAME,
    url: SITE_URL,
    logo: `${SITE_URL}/icon.svg`,
    description:
      "The workflow layer for computational protein design. Benchmark, run, and compare every binder design tool under one reproducible methodology.",
    foundingDate: "2026",
    sameAs: [
      "https://twitter.com/papercranebio",
      "https://github.com/papercrane-bio",
    ],
    contactPoint: [
      {
        "@type": "ContactPoint",
        email: "hello@papercrane.bio",
        contactType: "general",
        areaServed: "Worldwide",
      },
    ],
  };
}

export function websiteJsonLd() {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: SITE_URL,
    publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
    inLanguage: "en-US",
  };
}

interface Tier {
  name: string;
  price: string;
  priceCurrency?: string;
  description: string;
}

export function productJsonLd(tiers: Tier[]) {
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: `${SITE_NAME} Platform`,
    description:
      "Run RFdiffusion, BindCraft, Boltz-2, Chai-1 and more under one reproducible workflow. Bring-your-target binder design with public benchmark scoring.",
    brand: { "@type": "Brand", name: SITE_NAME },
    url: `${SITE_URL}/pricing`,
    offers: tiers.map((t) => ({
      "@type": "Offer",
      name: t.name,
      price: t.price,
      priceCurrency: t.priceCurrency ?? "USD",
      description: t.description,
      url: `${SITE_URL}/pricing`,
      availability: "https://schema.org/InStock",
    })),
  };
}

export function breadcrumbJsonLd(items: { name: string; path: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, idx) => ({
      "@type": "ListItem",
      position: idx + 1,
      name: item.name,
      item: `${SITE_URL}${item.path}`,
    })),
  };
}

interface Article {
  title: string;
  description: string;
  path: string;
  datePublished: string;
  dateModified?: string;
  author?: string;
}

export function articleJsonLd(article: Article) {
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.description,
    url: `${SITE_URL}${article.path}`,
    datePublished: article.datePublished,
    dateModified: article.dateModified ?? article.datePublished,
    author: {
      "@type": "Organization",
      name: article.author ?? SITE_NAME,
      url: SITE_URL,
    },
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
      logo: { "@type": "ImageObject", url: `${SITE_URL}/icon.svg` },
    },
  };
}

/**
 * Convenience: serialize JSON-LD safely for embedding in a script tag.
 * Escapes `<` to prevent breaking out of the script context.
 */
export function jsonLdString(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
