import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { ArrowUpRight, FlaskConical, ShieldCheck } from "lucide-react";

export const dynamic = "force-dynamic";

/**
 * Public, read-only research report. The API contract intentionally omits raw
 * sequences, structures, artifacts, parameters, logs, and member data.
 * `projects.public` also verifies `isPublic` on every request, so revocation
 * takes effect without waiting for a page cache to expire.
 */

interface PublicProjectView {
  project: { name: string; description: string | null; updatedAt: string };
  org: { name: string };
  target: { name: string; pdbId: string | null } | null;
  summary: { completedJobs: number; designsGenerated: number };
  topCandidates: Array<{
    id: string;
    seed: number;
    rank: number | null;
    tool: string;
    provenance: string;
    length: number | null;
    metrics: {
      ipSAE: number | null;
      ipTM: number | null;
      pDockQ: number | null;
      interfaceResidues: number | null;
    };
    metaScore: {
      status: "scored" | "insufficient_metrics";
      score: number | null;
      coverage: number;
      version: string;
      evidenceType: "computational";
      experimental: true;
    };
  }>;
}

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production"
    ? "https://api.papercrane.bio"
    : "http://localhost:3001");

const loadPublicProject = cache(
  async (publicId: string): Promise<PublicProjectView | null> => {
    const input = encodeURIComponent(JSON.stringify({ json: { publicId } }));
    try {
      const response = await fetch(
        `${API_URL}/trpc/projects.public?input=${input}`,
        {
          cache: "no-store",
          headers: { accept: "application/json" },
          signal: AbortSignal.timeout(4_000),
        },
      );
      if (!response.ok) return null;
      const payload = (await response.json()) as {
        result?: { data?: { json?: PublicProjectView } | PublicProjectView };
      };
      const data: unknown = payload.result?.data;
      if (!data) return null;
      if (typeof data === "object" && "json" in data) {
        return (data as { json?: PublicProjectView }).json ?? null;
      }
      return data as PublicProjectView;
    } catch {
      return null;
    }
  },
);

export async function generateMetadata({
  params,
}: {
  params: Promise<{ publicId: string }>;
}): Promise<Metadata> {
  const { publicId } = await params;
  const data = await loadPublicProject(publicId);
  if (!data) {
    return { title: "Project not found", robots: { index: false, follow: false } };
  }
  return {
    title: `${data.project.name} · ${data.org.name}`,
    description:
      data.project.description ??
      `${data.project.name} — a public computational protein-design report on Paper Crane.`,
    alternates: { canonical: `/p/${publicId}` },
    robots: { index: false, follow: false },
  };
}

