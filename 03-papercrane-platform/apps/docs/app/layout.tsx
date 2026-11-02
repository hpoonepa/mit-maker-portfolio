import type { Metadata } from "next";
import { Fraunces, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import "./globals.css";

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

export const metadata: Metadata = {
  metadataBase: new URL("https://docs.papercrane.bio"),
  title: {
    default: "Paper Crane Docs",
    template: "%s · Paper Crane Docs",
  },
  description:
    "Documentation for the Paper Crane platform — tools, API, billing, and protein binder design workflows.",
  applicationName: "Paper Crane Docs",
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${instrument.variable} ${jetbrains.variable}`}
    >
      <body>
        <Topbar />
        <div className="mx-auto w-full max-w-[1480px] px-6 sm:px-8 lg:px-12">
          <div className="docs-grid">
            <aside className="sticky top-[64px] hidden h-[calc(100vh-64px)] overflow-y-auto border-r border-lattice md:block">
              <Sidebar />
            </aside>

            <main className="min-w-0 py-12">
              <article className="prose-paper max-w-[760px]">{children}</article>
            </main>

            <aside className="sticky top-[64px] hidden h-[calc(100vh-64px)] overflow-y-auto py-12 pl-6 xl:block">
              <div className="eyebrow mb-3 text-graphite">On this page</div>
              <p className="text-[13px] text-graphite-soft">
                Auto-generated TOC ships in v0.2. For now, scan headings via the left nav.
              </p>
              <div className="mt-8">
                <div className="eyebrow mb-3 text-graphite">Need help?</div>
                <ul className="flex flex-col gap-2 text-[13px] text-ink-soft">
                  <li>
                    <a className="hover:text-crane" href="mailto:hello@papercrane.bio">
                      hello@papercrane.bio
                    </a>
                  </li>
                  <li>
                    <a className="hover:text-crane" href="https://papercrane.bio/contact">
                      Book a call
                    </a>
                  </li>
                </ul>
              </div>
            </aside>
          </div>
        </div>
      </body>
    </html>
  );
}
