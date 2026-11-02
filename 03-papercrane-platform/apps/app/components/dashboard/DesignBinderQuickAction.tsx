"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play } from "lucide-react";
import { Dialog } from "@papercrane/ui";
import { toolInputSpec, type ToolTier } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import {
  BackboneInput,
  backboneRequestValue,
  isBackboneValid,
  type BackboneValue,
} from "@/components/jobs/BackboneInput";
import {
  ComplexInputStep,
  isValidPdbId,
  isValidStructureReference,
  type ComplexInput,
} from "@/components/jobs/ComplexInputStep";
import {
  SequenceInput,
  isSequenceValid,
  type SequenceValue,
} from "@/components/jobs/SequenceInput";
import {
  LigandInput,
  isLigandValid,
  ligandToolParams,
  type LigandValue,
} from "@/components/jobs/LigandInput";

const TIER_RANK: Record<ToolTier, number> = {
  free: 0,
  pro: 1,
  frontier: 2,
};

const QUICK_TOOL_ORDER = [
  "boltzgen",
  "bindcraft",
  "rfdiffusion",
  "chroma",
  "proteinmpnn",
  "ligandmpnn",
  "solublempnn",
  "boltz1",
  "boltz2",
  "chai1",
  "alphafold3",
  "esm2",
] as const;

/**
 * Dashboard hero CTA. Opens a compact modal that submits a job directly
 * via `trpc.jobs.submit`: saves the user the 2-page hop through
 * /app/projects just to launch their first run.
 */
