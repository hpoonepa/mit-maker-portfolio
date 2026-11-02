"use client";

/**
 * Gallery of pre-built starter projects the user can clone with one click.
 * Each clone fires a tRPC mutation (`projects.cloneSample`) that creates a
 * new project tied to the seeded target + default params for the matching
 * sample slug. On success we route the user into the new project.
 *
 * The sample list mirrors `packages/db/prisma/seed.ts` (sample projects
 * section). Keep slugs in sync.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Beaker, Microscope, Pill, Copy, Loader2 } from "lucide-react";
import { Card, CardBody, Badge, cn } from "@papercrane/ui";
// trpc is provided by apps/app/lib/trpc: type-checked at consumer site.
// We intentionally do not import the AppRouter type here to avoid a circular
// dep (this component is imported by dashboard pages that already mount tRPC).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const trpc: any;

export interface SampleProject {
  slug: string;
  title: string;
  pdbId: string;
  category: "GPCR binder" | "Antibody" | "Enzyme";
  blurb: string;
  icon: React.ReactNode;
  defaultTools: string[];
}

export const SAMPLE_PROJECTS: SampleProject[] = [
  {
    slug: "gpcr-binder-6x1a",
    title: "GPCR binder",
    pdbId: "6X1A",
    category: "GPCR binder",
    blurb:
      "Design a de novo binder against an orphan GPCR. Seeded with hotspots and a BindCraft → Boltz2 pipeline.",
    icon: <Microscope className="h-5 w-5" aria-hidden />,
    defaultTools: ["bindcraft", "boltz2"],
  },
  {
    slug: "antibody-1igt",
    title: "Antibody design",
    pdbId: "1IGT",
    category: "Antibody",
    blurb:
      "Optimize a CDR loop on a canonical IgG scaffold. RFdiffusion + ProteinMPNN + AlphaFold3 self-consistency.",
    icon: <Pill className="h-5 w-5" aria-hidden />,
    defaultTools: ["rfdiffusion", "proteinmpnn", "alphafold3"],
  },
  {
    slug: "enzyme-1crn",
    title: "Enzyme stabilization",
    pdbId: "1CRN",
    category: "Enzyme",
    blurb:
      "Stabilize crambin while preserving its hydrophobic core. SolubleMPNN + ESM2 PLL ranking.",
    icon: <Beaker className="h-5 w-5" aria-hidden />,
    defaultTools: ["solublempnn", "esm2"],
  },
];

export interface SampleProjectsProps {
  className?: string;
  /** Override mutation hook for tests. */
  onClone?: (slug: string) => Promise<{ projectId: string }>;
}

export function SampleProjects({ className, onClone }: SampleProjectsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function clone(slug: string) {
    setBusy(slug);
    setError(null);
    try {
      let result: { projectId: string };
      if (onClone) {
        result = await onClone(slug);
      } else if (
        typeof trpc !== "undefined" &&
        trpc?.projects?.cloneSample?.mutate
      ) {
        // Wired up in apps/app/lib/trpc: see Wave 12 router.
        result = await trpc.projects.cloneSample.mutate({ slug });
      } else {
        // Fallback: route to the new-project page with the sample preselected.
        router.push(`/projects/new?sample=${encodeURIComponent(slug)}`);
        return;
      }
      router.push(`/projects/${result.projectId}`);
    } catch (err) {
      setError((err as Error).message ?? "Could not clone sample");
      setBusy(null);
    }
  }

  return (
    <section
      aria-labelledby="samples-heading"
      className={cn("flex flex-col gap-4", className)}
    >
      <div className="flex flex-col gap-1">
        <h2
          id="samples-heading"
          className="font-display text-lg font-semibold tracking-tight text-ink"
        >
          Start with a sample
        </h2>
        <p className="text-sm text-graphite-soft">
          Choose a preset to create a project with its target and tools filled
          in.
        </p>
      </div>

      <ul className="grid grid-cols-1 gap-3 md:grid-cols-3" role="list">
        {SAMPLE_PROJECTS.map((s) => {
          const isBusy = busy === s.slug;
          return (
            <li key={s.slug}>
              <Card className="h-full">
                <CardBody className="flex h-full flex-col gap-3 p-5">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-crane/10 text-crane">
                      {s.icon}
                    </span>
                    <Badge variant="neutral" size="sm">
                      PDB {s.pdbId}
                    </Badge>
                  </div>
                  <div className="flex flex-col gap-1">
                    <h3 className="font-display text-base font-semibold tracking-tight text-ink">
                      {s.title}
                    </h3>
                    <p className="text-xs uppercase tracking-wider text-graphite-soft">
                      {s.category}
                    </p>
                  </div>
                  <p className="text-sm text-graphite-soft leading-relaxed">
                    {s.blurb}
                  </p>
                  <div className="mt-auto flex flex-wrap gap-1.5">
                    {s.defaultTools.map((t) => (
                      <Badge key={t} variant="neutral" size="sm">
                        {t}
                      </Badge>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => clone(s.slug)}
                    disabled={isBusy}
                    className="inline-flex items-center justify-center gap-2 rounded-md bg-paper-fold px-3 py-2 text-sm font-medium text-ink border border-lattice-strong hover:bg-paper-deep transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-50 disabled:pointer-events-none"
                  >
                    {isBusy ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden
                      />
                    ) : (
                      <Copy className="h-3.5 w-3.5" aria-hidden />
                    )}
                    {isBusy ? "Cloning…" : "Clone this project"}
                  </button>
                </CardBody>
              </Card>
            </li>
          );
        })}
      </ul>

      {error && (
        <p role="alert" className="text-sm text-crane-deep">
          {error}
        </p>
      )}
    </section>
  );
}
