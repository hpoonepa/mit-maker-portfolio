/**
 * Error detail page: `/app/error/[id]`.
 *
 * Toasts that surface a 5xx include a short reference id (e.g.
 * `err_lz3k8q01`). The user can click "View details" or paste the id
 * into a support ticket; this page is the canonical landing spot.
 *
 * It is intentionally a Server Component with zero data dependencies -
 * even when tRPC is on fire, this page must render. Real trace data
 * lives server-side in our log aggregator; this UI just confirms the
 * id and gives the user something to copy.
 *
 * Brand: quiet origami fold layout: single column, Fraunces page-mark,
 * one prominent recovery CTA, support contact as a quiet text link.
 */

import Link from "next/link";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ErrorDetailPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main
      role="main"
      className="min-h-screen bg-paper text-ink px-6 py-24 sm:py-32"
    >
      <div className="mx-auto w-full max-w-[34rem]">
        <div aria-hidden="true" className="h-px w-12 bg-crane" />
        <p className="mt-8 font-mono text-[11px] uppercase tracking-[0.18em] text-graphite-soft">
          Error · 500
        </p>
        <p
          aria-hidden="true"
          className="mt-6 font-display text-[clamp(96px,18vw,168px)] leading-[0.9] tracking-[-0.04em] text-ink"
        >
          500
        </p>
        <h1 className="mt-8 font-display text-display-md leading-tight text-ink">
          Something went wrong on our end.
        </h1>
        <p className="mt-4 font-sans text-[15px] leading-relaxed text-graphite">
          We&apos;ve been notified and are looking into it. If you&apos;d like
          to follow up, share the reference id below with support.
        </p>

        <div className="mt-10 rounded-lg border border-lattice bg-paper-fold/40 p-5">
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-graphite-soft">
            Reference id
          </span>
          <code
            className="mt-2 block break-all font-mono text-[15px] text-ink"
            aria-label={`Error reference ${id}`}
          >
            {id}
          </code>
        </div>

        <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link href="/dashboard" className="btn-primary">
            Back to dashboard
          </Link>
          <a
            href={`mailto:support@papercrane.bio?subject=${encodeURIComponent(`Error ${id}`)}`}
            className="font-sans text-[14px] text-graphite underline-offset-4 hover:text-ink hover:underline"
          >
            Contact support
          </a>
        </div>
      </div>
    </main>
  );
}