export function DesignBinderQuickAction() {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const tools = trpc.tools.list.useQuery({}, { enabled: open });
  const usage = trpc.usage.getCurrentPeriodUsage.useQuery(undefined, {
    enabled: open,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const submit = trpc.jobs.submit.useMutation({
    onSuccess: (job) => {
      setOpen(false);
      router.push(`/app/jobs/${job.id}`);
      router.refresh();
    },
  });

  const userTier = (usage.data?.orgTier ?? "free") as ToolTier;
  const runnableTools = (tools.data?.items ?? [])
    .filter((tool) => {
      const tier = tool.tier as ToolTier;
      return tool.runnable && TIER_RANK[tier] <= TIER_RANK[userTier];
    })
    .sort((a, b) => {
      const aIndex = QUICK_TOOL_ORDER.indexOf(
        a.toolId as (typeof QUICK_TOOL_ORDER)[number],
      );
      const bIndex = QUICK_TOOL_ORDER.indexOf(
        b.toolId as (typeof QUICK_TOOL_ORDER)[number],
      );
      return (
        (aIndex < 0 ? Number.MAX_SAFE_INTEGER : aIndex) -
        (bIndex < 0 ? Number.MAX_SAFE_INTEGER : bIndex)
      );
    });
  const firstToolId = runnableTools[0]?.toolId ?? "";
  const [toolId, setToolId] = useState("");
  const [targetPdb, setTargetPdb] = useState("");
  const [backbone, setBackbone] = useState<BackboneValue>({
    pdb: "",
    chain: "",
  });
  const [complex, setComplex] = useState<ComplexInput>({
    targetPdb: "",
    targetChain: "",
    partnerPdb: "",
    partnerChain: "",
  });
  const [sequences, setSequences] = useState<SequenceValue>({
    raw: "",
    sequences: [],
  });
  const [ligand, setLigand] = useState<LigandValue>({ mode: "none" });
  const [numDesigns, setNumDesigns] = useState(8);

  const selectedToolId = toolId || firstToolId;
  const inputSpec = toolInputSpec(selectedToolId);
  const seeds = useMemo(
    () => Array.from({ length: Math.max(1, numDesigns) }, (_v, i) => i + 1),
    [numDesigns],
  );
  const mainInputValid =
    inputSpec.inputKind === "target"
      ? isValidPdbId(targetPdb)
      : inputSpec.inputKind === "backbone"
        ? isBackboneValid(backbone)
        : inputSpec.inputKind === "complex"
          ? isValidStructureReference(complex.targetPdb) &&
            isValidStructureReference(complex.partnerPdb)
          : isSequenceValid(sequences);
  const ligandValid =
    inputSpec.ligand === "none" ||
    isLigandValid(ligand, inputSpec.ligand === "required");
  const canSubmit =
    !!selectedToolId && mainInputValid && ligandValid && !submit.isPending;

  const submitSelectedTool = () => {
    if (!canSubmit) return;

    const toolParams: Record<string, unknown> = {};
    if (inputSpec.inputKind === "sequences") {
      toolParams.sequences = sequences.sequences;
    }
    if (inputSpec.ligand !== "none") {
      Object.assign(toolParams, ligandToolParams(ligand));
    }

    const requestFields =
      inputSpec.inputKind === "complex"
        ? {
            targetPdb: complex.targetPdb.trim(),
            partnerPdb: complex.partnerPdb.trim(),
            ...(complex.targetChain
              ? { targetChain: complex.targetChain }
              : {}),
            ...(complex.partnerChain
              ? { partnerChain: complex.partnerChain }
              : {}),
          }
        : inputSpec.inputKind === "backbone"
          ? {
              targetPdb: backboneRequestValue(backbone),
              ...(backbone.chain ? { targetChain: backbone.chain } : {}),
            }
          : inputSpec.inputKind === "target"
            ? { targetPdb: targetPdb.trim() }
            : {};

    submit.mutate({
      toolId: selectedToolId,
      request: {
        ...requestFields,
        seeds,
        numDesigns,
        toolParams,
      },
    });
  };

  return (
    <section className="bg-paper py-5">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="max-w-xl">
          <h2 className="mt-2 font-sans font-medium text-[28px] leading-[1.1] tracking-[-0.01em] text-ink">
            Run a design job
          </h2>
          <p className="mt-2 font-sans text-[14px] text-graphite">
            Choose a tool and add your protein inputs.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-testid="e2e-dashboard-design-binder"
          className="inline-flex items-center gap-2 rounded-full bg-crane-deep px-5 py-2.5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-ink"
        >
          <Play className="h-4 w-4" aria-hidden />
          New job
        </button>
      </div>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (submit.isPending) return;
          setOpen(next);
        }}
        title="Run a protein design tool"
        description="Choose a tool, provide its inputs, and submit a run."
        size="lg"
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitSelectedTool();
          }}
          className="flex flex-col gap-5"
        >
          <label className="flex flex-col gap-1.5">
            <span className="font-sans text-[12px] text-graphite-soft">
              Tool
            </span>
            <select
              value={selectedToolId}
              onChange={(event) => setToolId(event.target.value)}
              disabled={tools.isLoading || usage.isLoading || submit.isPending}
              className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-sans text-[14px] text-ink focus:border-ink focus:outline-none"
            >
              {(tools.isLoading || usage.isLoading) && (
                <option>Loading tools…</option>
              )}
              {runnableTools.map((tool) => (
                <option key={tool.toolId} value={tool.toolId}>
                  {tool.name}
                </option>
              ))}
            </select>
          </label>

          <div
            key={inputSpec.inputKind}
            className="motion-safe:animate-fade-in"
          >
            {inputSpec.inputKind === "target" && (
              <label className="flex flex-col gap-1.5">
                <span className="font-sans text-[12px] text-graphite-soft">
                  Target PDB
                </span>
                <input
                  value={targetPdb}
                  onChange={(event) => setTargetPdb(event.target.value)}
                  placeholder="e.g. 6X1A"
                  maxLength={4}
                  required
                  disabled={submit.isPending}
                  autoFocus
                  className="min-h-[44px] rounded-xl border border-lattice-strong bg-paper px-3 font-sans tabular-nums text-[14px] text-ink placeholder:font-sans placeholder:normal-case placeholder:tracking-normal placeholder:text-graphite-soft focus:border-ink focus:outline-none"
                />
              </label>
            )}

            {inputSpec.inputKind === "backbone" && (
              <BackboneInput
                value={backbone}
                onChange={(patch) =>
                  setBackbone((current) => ({ ...current, ...patch }))
                }
              />
            )}

            {inputSpec.inputKind === "complex" && (
              <ComplexInputStep
                value={complex}
                onChange={(patch) =>
                  setComplex((current) => ({ ...current, ...patch }))
                }
              />
            )}

            {inputSpec.inputKind === "sequences" && (
              <SequenceInput
                value={sequences}
                onChange={(patch) =>
                  setSequences((current) => ({ ...current, ...patch }))
                }
              />
            )}
          </div>

          {inputSpec.ligand !== "none" && (
            <LigandInput
              value={ligand}
              required={inputSpec.ligand === "required"}
              onChange={(patch) =>
                setLigand((current) => ({ ...current, ...patch }))
              }
            />
          )}

          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <span className="font-sans text-[12px] text-graphite-soft">
                Designs
              </span>
              <span className="font-sans tabular-nums text-[14px] text-ink">
                {numDesigns}
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={32}
              value={numDesigns}
              onChange={(event) =>
                setNumDesigns(
                  Math.max(1, Math.min(32, Number(event.target.value) || 1)),
                )
              }
              disabled={submit.isPending}
              className="h-2 w-full appearance-none rounded-full bg-lattice accent-crane-deep"
            />
            <div className="flex justify-between font-sans tabular-nums text-[12px] text-graphite-soft">
              <span>1</span>
              <span>32</span>
            </div>
          </div>

          {submit.error && (
            <p className="font-sans text-[13px] text-crane-deep">
              Could not submit job: {submit.error.message}
            </p>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              disabled={submit.isPending}
              className="font-sans text-[13px] text-graphite underline decoration-lattice-strong underline-offset-4 hover:text-ink hover:decoration-ink disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              data-testid="e2e-dashboard-design-binder-submit"
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-crane-deep px-5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submit.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Submit
            </button>
          </div>
        </form>
      </Dialog>
    </section>
  );
}
