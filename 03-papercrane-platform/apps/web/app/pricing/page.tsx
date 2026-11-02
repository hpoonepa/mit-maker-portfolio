import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Pricing } from "@/components/sections/Pricing";
import { Footer } from "@/components/sections/Footer";
import { FAQ as GlobalFAQ } from "@/components/sections/FAQ";
import { PricingTable } from "@/components/PricingTable";
import { Reveal } from "@/components/Reveal";
import { getAppUrl } from "@/lib/links";
import { pageMetadata } from "@/lib/metadata";
import {
  breadcrumbJsonLd,
  jsonLdString,
  productJsonLd,
} from "@/lib/structured-data";

const TITLE = "Pricing";
const DESCRIPTION =
  "Free for iGEM teams and academics. $299/mo for labs. $50K+/yr for pharma. Flat subscription plus metered compute. No surprises.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/pricing",
  ogTitle: "Pricing",
  ogDesc: "Three folds. No surprises.",
});

const PRICING_TIERS = [
  { name: "Free", price: "0", description: "Free forever for iGEM teams and academics." },
  { name: "Pro", price: "299", description: "$299/mo flat for labs. Includes 50,000 designs/month." },
  { name: "Frontier", price: "50000", description: "Custom $50K+/yr for pharma. Dedicated support and on-prem options." },
];

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Pricing", path: "/pricing" },
];

