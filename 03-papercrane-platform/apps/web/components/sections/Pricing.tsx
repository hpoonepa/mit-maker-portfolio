"use client";

import { Reveal } from "../Reveal";
import { cn } from "@/lib/utils";
import { getAppUrl } from "@/lib/links";
import { Check } from "lucide-react";

function buildTiers(appUrl: string) {
  return [
    {
      name: "Free",
      price: "$0",
      cadence: "forever",
      for: "iGEM teams · students · academics",
      cta: "Start free",
      href: `${appUrl}/app`,
      features: [
        "Every open-source tool",
        "Bring your own compute",
        "Public leaderboard access",
        "Community support",
        "7-day data retention",
      ],
      accent: false,
    },
    {
      name: "Pro",
      price: "$299",
      cadence: "/ month",
      for: "Labs · core facilities · biotech",
      cta: "Start 14-day trial",
      href: `${appUrl}/app`,
      features: [
        "Managed GPU, metered",
        "50,000 seeds / month",
        "Private campaigns",
        "Priority queue",
        "Email support · 24h",
        "90-day retention",
      ],
      accent: true,
    },
    {
      name: "Frontier",
      price: "$50K+",
      cadence: "/ year",
      for: "Pharma · Series B+ biotech",
      cta: "Talk to us",
      href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20frontier%20deployment",
      features: [
        "Closed frontier models",
        "Dedicated cluster",
        "VPC or on-prem deploy",
        "Custom tool integration",
        "Shared Slack · 1h SLA",
        "SOC 2 · HIPAA eligible",
      ],
      accent: false,
    },
  ];
}

export function Pricing() {
  const tiers = buildTiers(getAppUrl());
  return (
    <section id="pricing" className="py-section bg-paper-fold relative overflow-hidden">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 05 — Pricing</span>
            <span className="h-px flex-1 bg-lattice" />
          </div>
        </Reveal>

        <div className="grid md:grid-cols-2 gap-10 items-end mb-20">
          <Reveal delay={1}>
            <h2 className="font-display text-display-lg balance leading-[0.95]">
              Three folds.{" "}
              <em className="italic font-normal text-graphite">No surprises.</em>
            </h2>
          </Reveal>
          <Reveal delay={2}>
            <p className="text-[17px] leading-[1.5] text-graphite font-sans max-w-md">
              Free tier is free, forever. Pro is a flat subscription plus
              metered compute. Frontier is annual, invoiced, with a named
              account lead. That&rsquo;s it.
            </p>
          </Reveal>
        </div>

        <div className="grid md:grid-cols-3 gap-5 md:gap-6">
          {tiers.map((t, i) => (
            <Reveal key={t.name} delay={(i + 1) as 1 | 2 | 3}>
              <div
                className={cn(
                  "relative rounded-sm p-8 md:p-10 h-full transition-all duration-500",
                  t.accent
                    ? "bg-ink text-paper shadow-[0_24px_80px_-24px_rgba(20,17,13,0.35)] md:-translate-y-4"
                    : "bg-paper border border-lattice-strong hover:border-ink/40"
                )}
              >
                {t.accent && (
                  <div className="absolute top-6 right-6 flex items-center gap-2">
                    <span className="crane-dot" />
                    <span className="font-mono text-[9px] tracking-[0.24em] uppercase">
                      Most chosen
                    </span>
                  </div>
                )}

                {/* Name */}
                <div
                  className={cn(
                    "font-mono text-[10px] tracking-[0.24em] uppercase",
                    t.accent ? "text-paper/55" : "text-graphite"
                  )}
                >
                  {t.name}
                </div>

                {/* Price */}
                <div className="mt-8 flex items-baseline gap-2">
                  <span className="font-display text-[54px] md:text-[60px] leading-none tracking-tight">
                    {t.price}
                  </span>
                  <span
                    className={cn(
                      "font-sans text-[13px]",
                      t.accent ? "text-paper/60" : "text-graphite"
                    )}
                  >
                    {t.cadence}
                  </span>
                </div>

                {/* For */}
                <div
                  className={cn(
                    "mt-6 font-sans text-[14px] leading-[1.5]",
                    t.accent ? "text-paper/75" : "text-ink"
                  )}
                >
                  For {t.for}
                </div>

                <div
                  className={cn(
                    "my-8 h-px",
                    t.accent ? "bg-paper/12" : "bg-lattice"
                  )}
                />

                {/* Features */}
                <ul className="space-y-3 mb-10">
                  {t.features.map((f) => (
                    <li
                      key={f}
                      className={cn(
                        "flex items-start gap-3 text-[14px] font-sans",
                        t.accent ? "text-paper/85" : "text-ink-soft"
                      )}
                    >
                      <Check
                        className={cn(
                          "w-4 h-4 mt-[3px] shrink-0",
                          t.accent ? "text-crane" : "text-graphite"
                        )}
                        strokeWidth={2}
                      />
                      {f}
                    </li>
                  ))}
                </ul>

                <a
                  href={t.href}
                  className={cn(
                    "block text-center rounded-full py-3 font-sans text-[14px] tracking-tight transition-all",
                    t.accent
                      ? "bg-crane text-paper hover:bg-crane-deep"
                      : "border border-ink hover:bg-ink hover:text-paper"
                  )}
                >
                  {t.cta}
                </a>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
