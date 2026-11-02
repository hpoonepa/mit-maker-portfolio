import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Instrument Sans drives nav + body. We load 400/500/600 only.
const instrument = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument",
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

// JetBrains Mono is for Cmd+K hints + tabular run IDs. 500 is enough.
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  weight: ["400", "500"],
  display: "swap",
});

const SITE_URL = "https://app.papercrane.bio";
const DEFAULT_TITLE = "Paper Crane";
const DESCRIPTION =
  "Run protein design tools, manage jobs, and compare results.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: DEFAULT_TITLE,
    template: "%s · Paper Crane App",
  },
  description: DESCRIPTION,
  applicationName: "Paper Crane App",
  authors: [{ name: "Paper Crane", url: "https://papercrane.bio" }],
  creator: "Paper Crane",
  publisher: "Paper Crane",
  keywords: [
    "protein design",
    "binder design",
    "RFdiffusion",
    "BindCraft",
    "Boltz-2",
    "Chai-1",
    "AlphaFold",
    "dashboard",
    "computational biology",
  ],
  category: "science",
  openGraph: {
    title: DEFAULT_TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "Paper Crane",
    locale: "en_US",
    type: "website",
    // Dynamic OG from app/opengraph-image.tsx
  },
  twitter: {
    card: "summary_large_image",
    title: DEFAULT_TITLE,
    description: DESCRIPTION,
    creator: "@papercranebio",
  },
  robots: {
    // Keep the auth'd surface out of search indices. The public leaderboard
    // lives under /leaderboard but is still indexable (it sets its own
    // metadata); the authenticated dashboard should not be.
    index: false,
    follow: false,
  },
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${instrument.variable} ${jetbrains.variable}`}>
      <body>
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
