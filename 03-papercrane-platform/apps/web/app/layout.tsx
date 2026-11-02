import type { Metadata } from "next";
import { Fraunces, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { CookieBanner } from "@/components/legal/CookieBanner";
import { SITE_NAME, SITE_URL, TWITTER_HANDLE } from "@/lib/metadata";
import {
  jsonLdString,
  organizationJsonLd,
  websiteJsonLd,
} from "@/lib/structured-data";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  axes: ["SOFT", "opsz"],
  display: "swap",
});

const instrument = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

const TITLE = "Paper Crane — Every protein design tool. One workflow.";
const DESCRIPTION =
  "Benchmark, run, and compare protein binder design tools — RFdiffusion, BindCraft, Boltz-2, Chai-1, and more — under one reproducible methodology. YC S26.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s · Paper Crane",
  },
  description: DESCRIPTION,
  applicationName: SITE_NAME,
  authors: [{ name: SITE_NAME, url: SITE_URL }],
  creator: SITE_NAME,
  publisher: SITE_NAME,
  alternates: { canonical: `${SITE_URL}/` },
  keywords: [
    "protein design",
    "binder design",
    "RFdiffusion",
    "BindCraft",
    "Boltz-2",
    "Chai-1",
    "AlphaFold",
    "computational biology",
    "structural biology",
    "synthetic biology",
    "YC S26",
  ],
  category: "science",
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: SITE_NAME,
    locale: "en_US",
    type: "website",
    // Dynamic OG image is picked up automatically from app/opengraph-image.tsx
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    creator: TWITTER_HANDLE,
    // Dynamic Twitter image picked up from app/twitter-image.tsx
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  // Icons are supplied automatically by app/icon.tsx + app/apple-icon.tsx.
  // Keep the SVG fallback for legacy browsers / RSS readers.
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Analytics: env-gated. If NEXT_PUBLIC_PLAUSIBLE_DOMAIN is unset, no-op.
  // The actual <script> tag is intentionally not loaded here — wire through
  // a Plausible / Vercel Analytics component once the provider is finalized.
  const plausibleDomain = process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN;

  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${instrument.variable} ${jetbrains.variable}`}
    >
      <head>
        {/* Preconnect to external origins used on first paint or near it.
            Cuts ~100-300ms RTT on cold loads in the US/EU. */}
        <link rel="preconnect" href="https://files.rcsb.org" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://files.rcsb.org" />
        <link rel="preload" as="image" href="/crane-hero-poster.jpg" fetchPriority="high" />

        {/* Structured data — Organization + WebSite for the root layout.
            Page-level JSON-LD (Product, Article, Breadcrumb) is injected
            per-route. */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: jsonLdString(organizationJsonLd()),
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLdString(websiteJsonLd()) }}
        />

        {plausibleDomain ? (
          // Plausible analytics hook (env-gated). Real script loads once the
          // provider is wired; the meta tag lets server-side renderers see
          // the configured domain without a client-side dependency.
          <meta name="x-plausible-domain" content={plausibleDomain} />
        ) : null}
      </head>
      <body>
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        {children}
        <CookieBanner />
      </body>
    </html>
  );
}
