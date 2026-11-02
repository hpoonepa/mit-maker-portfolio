"use client";

import Link from "next/link";
import { ArrowRight, Dna, Shapes, ScanLine } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { MolecularDynamicsWaitlist } from "@/components/dashboard/MolecularDynamicsWaitlist";
import { ProjectsCarousel } from "@/components/dashboard/ProjectsCarousel";
import { toolLabel } from "@/lib/results/metrics";

const STARTERS = [
  { tool: "boltz2", name: "Boltz-2", title: "Predict a structure", icon: ScanLine },
  { tool: "bindcraft", name: "BindCraft", title: "Design a binder", icon: Shapes },
  { tool: "proteinmpnn", name: "ProteinMPNN", title: "Design a sequence", icon: Dna },
];

export default function DashboardPage() {
  const usage = trpc.usage.getCurrentPeriodUsage.useQuery(undefined, {staleTime: 30_000});
  const projects = trpc.dashboard.getTopProjects.useQuery({limit: 4});
  const jobs = trpc.jobs.list.useQuery({limit: 4});
  return (
    <div className="space-y-14 pb-6">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-display-md text-ink">Start a job</h1>
        </div>
        <Link href="/app/tools" className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm text-paper hover:bg-crane">All tools <ArrowRight className="h-4 w-4" /></Link>
      </header>

      <section aria-label="Choose a job" className="grid gap-x-12 gap-y-8 md:grid-cols-3">
        {STARTERS.map(({tool, name, title, icon: Icon}) => (
          <Link key={tool} href={`/app/jobs/new?tool=${tool}`} className="group py-3">
            <Icon strokeWidth={1.25} className="mb-6 h-8 w-8 text-crane" />
            <h2 className="mt-2 text-[26px] leading-tight tracking-[-0.025em] text-ink group-hover:text-crane">{title}</h2>
            <p className="mt-3 text-sm text-graphite">{name}</p>
          </Link>
        ))}
      </section>

      <MolecularDynamicsWaitlist />

      {jobs.data && jobs.data.items.length > 0 && <section aria-labelledby="recent-jobs-heading">
        <div className="mb-5 flex items-center justify-between gap-4"><h2 id="recent-jobs-heading" className="text-xl text-ink">Recent jobs</h2><Link href="/app/jobs" className="text-sm text-crane">All jobs →</Link></div>
        <div className="grid gap-x-12 gap-y-5 sm:grid-cols-2">
          {jobs.data.items.map(job => <Link key={job.id} href={`/app/jobs/${job.id}`} className="flex items-center justify-between gap-4 py-2 text-sm hover:text-crane"><div><p className="text-ink">{toolLabel(job.toolId)}</p><p className="mt-1 text-xs text-graphite">{job.id.slice(0, 8)}</p></div><span className="capitalize text-graphite">{job.status === "succeeded" ? "Complete" : job.status}</span></Link>)}
        </div>
      </section>}

      {projects.data && projects.data.items.length > 0 && <ProjectsCarousel items={projects.data.items} />}

      <section aria-labelledby="overview-usage" className="flex flex-wrap items-center justify-between gap-4 pt-2 text-sm">
        <div><h2 id="overview-usage" className="text-graphite">Usage this month</h2><p className="mt-2 text-ink">{usage.data ? `${usage.data.seedsConsumed.toLocaleString()} / ${usage.data.seedsIncluded.toLocaleString()} seeds` : usage.isLoading ? "Loading usage…" : "Usage unavailable"}</p></div>
        <Link href="/app/usage" className="text-graphite hover:text-ink">View usage & limits →</Link>
      </section>
    </div>
  );
}
