import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "Contact";
const DESCRIPTION =
  "Get in touch with the Paper Crane team — partnerships, support, careers, or research collaboration.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/contact",
  ogTitle: "Contact",
  ogDesc: "Talk to us. hello@papercrane.bio",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Contact", path: "/contact" },
];

type ContactRoute = {
  label: string;
  email: string;
  description: string;
  sla: string;
};

const ROUTES: ContactRoute[] = [
  {
    label: "Partnerships & research",
    email: "hello@papercrane.bio",
    description:
      "Pilot programs, co-authored benchmarks, academic collaborations, and press.",
    sla: "Replies within 2 business days",
  },
  {
    label: "Product support",
    email: "support@papercrane.bio",
    description:
      "Bugs, billing, account issues, and questions about a specific run.",
    sla: "Replies within 1 business day",
  },
  {
    label: "Security & privacy",
    email: "security@papercrane.bio",
    description:
      "Vulnerability disclosure, data-deletion requests, and DPA inquiries.",
    sla: "Acknowledged within 24 hours",
  },
];

export default function ContactPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        <section className="container-edge pb-24">
          <Reveal>
            <div className="flex items-baseline gap-4 mb-10">
              <span className="eyebrow">§ Contact</span>
              <span className="hairline flex-1" />
            </div>
            <div className="flex flex-wrap items-end justify-between gap-6">
              <h1 className="font-display text-[clamp(40px,6vw,72px)] leading-[1.05] text-ink">
                Talk to us.
              </h1>
              <div
                className="inline-flex items-center gap-2 border border-ink/15 px-3 py-1.5 font-mono text-[11px] tracking-[0.22em] uppercase text-ink"
                aria-label="Currently staffed Monday through Friday Pacific time"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-crane-deep" aria-hidden />
                Staffed <time dateTime="Mon-Fri">Mon–Fri</time> · 09–18 PT
              </div>
            </div>
            <p className="mt-6 max-w-[60ch] text-graphite text-[17px] leading-relaxed">
              Three inboxes, three jobs. Pick the one that matches what you
              need and we&apos;ll route you to the right human.
            </p>
          </Reveal>

          <Reveal>
            <ul className="mt-14 grid gap-px bg-ink/10 border border-ink/10 md:grid-cols-3">
              {ROUTES.map((route) => {
                const slug = route.email.split("@")[0];
                return (
                <li
                  key={route.email}
                  id={`route-${slug}`}
                  className="bg-paper p-6 md:p-7 flex flex-col scroll-mt-32"
                >
                  <div className="font-mono text-[10px] tracking-[0.24em] uppercase text-graphite-soft">
                    {route.label}
                  </div>
                  <a
                    href={`mailto:${route.email}`}
                    className="mt-3 inline-block py-1 font-mono text-[14px] text-ink underline decoration-crane-deep/40 underline-offset-4 hover:decoration-crane-deep break-all"
                    aria-label={`Email ${route.label} at ${route.email}`}
                  >
                    {route.email}
                  </a>
                  <p className="mt-4 text-[14px] leading-relaxed text-graphite max-w-[40ch]">
                    {route.description}
                  </p>
                  <div className="mt-auto pt-5 text-[12px] text-graphite-soft">
                    {route.sla}
                  </div>
                </li>
                );
              })}
            </ul>
          </Reveal>

          <Reveal>
            <div className="mt-16 grid gap-10 md:grid-cols-[1fr_auto] md:items-end max-w-4xl">
              <div>
                <div className="font-mono text-[10px] tracking-[0.24em] uppercase text-graphite-soft">
                  Mailing address
                </div>
                <address className="mt-3 not-italic text-ink text-[15px] leading-relaxed">
                  Paper Crane, Inc.
                  <br />
                  2261 Market Street #4000
                  <br />
                  San Francisco, CA 94114
                </address>
              </div>
              <div className="text-[12px] font-mono tracking-[0.18em] uppercase text-graphite-soft md:text-right">
                Hours · Mon–Fri · 09:00–18:00 PT
              </div>
            </div>
          </Reveal>

          <Reveal>
            <p className="mt-16 text-sm text-graphite-soft">
              Prefer the dashboard?{" "}
              <Link
                href="/"
                className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
              >
                Back to home
              </Link>
              . For data-rights requests, see{" "}
              <Link
                href="/privacy-choices"
                className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
              >
                privacy choices
              </Link>
              .
            </p>
          </Reveal>
        </section>
      </main>
      <Footer />
    </>
  );
}
