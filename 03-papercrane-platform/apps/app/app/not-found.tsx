import Link from "next/link";

/**
 * Global 404. Next renders this for any route that doesn't match a page,
 * including `notFound()` calls from RSC pages (e.g. project detail when
 * the id doesn't exist or doesn't belong to the caller's org).
 *
 * Brand: a quiet origami fold: single column, generous space, Fraunces
 * page-mark, calm copy, one prominent recovery CTA. Crane red is reserved
 * for the thin top rule, not the buttons.
 */
export default function NotFound() {
  return (
    <main
      role="main"
      className="min-h-screen bg-paper text-ink px-6 py-24 sm:py-32"
    >
      <div className="mx-auto w-full max-w-[34rem]">
        <div
          aria-hidden="true"
          className="h-px w-12 bg-crane"
        />
        <p className="mt-8 font-mono text-[11px] uppercase tracking-[0.18em] text-graphite-soft">
          Error · 404
        </p>
        <p
          aria-hidden="true"
          className="mt-6 font-display text-[clamp(96px,18vw,168px)] leading-[0.9] tracking-[-0.04em] text-ink"
        >
          404
        </p>
        <h1 className="mt-8 font-display text-display-md leading-tight text-ink">
          We folded the wrong page.
        </h1>
        <p className="mt-4 font-sans text-[15px] leading-relaxed text-graphite">
          This route doesn&apos;t exist, or it&apos;s been moved. Head back to
          the dashboard and we&apos;ll pick up where you left off.
        </p>
        <div className="mt-10">
          <Link
            href="/dashboard"
            className="btn-primary"
            aria-label="Back to dashboard"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
