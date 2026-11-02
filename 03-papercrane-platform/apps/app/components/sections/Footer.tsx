"use client";

import { getWebUrl } from "@/lib/links";

/**
 * Footer for publicly-reachable pages inside @papercrane/app (the leaderboard).
 * Mirrors the landing footer in apps/web, but any hash-anchor link routes
 * back to the landing deployment so scroll targets resolve.
 */
export function Footer() {
  const webUrl = getWebUrl();
  const cols = [
    {
      h: "Product",
      links: [
        { label: "Tools", href: `${webUrl}/#tools` },
        { label: "Benchmark", href: `${webUrl}/#benchmark` },
        { label: "Pricing", href: `${webUrl}/#pricing` },
        {
          label: "Changelog",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20changelog",
        },
        {
          label: "Status",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20status",
        },
      ],
    },
    {
      h: "Company",
      links: [
        { label: "About", href: `${webUrl}/#about` },
        {
          label: "Careers",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20careers",
        },
        {
          label: "Press",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20press",
        },
        {
          label: "Blog",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20blog",
        },
        { label: "The Fold · newsletter", href: `${webUrl}/#cta` },
      ],
    },
    {
      h: "Resources",
      links: [
        {
          label: "Docs",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20docs",
        },
        {
          label: "API",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20API",
        },
        { label: "Catalog repo", href: `${webUrl}/#tools` },
        {
          label: "Biosecurity policy",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20biosecurity%20policy",
        },
        { label: "Methodology", href: `${webUrl}/#benchmark` },
      ],
    },
    {
      h: "Legal",
      links: [
        {
          label: "Privacy",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20privacy",
        },
        {
          label: "Terms",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20terms",
        },
        {
          label: "Acceptable use",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20acceptable%20use",
        },
        {
          label: "Security",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20security",
        },
        {
          label: "Data handling",
          href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20data%20handling",
        },
      ],
    },
  ];

  return (
    <footer className="bg-paper-fold pt-24 pb-10 relative">
      <div className="container-edge">
        {/* Big wordmark */}
        <div className="flex items-end justify-between gap-8 mb-20 flex-wrap">
          <div>
            <div className="eyebrow mb-4">A thousand seeds. One binder.</div>
            <h3 className="font-display text-[clamp(4rem,12vw,10rem)] leading-[0.85] tracking-[-0.04em]">
              Paper Crane
              <span className="text-crane">.</span>
            </h3>
          </div>
          <div className="text-right">
            <div className="font-sans text-[12px] text-graphite">
              Est. 2026 · Atlanta → SF
            </div>
            <div className="mt-1 font-sans text-[12px] text-graphite-soft">
              Fold · Run · Rank · Repeat
            </div>
          </div>
        </div>

        <div className="fold-line opacity-40 mb-12" />

        {/* Link columns */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-10 mb-20">
          {cols.map((c) => (
            <div key={c.h}>
              <div className="font-sans text-[12px] text-graphite mb-5">
                {c.h}
                </div>
                <ul className="space-y-3">
                  {c.links.map((l) => (
                    <li key={l.label}>
                      <a
                        href={l.href}
                        className="font-sans text-[14px] text-ink-soft hover:text-crane transition-colors"
                      >
                        {l.label}
                      </a>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="fold-line opacity-40 mb-8" />

        {/* Bottom meta row */}
        <div className="flex flex-wrap items-center justify-between gap-4 font-sans text-[12px] text-graphite-soft">
          <div className="flex items-center gap-3">
            <span className="crane-dot opacity-60" />
            <span>© 2026 Paper Crane, Inc. · All rights folded.</span>
          </div>
          <div className="flex gap-5">
            <a
              href="mailto:hello@papercrane.bio?subject=Paper%20Crane"
              className="hover:text-ink transition-colors"
            >
              Email
            </a>
            <a
              href={`${webUrl}/#benchmark`}
              className="hover:text-ink transition-colors"
            >
              Benchmark
            </a>
            <a
              href={`${webUrl}/#pricing`}
              className="hover:text-ink transition-colors"
            >
              Pricing
            </a>
            <a
              href={`${webUrl}/#faq`}
              className="hover:text-ink transition-colors"
            >
              FAQ
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
