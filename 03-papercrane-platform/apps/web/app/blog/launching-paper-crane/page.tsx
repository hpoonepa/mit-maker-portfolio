import type { Metadata } from "next";
import Link from "next/link";
import { pageMetadata } from "@/lib/metadata";

const TITLE = "Paper Crane is now in beta.";
const DESCRIPTION =
  "A thousand folds for one wish. A thousand seeds for one binder. Notes from the launch of Paper Crane.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/blog/launching-paper-crane",
  ogTitle: "Paper Crane is now in beta.",
  ogDesc: "A thousand folds for one wish.",
});

export default function LaunchingPaperCranePost() {
  return (
    <main className="bg-paper text-ink min-h-screen">
      <article className="mx-auto max-w-2xl px-6 py-24 md:py-32">
        {/* Breadcrumb */}
        <div className="mb-12 font-mono text-xs uppercase tracking-[0.2em] text-ink/50">
          <Link href="/blog" className="hover:text-ink">
            ← Field Notes
          </Link>
        </div>

        {/* Title */}
        <h1 className="font-fraunces text-5xl md:text-6xl font-light leading-[1.05] tracking-tight">
          Paper Crane is now in beta.
        </h1>

        {/* Byline */}
        <div className="mt-8 font-mono text-xs uppercase tracking-[0.2em] text-ink/60">
          <span>Harsha Poonepalle</span>
          <span className="mx-2 text-ink/30">/</span>
          <span>2026-04-30</span>
        </div>

        <hr className="my-12 border-ink/10" />

        {/* Body */}
        <div className="font-fraunces text-lg md:text-xl leading-[1.7] text-ink/85 space-y-7">
          <p className="first-letter:font-fraunces first-letter:text-7xl first-letter:font-light first-letter:float-left first-letter:mr-3 first-letter:mt-2 first-letter:leading-[0.85]">
            We are opening Paper Crane to a small group of beta users today. It
            is a catalog of protein design tools — the same models you would run
            yourself if you had the time, the GPUs, and the patience to wire
            them together. We did the wiring. The patience is still on you.
          </p>

          <h2 className="font-fraunces text-3xl font-light pt-6 tracking-tight">
            The thesis
          </h2>

          <p>
            In Japan, <em className="italic">senbazuru</em> is the practice of
            folding one thousand origami cranes to grant a single wish. The
            folds are nearly identical. The wish is singular. The discipline is
            in the repetition.
          </p>

          <p>
            Protein binder design is the same shape of problem. You do not get
            one binder from one seed. You get a binder from a thousand seeds,
            filtered down to ten, validated down to one. The math is brutal and
            the math is the point. We named the company after the practice
            because we wanted the name to be honest about what the work
            actually is.
          </p>

          <h2 className="font-fraunces text-3xl font-light pt-6 tracking-tight">
            Why distribution matters
          </h2>

          <p>
            The models that matter — RFdiffusion, BindCraft, BoltzGen, Boltz-2,
            Chai, ProteinMPNN, ESM-2 — are open. The papers are public. The
            weights are downloadable. And yet most working scientists still
            cannot run them, because running them means owning a GPU cluster,
            speaking three flavors of CUDA, and reconciling a dozen
            incompatible Python environments.
          </p>

          <p>
            One company, Tamarind Bio, has done a respectable job stitching the
            models behind a UI. We respect the work. We disagree with the
            shape: a walled garden where the catalog is curated and the prices
            are quiet. Our bet is the opposite — an open catalog, posted
            prices, your own keys, your own compute, your own data. We make
            money on the orchestration. You keep the science.
          </p>

          <blockquote className="font-fraunces italic text-2xl md:text-3xl font-light leading-snug text-ink/90 border-l-2 border-crimson/40 pl-6 my-12">
            A thousand folds for one wish. A thousand seeds for one binder. The
            patience is the product.
          </blockquote>

          <h2 className="font-fraunces text-3xl font-light pt-6 tracking-tight">
            What is in the beta
          </h2>

          <p>
            Twelve tools, wired end to end: backbone generation, sequence
            design, structure validation, ranking, and quality control. Bring
            your own Modal account and we run jobs on your GPUs at cost — no
            markup on compute. A public benchmark, updated nightly, so you can
            see how each tool performs on standard targets before you spend a
            single GPU-hour. A typed CLI for the people who live in terminals.
            A REST API for the people who do not.
          </p>

          <p>
            There is no free tier and there is no enterprise tier. There is one
            flat seat price during beta. Everyone gets the same catalog.
          </p>

          <h2 className="font-fraunces text-3xl font-light pt-6 tracking-tight">
            What is coming
          </h2>

          <p>
            After beta we will add a pharma tier — audit logs, SSO, on-prem
            deployments, and the paperwork that regulated environments need.
            General availability is targeted for late summer. Between now and
            then we will keep adding tools as the field publishes them, and we
            will keep the benchmark honest.
          </p>

          <h2 className="font-fraunces text-3xl font-light pt-6 tracking-tight">
            How to join
          </h2>

          <p>
            Beta is invite-only and small on purpose. If you have a target you
            are working on and you want a partner who will not lock you into
            their stack, request access on the{" "}
            <Link
              href="/pricing"
              className="underline decoration-crimson/40 underline-offset-4 hover:decoration-crimson"
            >
              pricing page
            </Link>
            . We read every request.
          </p>

          <p className="pt-6 text-ink/60">
            Fold carefully. We will see you in the catalog.
          </p>
        </div>

        <hr className="my-16 border-ink/10" />

        {/* Sign-off */}
        <div className="font-mono text-xs uppercase tracking-[0.2em] text-ink/50 flex items-center justify-between">
          <Link href="/blog" className="hover:text-ink">
            ← All field notes
          </Link>
          <Link href="/pricing" className="hover:text-ink">
            Request access →
          </Link>
        </div>
      </article>
    </main>
  );
}