export default async function PublicProjectPage({
  params,
}: {
  params: Promise<{ publicId: string }>;
}) {
  const { publicId } = await params;
  const data = await loadPublicProject(publicId);
  if (!data) notFound();

  const { project, org, target, summary, topCandidates } = data;

  return (
    <main id="main-content" className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8 sm:py-16">
        <header className="relative overflow-hidden rounded-[2rem] border border-lattice bg-paper-fold/35 px-6 py-8 sm:px-10 sm:py-12">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_84%_4%,rgba(193,61,41,0.13),transparent_42%)]" />
          <div className="relative">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-crane-deep">
                Public computational report
              </p>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-graphite-soft">
                Updated {formatDate(project.updatedAt)}
              </p>
            </div>
            <h1 className="mt-7 max-w-3xl font-display text-[42px] leading-[0.98] tracking-[-0.025em] text-ink sm:text-[64px]">
              {project.name}
            </h1>
            <p className="mt-4 font-sans text-[14px] text-graphite">
              Prepared by <span className="font-medium text-ink">{org.name}</span> on Paper Crane
            </p>
            {project.description && (
              <p className="mt-7 max-w-2xl font-serif text-[18px] leading-[1.6] text-graphite sm:text-[20px]">
                {project.description}
              </p>
            )}
          </div>
        </header>

        <section aria-label="Campaign summary" className="mt-5 grid gap-3 sm:grid-cols-3">
          <SummaryCard label="Completed runs" value={summary.completedJobs} />
          <SummaryCard label="Designs generated" value={summary.designsGenerated} />
          <SummaryCard
            label="Candidates shown"
            value={topCandidates.length}
            detail="ranked by experimental meta-score"
          />
        </section>

        <div className="mt-12 grid gap-6 lg:grid-cols-[1fr_1.35fr]">
          <div className="space-y-6">
            <section className="rounded-3xl border border-lattice bg-paper p-6">
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-graphite-soft">
                Target
              </p>
              {target ? (
                <div className="mt-4">
                  <h2 className="font-display text-[28px] leading-tight text-ink">{target.name}</h2>
                  <p className="mt-2 font-mono text-[12px] uppercase tracking-[0.12em] text-graphite">
                    {target.pdbId ? `PDB ${target.pdbId}` : "Uploaded structure"}
                  </p>
                </div>
              ) : (
                <p className="mt-4 font-sans text-[14px] text-graphite-soft">
                  Target metadata was not published.
                </p>
              )}
            </section>

            <section className="rounded-3xl border border-crane/25 bg-crane-glow/45 p-6">
              <div className="flex items-start gap-3">
                <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-crane-deep" aria-hidden />
                <div>
                  <h2 className="font-display text-[20px] text-ink">Report scope</h2>
                  <p className="mt-2 font-sans text-[13px] leading-5 text-graphite">
                    These rankings use stored computational metrics to support candidate review. Binding, clinical suitability and experimental performance require orthogonal checks and wet-lab validation.
                  </p>
                </div>
              </div>
            </section>
          </div>

          <section className="overflow-hidden rounded-3xl border border-lattice bg-paper">
            <div className="flex items-end justify-between gap-4 border-b border-lattice px-6 py-5">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-crane-deep">
                  Computational shortlist
                </p>
                <h2 className="mt-1 font-display text-[25px] text-ink">Top candidates</h2>
              </div>
              <FlaskConical className="h-5 w-5 text-graphite-soft" aria-hidden />
            </div>

            {topCandidates.length === 0 ? (
              <div className="px-6 py-14 text-center">
                <p className="font-display text-[20px] text-ink">No scored candidates yet.</p>
                <p className="mt-2 font-sans text-[13px] text-graphite-soft">
                  This report will update when completed runs persist designs.
                </p>
              </div>
            ) : (
              <ol className="divide-y divide-lattice">
                {topCandidates.map((candidate, index) => (
                  <li key={candidate.id} className="px-5 py-5 sm:px-6">
                    <div className="flex items-start justify-between gap-5">
                      <div className="min-w-0">
                        <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-graphite-soft">
                          Candidate {String(index + 1).padStart(2, "0")} · seed {candidate.seed}
                        </p>
                        <p className="mt-1 truncate font-sans text-[14px] font-medium text-ink">
                          {candidate.tool}
                          {candidate.length ? ` · ${candidate.length} aa` : ""}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-display text-[25px] tabular-nums text-ink">
                          {formatScore(candidate.metaScore.score)}
                        </p>
                        <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-graphite-soft">
                          meta / 100
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-paper-fold">
                      <div
                        className="h-full rounded-full bg-crane-deep"
                        style={{ width: `${Math.round(candidate.metaScore.coverage * 100)}%` }}
                      />
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-4 font-mono text-[9px] uppercase tracking-[0.11em] text-graphite-soft">
                      <span>{Math.round(candidate.metaScore.coverage * 100)}% evidence coverage</span>
                      <span>{candidate.provenance} output</span>
                    </div>

                    <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-4">
                      <Metric label="ipSAE" value={candidate.metrics.ipSAE} />
                      <Metric label="ipTM" value={candidate.metrics.ipTM} />
                      <Metric label="pDockQ" value={candidate.metrics.pDockQ} />
                      <Metric label="Interface" value={candidate.metrics.interfaceResidues} integer />
                    </dl>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>

        <footer className="mt-16 flex flex-col gap-5 border-t border-lattice pt-8 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-display text-[20px] text-ink">Built with Paper Crane</p>
            <p className="mt-1 font-sans text-[13px] text-graphite-soft">
              Reproducible protein-design campaigns without stitching together GPU infrastructure.
            </p>
          </div>
          <Link
            href="https://app.papercrane.bio"
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-ink px-5 font-sans text-[13px] text-paper transition-colors hover:bg-graphite"
          >
            Explore Paper Crane
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </footer>
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail?: string;
}) {
  return (
    <div className="rounded-2xl border border-lattice bg-paper px-5 py-4">
      <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-graphite-soft">{label}</p>
      <p className="mt-1 font-display text-[28px] tabular-nums text-ink">{value}</p>
      {detail && <p className="mt-1 font-sans text-[11px] text-graphite-soft">{detail}</p>}
    </div>
  );
}

function Metric({
  label,
  value,
  integer = false,
}: {
  label: string;
  value: number | null;
  integer?: boolean;
}) {
  return (
    <div>
      <dt className="font-mono text-[9px] uppercase tracking-[0.12em] text-graphite-soft">{label}</dt>
      <dd className="mt-0.5 font-mono text-[12px] tabular-nums text-ink">
        {value == null ? "—" : integer ? Math.round(value) : value.toFixed(3)}
      </dd>
    </div>
  );
}

function formatScore(score: number | null): string {
  return score == null ? "—" : String(Math.round(score * 100));
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
