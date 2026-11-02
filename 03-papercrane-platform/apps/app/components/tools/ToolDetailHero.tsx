import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { familyLabel } from "./CatalogChip";

/**
 * ToolDetailHero: top of the tool detail page.
 *
 * Family eyebrow → display title (Fraunces) → description prose →
 * primary CTA "Submit job with this tool". Mirrors the brief's editorial
 * voice: hairline rule, no shadow, no rounded SaaS chrome.
 */
type ToolDetailHeroProps = {
  name: string;
  version: string;
  category: string;
  description: string;
  ctaHref: string;
};

export function ToolDetailHero({
  name,
  version,
  category,
  description,
  ctaHref,
}: ToolDetailHeroProps) {
  return (
    <section className="space-y-8 pb-12">
      <div>
        <Link
          href="/app/tools"
          className="inline-flex items-center gap-2 font-sans text-[12px] text-graphite-soft transition-colors hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Catalog
        </Link>
      </div>

      <div className="flex flex-col gap-10 md:flex-row md:items-end md:justify-between">
        <div className="max-w-2xl">
          <p className="font-sans text-[12px] text-graphite-soft">
            {familyLabel(category)}
          </p>
          <h1 className="mt-3 font-display text-display-lg leading-[0.95] tracking-[-0.025em] text-ink">
            {name}
          </h1>
          <p className="mt-3 font-mono text-[12px] tracking-tight text-graphite-soft">
            v{version}
          </p>
          <p className="mt-6 font-sans text-[16px] leading-relaxed text-graphite">
            {description}
          </p>
        </div>

        <Link href={ctaHref} className="btn-primary shrink-0">
          Run {name}

        </Link>
      </div>
    </section>
  );
}
