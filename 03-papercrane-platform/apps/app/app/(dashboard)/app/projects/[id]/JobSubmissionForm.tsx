"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { toolInputSpec } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { isValidPdbId } from "@/components/jobs/ComplexInputStep";
import {
  EXAMPLE_JOB,
  exampleHotspotLabel,
  exampleSubmission,
} from "@/lib/jobs/exampleJob";
import { friendlySubmitError } from "@/lib/jobs/submitErrors";

/** Format a USD dollar amount with two decimal places (no rounding tricks). */
function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}

export function JobSubmissionForm({ projectId }: { projectId: string }) {
  const router = useRouter();
  const tools = trpc.tools.list.useQuery({});
  const targets = trpc.targets.list.useQuery({ limit: 50 });
  const submit = trpc.jobs.submit.useMutation({
    onSuccess: (job) => {
      router.push(`/app/jobs/${job.id}`);
      router.refresh();
    },
  });

  // This compact form only collects a target PDB, so show runnable target-input
  // tools. The full wizard handles sequence, backbone, and complex inputs.
  const runnableTools = (tools.data?.items ?? []).filter(
    (tool) =>
      tool.runnable &&
      tool.tier !== "frontier" &&
      toolInputSpec(tool.toolId).inputKind === "target",
  );
  const firstToolId = runnableTools[0]?.toolId ?? "";
  const [toolId, setToolId] = useState("");
  const [targetPdb, setTargetPdb] = useState("");
  const [numDesigns, setNumDesigns] = useState(8);
  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [ranExample, setRanExample] = useState(false);

  const selectedToolId = toolId || firstToolId;
  const selectedToolName =
    runnableTools.find((t) => t.toolId === selectedToolId)?.name ??
    selectedToolId;

  // Friendly, specific input validation: never a raw server rejection.
  const pdbTouched = targetPdb.trim().length > 0;
  const pdbShapeError =
    pdbTouched && !isValidPdbId(targetPdb)
      ? `"${targetPdb.trim()}" isn't a PDB ID. They're four characters starting with a digit: try the example, ${EXAMPLE_JOB.targetPdb}.`
      : null;

  /**
   * One-click demo: submits the known-good BindCraft / PD-L1 (5O45) job with a
   * literal payload, so nothing depends on the form's current state.
   */
  function runExample() {
    setRanExample(true);
    submit.mutate(exampleSubmission(projectId));
  }

  // ─── Cost preview ──────────────────────────────────────────────────────
  // Debounce the (toolId, numDesigns) tuple. The server cost calculator is
  // cheap, but a query per keystroke is still rude and shows up as
  // unnecessary "loading" flashes in the UI.
  const [debouncedKey, setDebouncedKey] = useState<{
    tool: string;
    numDesigns: number;
  } | null>(null);
  useEffect(() => {
    if (!selectedToolId || numDesigns < 1) {
      setDebouncedKey(null);
      return;
    }
    const id = window.setTimeout(() => {
      setDebouncedKey({ tool: selectedToolId, numDesigns });
    }, 300);
    return () => window.clearTimeout(id);
  }, [selectedToolId, numDesigns]);
  const preview = trpc.jobs.previewCost.useQuery(
    debouncedKey ?? { tool: "", numDesigns: 1 },
    {
      enabled: debouncedKey !== null,
      // Don't refetch on focus: the cap rarely shifts under the user.
      refetchOnWindowFocus: false,
    },
  );
  const seeds = useMemo(
    () => Array.from({ length: Math.max(1, numDesigns) }, (_v, i) => i + 1),
    [numDesigns],
  );

  // Only surface targets with a pdbId: prefilling the input with a name would
  // fail server-side validation. Scoping to this project keeps the menu tight.
  const recentTargets = useMemo(() => {
    const items = targets.data?.items ?? [];
    return items.filter((t) => {
      const targetProjectId = (t as { projectId?: string | null }).projectId;
      return t.pdbId && (!targetProjectId || targetProjectId === projectId);
    });
  }, [targets.data, projectId]);

  const selectedTarget = useMemo(
    () => recentTargets.find((t) => t.id === selectedTargetId) ?? null,
    [recentTargets, selectedTargetId],
  );

  const matchedTargetByPdb = useMemo(() => {
    const v = targetPdb.trim().toUpperCase();
    if (v.length !== 4) return null;
    return (
      recentTargets.find((t) => (t.pdbId ?? "").toUpperCase() === v) ?? null
    );
  }, [recentTargets, targetPdb]);

  const activeTarget = selectedTarget ?? matchedTargetByPdb;
  const activeHotspots = (() => {
    const h = activeTarget?.hotspots;
    if (Array.isArray(h)) return h.length;
    if (h && typeof h === "object" && "chain" in (h as object)) return 1;
    return 0;
  })();

  function handlePickTarget(id: string) {
    setSelectedTargetId(id);
    const picked = recentTargets.find((t) => t.id === id);
    if (picked?.pdbId) setTargetPdb(picked.pdbId);
  }

  return (
    <form
      id="submit-job"
      data-testid="e2e-job-submission-form"
      className="p-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!selectedToolId || !targetPdb.trim()) return;
        submit.mutate({
          toolId: selectedToolId,
          request: {
            targetPdb: targetPdb.trim(),
            seeds,
            numDesigns,
            // Pass targetId when the user picked from the dropdown so the
            // server can look up saved hotspots even before the row matches
            // by pdbId (e.g. uploaded PDBs that have no 4-char id).
            toolParams: activeTarget
              ? { projectId, targetId: activeTarget.id }
              : { projectId },
          },
        });
      }}
    >
      {/* One-click demo path: the visually primary action for anyone who
          hasn't run a job before. Submits a complete, known-good job with no
          typing; the manual fields below stay available underneath. */}
      <div className="mb-5 rounded-lg border border-crane/40 bg-crane/5 p-4">
        <p className="font-sans text-[12px] text-graphite-soft">
          Example job
        </p>
        <p className="mt-2.5 max-w-xl font-sans text-[13.5px] leading-relaxed text-graphite">
          Submit {EXAMPLE_JOB.numDesigns} designs with {EXAMPLE_JOB.toolName} on{" "}
          {EXAMPLE_JOB.targetName}, PDB {EXAMPLE_JOB.targetPdb} chain{" "}
          {EXAMPLE_JOB.targetChain}, using {exampleHotspotLabel()}.
        </p>
        <button
          type="button"
          onClick={runExample}
          disabled={submit.isPending}
          data-testid="e2e-job-run-example"
          className="mt-3 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md bg-crane-deep px-5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submit.isPending && ranExample ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          Run the example
        </button>
      </div>

      <p className="mb-4 max-w-xl font-sans text-[13px] leading-relaxed text-graphite">
        Or set it up yourself: pick the model, name the protein to design
        against (its four-character PDB ID), and say how many attempts to run.
      </p>

      {recentTargets.length > 0 && (
        <label className="mb-4 flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Or pick from recent targets
          </span>
          <select
            value={selectedTargetId}
            onChange={(event) => handlePickTarget(event.target.value)}
            disabled={targets.isLoading || submit.isPending}
            data-testid="e2e-job-recent-targets"
            className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-sans text-[14px] text-ink focus:border-ink focus:outline-none"
          >
            <option value="">Select a saved target…</option>
            {recentTargets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.pdbId ? ` · ${t.pdbId}` : ""}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="grid gap-4 md:grid-cols-[1fr_180px_150px_auto] md:items-end">
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Tool
          </span>
          <select
            value={selectedToolId}
            onChange={(event) => setToolId(event.target.value)}
            disabled={tools.isLoading || submit.isPending}
            data-testid="e2e-job-tool-select"
            className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-sans text-[14px] text-ink focus:border-ink focus:outline-none"
          >
            {tools.isLoading && <option>Loading tools…</option>}
            {!tools.isLoading && runnableTools.length === 0 && (
              <option value="">No tools available</option>
            )}
            {runnableTools.map((tool) => (
              <option key={tool.toolId} value={tool.toolId}>
                {tool.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Target PDB
          </span>
          <input
            value={targetPdb}
            onChange={(event) => {
              setTargetPdb(event.target.value);
              // Clear the dropdown when the user types something that no
              // longer matches their picked target.
              if (selectedTargetId) setSelectedTargetId("");
            }}
            placeholder={EXAMPLE_JOB.targetPdb}
            minLength={4}
            required
            disabled={submit.isPending}
            aria-invalid={pdbShapeError ? true : undefined}
            data-testid="e2e-job-target-pdb"
            className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Designs
          </span>
          <input
            type="number"
            min={1}
            max={32}
            value={numDesigns}
            onChange={(event) =>
              setNumDesigns(
                Math.max(1, Math.min(32, Number(event.target.value) || 1)),
              )
            }
            disabled={submit.isPending}
            data-testid="e2e-job-num-designs"
            className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-mono text-[14px] text-ink focus:border-ink focus:outline-none"
          />
        </label>

        <button
          type="submit"
          disabled={
            submit.isPending ||
            tools.isLoading ||
            !selectedToolId ||
            targetPdb.trim().length < 4 ||
            pdbShapeError !== null ||
            preview.data?.wouldExceed === true
          }
          data-testid="e2e-job-submit"
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-crane-deep px-5 font-sans text-[13px] text-paper transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submit.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          Submit
        </button>
      </div>

      {pdbShapeError && (
        <p
          role="alert"
          data-testid="e2e-job-pdb-error"
          className="mt-3 font-sans text-[13px] text-crane-deep"
        >
          {pdbShapeError}
        </p>
      )}

      {!pdbShapeError && selectedToolId && targetPdb.trim().length >= 4 && (
        <p className="mt-3 font-sans text-[13px] leading-relaxed text-graphite">
          On submit:{" "}
          <span className="font-medium text-ink">{selectedToolName}</span> runs
          on our GPUs and produces {numDesigns} candidate binder
          {numDesigns === 1 ? "" : "s"} against {targetPdb.trim().toUpperCase()}
          . You&apos;ll go straight to a live progress screen. The job keeps
          running if you close the tab.
        </p>
      )}

      {preview.isLoading && (
        <p className="mt-3 font-sans text-[13px] text-graphite">
          Checking cost against your GPU spend cap…
        </p>
      )}

      {preview.data && (
        <p
          data-testid="e2e-job-cost-preview"
          className={`mt-3 font-sans text-[13px] ${
            preview.data.wouldExceed ? "text-crane-deep" : "text-graphite"
          }`}
        >
          {preview.data.wouldExceed ? (
            <>
              <span className="font-medium">
                This job would exceed your beta cap.
              </span>{" "}
              Estimated cost: {formatUsd(preview.data.estimatedUsd)} · only{" "}
              {formatUsd(preview.data.remainingUsd)} remaining of{" "}
              {formatUsd(preview.data.capUsd)}.
            </>
          ) : (
            <>
              Estimated cost: {formatUsd(preview.data.estimatedUsd)} · You have{" "}
              {formatUsd(preview.data.remainingUsd)} remaining in your{" "}
              {formatUsd(preview.data.capUsd)} beta cap.
            </>
          )}
        </p>
      )}

      {activeTarget && activeHotspots > 0 && (
        <p
          data-testid="e2e-job-hotspot-hint"
          className="mt-3 font-sans text-[13px] text-crane-deep"
        >
          ✓ hotspots will be auto-included ({activeHotspots} saved on{" "}
          {activeTarget.name})
        </p>
      )}

      {tools.error && (
        <p role="alert" className="mt-3 font-sans text-[13px] text-crane-deep">
          We couldn&apos;t load the model list. Refresh the page: until it
          loads, no job can be submitted.
        </p>
      )}
      {!tools.isLoading && !tools.error && runnableTools.length === 0 && (
        <p className="mt-3 font-sans text-[13px] text-crane-deep">
          No verified models are available on your plan right now, so nothing
          can be submitted from here.
        </p>
      )}
      {submit.error && (
        <p
          role="alert"
          data-testid="e2e-job-submit-error"
          className="mt-3 font-sans text-[13px] leading-relaxed text-crane-deep"
        >
          {friendlySubmitError(
            submit.error,
            ranExample ? EXAMPLE_JOB.toolName : selectedToolName,
          )}
        </p>
      )}
    </form>
  );
}