export default function PricingPage() {
  const appUrl = getAppUrl();
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(productJsonLd(PRICING_TIERS)) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        {/* Page hero */}
        <section className="container-edge pb-12">
          <Reveal>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 mb-10">
              <span className="eyebrow">Pricing · effective 2026-04-29</span>
              <span className="h-px flex-1 min-w-[2rem] bg-lattice" />
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
                MONTHLY
              </span>
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">·</span>
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-ink">
                ANNUAL
              </span>
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
                −17%
              </span>
              <span className="h-px w-6 bg-lattice" />
              <a
                href="#compare"
                className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft hover:text-ink underline decoration-lattice-strong underline-offset-4"
              >
                Jump to compare ↓
              </a>
            </div>
          </Reveal>
          <div className="grid lg:grid-cols-12 gap-10 items-end">
            <Reveal delay={1} className="lg:col-span-8">
              <h1 className="font-display text-display-xl balance leading-[0.92]">
                Pricing that fits how science actually{" "}
                <em className="italic font-normal text-crane">runs.</em>
              </h1>
            </Reveal>
            <Reveal delay={2} className="lg:col-span-4">
              <p className="font-sans text-[17px] leading-[1.55] text-graphite max-w-md">
                Free for iGEM and academics, forever. Pro is a flat $299/mo
                plus pennies per seed. Frontier is annual, invoiced, with a
                named account lead. That&rsquo;s it.
              </p>
              <div className="mt-5 inline-flex items-center gap-2 border border-lattice-strong px-3 py-1.5 rounded-sm">
                <span className="crane-dot-pulse" aria-hidden />
                <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-ink">
                  Beta access · Free tier no-cost until 2026-06-01
                </span>
              </div>
            </Reveal>
          </div>
        </section>

        {/* Tier cards (reuses landing component) */}
        <Pricing />

        {/* Feature matrix */}
        <section id="compare" className="py-section scroll-mt-32">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">Feature matrix</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>
            <Reveal delay={1}>
              <h2 className="font-display text-display-md balance leading-[0.96] mb-12 max-w-3xl">
                Everything in one table.{" "}
                <em className="italic font-normal text-graphite">
                  No legal-team translation required.
                </em>
              </h2>
            </Reveal>
            <PricingTable />
            <Reveal delay={2}>
              <p className="mt-6 font-mono text-[10px] tracking-[0.18em] uppercase text-graphite-soft">
                * Source: docs/plans/05-billing-pricing.md §1
              </p>
            </Reveal>
          </div>
        </section>

        {/* CTA strip */}
        <section id="enterprise" className="py-section scroll-mt-32">
          <div className="container-edge">
            <Reveal>
              <div className="hairline-border rounded-sm bg-paper-fold px-8 py-14 md:px-14 md:py-16 grid lg:grid-cols-12 gap-8 items-center">
                <div className="lg:col-span-7">
                  <div className="eyebrow mb-3">Not sure which fold?</div>
                  <h3 className="font-display text-[40px] md:text-[48px] leading-[1.05] balance max-w-xl">
                    Start free.{" "}
                    <em className="italic font-normal text-graphite">
                      Upgrade when you outgrow it.
                    </em>
                  </h3>
                  <p className="mt-5 font-sans text-[15px] leading-[1.6] text-graphite max-w-lg">
                    Pharma teams: Frontier ships annual, invoiced, with a named account lead. Contracts start at $50K.
                  </p>
                  <ul className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 max-w-lg">
                    {[
                      "BAA · HIPAA-ready",
                      "99.9% SLA",
                      "SSO · SCIM",
                      "Audit retention 7y",
                      "Dedicated support",
                      "BYOC · on-prem",
                    ].map((b) => (
                      <li
                        key={b}
                        className="font-mono text-[10px] tracking-[0.18em] uppercase text-graphite flex items-baseline gap-2"
                      >
                        <span className="text-crane">·</span>
                        {b}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="lg:col-span-5 flex flex-col gap-3">
                  <a href={`${appUrl}/signup`} className="btn-primary justify-center">
                    Start free
                    <span className="crane-dot-pulse" />
                  </a>
                  <a href="#compare" className="btn-ghost justify-center">
                    Compare all plans
                  </a>
                  <a
                    href="mailto:sales@papercrane.bio?subject=Paper%20Crane%20Frontier%20deployment"
                    className="font-mono text-[11px] tracking-[0.18em] uppercase text-crane hover:text-ink text-center pt-1 underline decoration-crane/40 underline-offset-4"
                  >
                    Frontier · talk to sales →
                  </a>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* Pricing-focused FAQ */}
        <PricingFAQ />

        {/* Reuse global FAQ for general questions */}
        <GlobalFAQ />
      </main>
      <Footer />
    </>
  );
}

function PricingFAQ() {
  const items = [
    {
      q: "What does \"beta access\" mean during launch?",
      a: "Through 2026-06-01, every account runs on the Free tier with Pro-level seed quotas unlocked, no card required. We collect telemetry (with your opt-in) to harden the orchestrator before GA. Pro and Frontier billing only switch on after 2026-06-01, and existing beta accounts get their first month free at the published rate.",
    },
    {
      q: "How does seed metering work?",
      a: "A seed counts when the orchestrator emits seed.completed (success OR graceful failure). Crashes in the first 30s do not count. Idempotency keys deduplicate retries within 24h. Real-time enforcement, daily roll-up for billing.",
    },
    {
      q: "What happens if I exceed my Pro cap?",
      a: "Your dashboard meter turns yellow at 80%, red at 95%. You can either (a) buy a top-up pack — 10k seeds for $99, 50k for $399 — or (b) opt into overage at $0.012/seed, billed end of month. Default is block, not overage.",
    },
    {
      q: "Do you offer an annual discount?",
      a: "Yes. Pro annual is $2,990 (17% off, two months free). Frontier is annual-only by default, with quarterly available on request. Standard net-30, net-60 negotiable above $150K.",
    },
    {
      q: "What's the support response time?",
      a: "Free is community Discord, no SLA. Pro is email at hello@papercrane.bio with 24h response 9am-9pm PT M-F. Frontier is shared Slack with 1h response and an on-call rotation for P0 incidents.",
    },
    {
      q: "Can I bring my own GPUs?",
      a: "Free requires it — runs entirely on your hardware. Pro lets you mix managed and BYOC. Frontier is most often BYOC into pharma's existing A100 fleet, with a 0% markup; we just charge the platform fee.",
    },
  ];
  return (
    <section id="billing-faq" className="py-section scroll-mt-32">
      <div className="container-edge">
        <Reveal>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 mb-16">
            <span className="eyebrow">§ Pricing FAQ</span>
            <span className="h-px flex-1 min-w-[2rem] bg-lattice" />
            <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
              {items.length} questions
            </span>
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-16">
          <Reveal delay={1} className="lg:col-span-4">
            <h2 className="font-display text-display-md balance leading-[0.98]">
              Billing,{" "}
              <em className="italic font-normal text-graphite">specifically.</em>
            </h2>
          </Reveal>
          <dl className="lg:col-span-8">
            {items.map((item, i) => (
              <Reveal
                key={item.q}
                delay={((i % 4) + 1) as 1 | 2 | 3 | 4}
                className="border-b border-lattice-strong py-7"
              >
                <dt className="font-display text-[22px] md:text-[24px] leading-[1.18] tracking-tight pr-8 mb-3">
                  {item.q}
                </dt>
                <dd className="font-sans text-[16px] leading-[1.6] text-graphite max-w-2xl">
                  {item.a}
                </dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
