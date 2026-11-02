"use client";

/**
 * Animated hero copy block — headline, subhead, and three CTAs.
 *
 * Uses the existing `animate-fade-up` / `animate-fade-in` Tailwind utilities
 * (defined in `tailwind.config.ts`) so we don't pull `framer-motion` into the
 * landing bundle. The CTAs get a subtle "lift + crane-glow" hover via inline
 * Tailwind classes — no new global CSS needed.
 */
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { getAppUrl } from "@/lib/links";

export function HeroCopy() {
  const appUrl = getAppUrl();
  return (
    <div className="max-w-2xl">
      <Link
        href="/contact?beta=1"
        className="group mb-6 inline-flex items-center gap-3 font-mono text-[10.5px] uppercase tracking-[0.26em] text-graphite hover:text-ink transition-colors animate-fade-in"
        style={{ animationDelay: "0ms" }}
      >
        <span aria-hidden="true" className="inline-block h-px w-10 bg-ink/30 group-hover:bg-ink/60 transition-colors" />
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-crane" />
        <span>Now in beta &middot; Request access</span>
      </Link>
      <h1
        className="font-display text-display-xl balance leading-[0.95]"
        style={{ fontFeatureSettings: '"ss01", "ss02"' }}
      >
        <span
          className="block animate-fade-up"
          style={{ animationDelay: "60ms" }}
        >
          A thousand seeds.
        </span>
        <span
          className="block animate-fade-up"
          style={{ animationDelay: "200ms" }}
        >
          <em className="italic font-normal text-crane">One binder.</em>
        </span>
      </h1>

      <p
        className="mt-6 flex items-center gap-3 font-mono text-[11px] tracking-[0.22em] uppercase text-graphite animate-fade-in"
        style={{ animationDelay: "300ms" }}
      >
        <span aria-hidden="true" className="inline-block h-px w-8 bg-crane/70" />
        Senbazuru &mdash; fold a thousand, grant one wish.
      </p>

      <p
        className="mt-7 max-w-xl text-[18px] md:text-[20px] leading-[1.5] text-ink-soft font-sans animate-fade-up"
        style={{ animationDelay: "420ms" }}
      >
        <span className="text-ink font-medium">Twelve protein-design tools, one workflow.</span>{" "}
        Point at a target, route across RFdiffusion, BindCraft, Boltz-2 and the rest, and rank survivors under a single rubric.
      </p>

      <div
        className="mt-10 flex flex-wrap items-center gap-3 animate-fade-up"
        style={{ animationDelay: "500ms" }}
      >
        <Link
          href={`${appUrl}/signup`}
          className="btn-primary group"
        >
          Start free
          <ArrowUpRight
            className="w-4 h-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
            strokeWidth={1.8}
          />
        </Link>
        <Link
          href="/benchmark"
          className="btn-ghost"
        >
          See benchmark
        </Link>
        <Link
          href="/pricing"
          className="font-sans text-[14px] text-graphite hover:text-ink transition-colors underline-offset-4 hover:underline"
        >
          View pricing
        </Link>
        <Link
          href="/contact?beta=1"
          className="font-mono text-[11px] uppercase tracking-[0.22em] text-graphite hover:text-crane transition-colors underline-offset-[6px] decoration-ink/20 hover:decoration-crane hover:underline"
        >
          Request beta access
        </Link>
      </div>

      <div
        className="mt-8 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-graphite-soft animate-fade-in"
        style={{ animationDelay: "680ms" }}
      >
        <span className="crane-dot-pulse" />
        No credit card · Free tier · Cancel anytime
      </div>
    </div>
  );
}

export default HeroCopy;
