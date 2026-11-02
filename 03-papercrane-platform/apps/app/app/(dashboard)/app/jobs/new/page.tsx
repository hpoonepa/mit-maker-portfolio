"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import type {
  Target,
  ToolManifest,
  ToolTier,
  WorkflowId,
} from "@papercrane/types";
import {
  PAPERCRANE_WORKFLOWS,
  getPapercraneWorkflow,
  jobInputKind,
  jobLigandRequirement,
} from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";
import { JobWizard, type WizardStep } from "@/components/jobs/JobWizard";
import { ToolPicker } from "@/components/jobs/ToolPicker";
import { WorkflowPicker } from "@/components/jobs/WorkflowPicker";
import { NewJobReview } from "@/components/jobs/NewJobReview";
import { StepIntro } from "@/components/jobs/StepIntro";
import { ExampleRunCard } from "@/components/jobs/ExampleRunCard";
import { PreSubmitSummary } from "@/components/jobs/PreSubmitSummary";
import { InputStepBody } from "@/components/jobs/InputStepBody";
import { ToolParamsPanel } from "@/components/jobs/ToolParamsPanel";
import { DesignsStepBody } from "@/components/jobs/DesignsStepBody";
import {
  isValidStructureReference,
  type ComplexInput,
} from "@/components/jobs/ComplexInputStep";
import {
  isBackboneValid,
  backboneRequestValue,
  type BackboneValue,
} from "@/components/jobs/BackboneInput";
import {
  isSequenceValid,
  type SequenceValue,
} from "@/components/jobs/SequenceInput";
import { isLigandValid, type LigandValue } from "@/components/jobs/LigandInput";
import { buildJobRequest } from "@/lib/jobs/buildRequest";
import { duplicateInput } from "@/lib/jobs/duplicateInput";
import {
  allocate,
  manualSumValid,
  type AllocationStrategy,
} from "@/lib/jobs/allocation";
import { estimateCost } from "@/lib/jobs/estimateCost";
import {
  estimateEta,
  formatEta,
  type EtaEstimate,
} from "@/lib/jobs/estimateEta";
import { EXAMPLE_JOB, exampleSubmission } from "@/lib/jobs/exampleJob";
import { friendlySubmitError } from "@/lib/jobs/submitErrors";
import {
  parameterFieldsFromJsonSchema,
  resolvedParameterDefaults,
} from "@/lib/jobs/jsonSchemaParams";
import { validateParams } from "@/components/jobs/ParamsEditor";
import {
  mergeToolParams,
  parseToolParamsJson,
  serializeToolParams,
} from "@/lib/jobs/toolParams";
import { isToolTierAllowed } from "@/lib/jobs/toolTier";
import { STATIC_TOOL_MANIFESTS } from "@/lib/static-tool-catalog";

type RunnableToolManifest = ToolManifest & {
  defaultParams?: Record<string, unknown>;
  inputSchema?: Record<string, unknown>;
};

const STEPS: WizardStep[] = [
  { id: "tools", label: "Tools" },
  { id: "input", label: "Input" },
  { id: "designs", label: "Designs" },
  { id: "review", label: "Review & run" },
];

const DEFAULT_DESIGNS = 1;
const TOOL_DEFAULT_DESIGNS: Record<string, number> = {
  // BoltzGen runs one full GPU workflow per design. One is the useful default
  // for a first run or demo; users can still raise it deliberately.
  boltzgen: 1,
};

/** Either an S3 artifact key or a 4-char RCSB id: what jobs.submit wants. */
function deriveTargetPdb(t: Target | null | undefined): string {
  if (!t) return "";
  if (t.pdbId) return t.pdbId;
  const key = (t as { artifactKey?: string }).artifactKey;
  return typeof key === "string" ? key : "";
}

function newSubmissionId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `sub-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

function NewJobWizard() {
  const router = useRouter();
  const { toast } = useToast();
  const sp = useSearchParams();
  const toolParam = sp.get("tool");
  const cloneOf = sp.get("cloneOf") ?? sp.get("retryOf") ?? sp.get("from");
  const requestedProjectId = sp.get("projectId");
  const targetParam = sp.get("target");

  // ─── Data ────────────────────────────────────────────────────────────────
  const targetsQuery = trpc.targets.list.useQuery({ limit: 50 });
  const toolsQuery = trpc.tools.list.useQuery({});
  // Best-effort: seed headroom + tier. 404s for orgs with no period yet.
  const usageQuery = trpc.usage.getCurrentPeriodUsage.useQuery(undefined, {
    retry: false,
    refetchOnWindowFocus: false,
  });
  const sourceJob = trpc.jobs.get.useQuery(
    { id: cloneOf ?? "" },
    { enabled: Boolean(cloneOf), retry: false, refetchOnWindowFocus: false },
  );

  const targets = useMemo(
    () => (targetsQuery.data?.items ?? []) as Target[],
    [targetsQuery.data?.items],
  );
  const copiedInput = useMemo(() => duplicateInput(sourceJob.data?.params, targets), [sourceJob.data?.params, targets]);
  const projectIdParam = requestedProjectId || (cloneOf ? copiedInput.projectId : null);
  const toolItems = useMemo(
    () => {
      const merged = new Map<string, RunnableToolManifest>(
        STATIC_TOOL_MANIFESTS.map((tool) => [
          tool.toolId,
          tool as RunnableToolManifest,
        ]),
      );
      for (const tool of toolsQuery.data?.items ?? []) {
        merged.set(tool.toolId, tool as unknown as RunnableToolManifest);
      }
      return Array.from(merged.values()) as RunnableToolManifest[];
    },
    [toolsQuery.data?.items],
  );

  // ─── Wizard state ──────────────────────────────────────────────────────────
  const [step, setStep] = useState(0);
  const [creatingTarget, setCreatingTarget] = useState(false);
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] =
    useState<WorkflowId | null>(null);
  // Structure-prediction co-fold inputs: only used when the selected family is
  // `structure-prediction`. Kept separate from the target dropdown so switching
  // families never clobbers either input.
  const [complex, setComplex] = useState<ComplexInput>({
    targetPdb: "",
    targetChain: "",
    partnerPdb: "",
    partnerChain: "",
  });
  // Backbone (inverse-folding) and raw-sequence inputs: used per input kind.
  // Kept separate from the target/complex inputs so switching tools never
  // clobbers a previously typed value.
  const [backbone, setBackbone] = useState<BackboneValue>({
    pdb: "",
    chain: "",
  });
  const [sequences, setSequences] = useState<SequenceValue>({
    raw: "",
    sequences: [],
  });
  const [ligand, setLigand] = useState<LigandValue>({ mode: "none" });
  const [advancedParamsRaw, setAdvancedParamsRaw] = useState<
    Record<string, string>
  >({});
  const [totalDesigns, setTotalDesigns] = useState(DEFAULT_DESIGNS);
  const [strategy, setStrategy] = useState<AllocationStrategy>("auto");
  const [manualCounts, setManualCounts] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [failedTools, setFailedTools] = useState<string[]>([]);
  // One-click demo path. Submitted from a literal payload (see
  // `exampleSubmission`) rather than by prefilling wizard state, so a viewer
  // reaches a running job on the FIRST click with no render round-trip.
  const [runningExample, setRunningExample] = useState(false);
  const [exampleDismissed, setExampleDismissed] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);

  const submitMutation = trpc.jobs.submit.useMutation();
  const utils = trpc.useUtils?.();

  // ─── Derived ────────────────────────────────────────────────────────────────
  const toolNameMap = useMemo(() => {
    const m: Record<string, string> = {};
    for (const t of toolItems) m[t.toolId] = t.name;
    return m;
  }, [toolItems]);

  const selectedTarget = useMemo(
    () => targets.find((t) => t.id === selectedTargetId) ?? null,
    [targets, selectedTargetId],
  );
  const targetPdb = useMemo(
    () => deriveTargetPdb(selectedTarget),
    [selectedTarget],
  );

  const selectedTools = useMemo(
    () =>
      selectedToolIds
        .map((id) => toolItems.find((t) => t.toolId === id))
        .filter((t): t is RunnableToolManifest => Boolean(t)),
    [selectedToolIds, toolItems],
  );
  const selectedWorkflow = useMemo(
    () => getPapercraneWorkflow(selectedWorkflowId ?? undefined),
    [selectedWorkflowId],
  );

  const { advancedParamsByTool, advancedParamsValid } = useMemo(() => {
    const values: Record<string, Record<string, unknown>> = {};
    let valid = true;
    for (const toolId of selectedToolIds) {
      const tool = toolItems.find((item) => item.toolId === toolId);
      const defaults = resolvedParameterDefaults(
        tool?.inputSchema,
        tool?.defaultParams,
      );
      const parsed = parseToolParamsJson(
        advancedParamsRaw[toolId] ?? serializeToolParams(defaults),
      );
      if (parsed.value === null) valid = false;
      else {
        values[toolId] = parsed.value;
        const fields = parameterFieldsFromJsonSchema(
          tool?.inputSchema,
          tool?.defaultParams,
        );
        if (Object.keys(validateParams(fields, parsed.value)).length > 0) {
          valid = false;
        }
      }
    }
    return { advancedParamsByTool: values, advancedParamsValid: valid };
  }, [advancedParamsRaw, selectedToolIds, toolItems]);

  // Selection is constrained to a single input kind (enforced in ToolPicker),
  // so the selected tools' shared kind drives the whole input step.
  const inputKind = useMemo(
    () => jobInputKind(selectedToolIds),
    [selectedToolIds],
  );
  const ligandReq = useMemo(
    () => jobLigandRequirement(selectedToolIds),
    [selectedToolIds],
  );
  // Kept for copy that flips predictions↔designs (was the old `isStructure`).
  const isComplex = inputKind === "complex";
  // The target pdb the request actually carries, per input kind. Empty for the
  // sequences kind (which omits targetPdb entirely) and for incomplete inputs.
  const effectiveTargetPdb = useMemo(() => {
    if (inputKind === "complex") return complex.targetPdb.trim();
    if (inputKind === "backbone") return backboneRequestValue(backbone);
    if (inputKind === "sequences") return "";
    return targetPdb;
  }, [inputKind, complex.targetPdb, backbone, targetPdb]);

  const perToolCounts = useMemo<Record<string, number>>(() => {
    if (selectedToolIds.length === 0) return {};
    if (selectedToolIds.length === 1) {
      const only = selectedToolIds[0];
      return only ? { [only]: totalDesigns } : {};
    }
    return allocate({
      strategy,
      totalDesigns,
      toolIds: selectedToolIds,
      manualCounts,
    });
  }, [selectedToolIds, totalDesigns, strategy, manualCounts]);

  // Aggregate cost (sum) + ETA (max, since tools run in parallel).
  const { cost, eta } = useMemo(() => {
    const agg = { totalDesigns: 0, totalSeeds: 0, seedCostPerDesign: 0 };
    let maxEta: EtaEstimate = {
      etaSeconds: 0,
      queueWaitSeconds: 0,
      runSeconds: 0,
      parallelism: Math.max(1, selectedTools.length),
    };
    for (const tool of selectedTools) {
      const count = Math.max(0, perToolCounts[tool.toolId] ?? 0);
      const c = estimateCost({ tool, seedsRequested: count, numDesigns: 1 });
      agg.totalDesigns += c.totalDesigns;
      agg.totalSeeds += c.totalSeeds;
      const e = estimateEta({ tool, totalDesigns: count });
      if (e.etaSeconds > maxEta.etaSeconds) {
        maxEta = { ...e, parallelism: Math.max(1, selectedTools.length) };
      }
    }
    agg.seedCostPerDesign =
      agg.totalDesigns > 0 ? agg.totalSeeds / agg.totalDesigns : 0;
    return { cost: agg, eta: maxEta };
  }, [selectedTools, perToolCounts]);

  const remainingSeeds = usageQuery.data
    ? Math.max(0, usageQuery.data.seedsIncluded - usageQuery.data.seedsConsumed)
    : undefined;
  const userTier = usageQuery.data?.orgTier as ToolTier | undefined;
  const overQuota =
    remainingSeeds !== undefined && cost.totalSeeds > remainingSeeds;

  const isToolAllowed = useMemo(() => {
    return (tool: ToolManifest) => {
      const enriched = tool as ToolManifest & {
        status?: string;
        runnable?: boolean;
      };
      const runnable = enriched.runnable ?? enriched.status === "ga";
      return runnable && isToolTierAllowed(tool.tier, userTier);
    };
  }, [userTier]);

  // Server truth for execution readiness. Release status is separate: beta
  // tools can run while they accumulate production verification.
  const isToolRunnable = useMemo(
    () => (tool: ToolManifest) =>
      (tool as ToolManifest & { status?: string; runnable?: boolean })
        .runnable ??
      (tool as ToolManifest & { status?: string }).status === "ga",
    [],
  );
  const availableWorkflowIds = useMemo(() => {
    const available = new Set<WorkflowId>();
    for (const workflow of PAPERCRANE_WORKFLOWS) {
      const canRun = workflow.stages.every((stage) => {
        const tool = toolItems.find((item) => item.toolId === stage.toolId);
        return Boolean(
          tool && isToolRunnable(tool) && isToolAllowed(tool),
        );
      });
      if (canRun) available.add(workflow.id);
    }
    return available;
  }, [isToolAllowed, isToolRunnable, toolItems]);

  // ─── One-click example ───────────────────────────────────────────────────
  const exampleTool = useMemo(
    () => toolItems.find((t) => t.toolId === EXAMPLE_JOB.toolId) ?? null,
    [toolItems],
  );
  const exampleReady = Boolean(exampleTool && isToolRunnable(exampleTool));
  const showExample =
    !exampleDismissed &&
    !cloneOf &&
    !toolParam &&
    selectedToolIds.length === 0 &&
    step === 0;
  const exampleEtaLabel = exampleTool
    ? formatEta(
        estimateEta({
          tool: exampleTool,
          totalDesigns: EXAMPLE_JOB.numDesigns,
        }).etaSeconds,
      )
    : undefined;
  const examplePreview = trpc.jobs.previewCost.useQuery(
    { tool: EXAMPLE_JOB.toolId, numDesigns: EXAMPLE_JOB.numDesigns },
    {
      enabled: showExample && exampleReady,
      retry: false,
      refetchOnWindowFocus: false,
    },
  );

  // ─── Dollar estimate for the review step ─────────────────────────────────
  // `previewCost` is per-tool, so a multi-tool comparison shows the primary
  // tool's figure and says so: the cap numbers it returns are org-wide and
  // therefore correct either way.
  const primaryToolId = selectedToolIds[0] ?? "";
  const reviewPreview = trpc.jobs.previewCost.useQuery(
    {
      tool: primaryToolId,
      ...(selectedWorkflowId ? { workflowId: selectedWorkflowId } : {}),
      numDesigns: Math.max(1, perToolCounts[primaryToolId] ?? 1),
    },
    {
      enabled: primaryToolId.length > 0 && step === STEPS.length - 1,
      retry: false,
      refetchOnWindowFocus: false,
    },
  );
  const capBlocked = reviewPreview.data?.wouldExceed === true;

  // ─── Prefill from query string (best-effort, once) ──────────────────────────
  const appliedRef = useRef(false);
  useEffect(() => {
    if (appliedRef.current) return;
    if (toolsQuery.isLoading) return;
    if (cloneOf && sourceJob.isLoading) return;
    if (cloneOf && targetsQuery.isLoading) return;
    const clonedWorkflowRecord =
      sourceJob.data?.params?._papercraneWorkflow &&
      typeof sourceJob.data.params._papercraneWorkflow === "object"
        ? (sourceJob.data.params._papercraneWorkflow as Record<string, unknown>)
        : undefined;
    const clonedWorkflowId = clonedWorkflowRecord?.id;
    const clonedWorkflow =
      typeof clonedWorkflowId === "string"
        ? getPapercraneWorkflow(clonedWorkflowId)
        : undefined;
    if (clonedWorkflow && availableWorkflowIds.has(clonedWorkflow.id)) {
      const entryTool = clonedWorkflow.stages[0]?.toolId;
      if (entryTool) {
        setSelectedWorkflowId(clonedWorkflow.id);
        setSelectedToolIds([entryTool]);
        setStep(1);
      }
    }
    const presetTool = toolParam ?? sourceJob.data?.toolId;
    if (
      !clonedWorkflow &&
      presetTool &&
      toolItems.some(
        (tool) => tool.toolId === presetTool && isToolRunnable(tool),
      )
    ) {
      setSelectedToolIds([presetTool]);
      setStep(1);
      if (!cloneOf) {
        setTotalDesigns(TOOL_DEFAULT_DESIGNS[presetTool] ?? DEFAULT_DESIGNS);
      }
    }
    const srcDesigns = sourceJob.data?.numDesigns;
    if (typeof srcDesigns === "number" && srcDesigns > 0) {
      setTotalDesigns(srcDesigns);
    }
    if (sourceJob.data && presetTool) {
      setSelectedTargetId(copiedInput.targetId);
      setBackbone(copiedInput.backbone);
      setComplex(copiedInput.complex);
      setSequences(copiedInput.sequences);
      setLigand(copiedInput.ligand);
      setAdvancedParamsRaw({ [presetTool]: serializeToolParams(copiedInput.toolParams) });
    }
    appliedRef.current = true;
  }, [
    toolsQuery.isLoading,
    sourceJob.isLoading,
    sourceJob.data,
    toolItems,
    toolParam,
    cloneOf,
    copiedInput,
    targetsQuery.isLoading,
    isToolRunnable,
    availableWorkflowIds,
  ]);

  // Prefill the target from ?target=<id> once the targets list has loaded
  // (separate from the tool prefill since targets may arrive on a different
  // tick). Used when launching the wizard from a project page.
  const targetAppliedRef = useRef(false);
  useEffect(() => {
    if (targetAppliedRef.current) return;
    if (targetsQuery.isLoading) return;
    if (targetParam && targets.some((t) => t.id === targetParam)) {
      setSelectedTargetId(targetParam);
    }
    targetAppliedRef.current = true;
  }, [targetsQuery.isLoading, targets, targetParam]);

  // ─── Allocation handlers ────────────────────────────────────────────────────
  function handleStrategyChange(s: AllocationStrategy) {
    if (s === "manual") {
      // Seed manual counts from the current allocation so it starts balanced.
      setManualCounts((prev) => {
        const seeded: Record<string, number> = {};
        for (const id of selectedToolIds) {
          seeded[id] = prev[id] ?? perToolCounts[id] ?? 0;
        }
        return seeded;
      });
    }
    setStrategy(s);
  }
  function handleManualChange(toolId: string, value: number) {
    setManualCounts((prev) => ({ ...prev, [toolId]: value }));
  }

  function handleToolSelectionChange(nextIds: string[]) {
    setSelectedWorkflowId(null);
    // Apply a slower tool's safer first-run default only on the initial pick.
    // Never overwrite a count the user has already changed.
    if (
      selectedToolIds.length === 0 &&
      nextIds.length === 1 &&
      totalDesigns === DEFAULT_DESIGNS
    ) {
      const first = nextIds[0];
      if (first) {
        setTotalDesigns(TOOL_DEFAULT_DESIGNS[first] ?? DEFAULT_DESIGNS);
      }
    }
    setSelectedToolIds(nextIds);
  }

  function handleWorkflowSelection(id: WorkflowId) {
    const workflow = getPapercraneWorkflow(id);
    const entryTool = workflow?.stages[0]?.toolId;
    if (!workflow || !entryTool || !availableWorkflowIds.has(id)) return;
    setSelectedWorkflowId(id);
    setSelectedToolIds([entryTool]);
    setStrategy("auto");
    setTotalDesigns(id === "binder-high-confidence" ? 2 : 4);
  }

  // ─── Validation gating ──────────────────────────────────────────────────────
  const everyToolHasOne =
    selectedToolIds.length > 0 &&
    selectedToolIds.every((id) => (perToolCounts[id] ?? 0) >= 1);
  const manualOk =
    strategy !== "manual" ||
    selectedToolIds.length < 2 ||
    manualSumValid(manualCounts, selectedToolIds, totalDesigns);
  const step3Valid =
    totalDesigns >= 1 && everyToolHasOne && manualOk && !overQuota;

  const complexInputValid =
    isValidStructureReference(complex.targetPdb) &&
    isValidStructureReference(complex.partnerPdb);

  // Ligand is satisfied when no selected tool asks for one, or the provided
  // ligand is valid for the requirement (required tools must carry a value).
  const ligandOk =
    ligandReq === "none" || isLigandValid(ligand, ligandReq === "required");

  // The main input for the selected kind is complete.
  const inputKindValid = ((): boolean => {
    switch (inputKind) {
      case "target":
        return Boolean(selectedTargetId) && Boolean(targetPdb);
      case "backbone":
        return isBackboneValid(backbone);
      case "complex":
        return complexInputValid;
      case "sequences":
        return isSequenceValid(sequences);
      default:
        return false;
    }
  })();

  // Whole input step: a kind is chosen (tools picked), its input is complete,
  // and any ligand requirement is satisfied.
  const inputStepValid =
    inputKind !== null && inputKindValid && ligandOk && advancedParamsValid;

  const stepValid = (i: number): boolean => {
    const id = STEPS[i]?.id;
    if (id === "tools") return selectedToolIds.length >= 1;
    if (id === "input") return inputStepValid;
    if (id === "designs") return step3Valid;
    // Review: block submission the wizard already knows the server will
    // refuse, so a spend-cap rejection never arrives as a surprise error.
    return !capBlocked;
  };

  const isLast = step === STEPS.length - 1;

  // ─── One-click example submit ────────────────────────────────────────────
  // Deliberately bypasses wizard state: the payload is a literal, so the very
  // first click produces a real job. On success we land on that job's live
  // progress screen; on failure the message is rewritten in plain language.
  async function handleRunExample() {
    if (runningExample) return;
    setRunningExample(true);
    setExampleError(null);
    try {
      const job = await submitMutation.mutateAsync({
        ...exampleSubmission(projectIdParam ?? undefined),
        idempotencyKey: `example-${newSubmissionId()}`,
      });
      utils?.jobs.list.invalidate?.();
      toast({
        title: "Example job submitted",
        description: `${EXAMPLE_JOB.toolName} is designing ${EXAMPLE_JOB.numDesigns} binders against ${EXAMPLE_JOB.targetName}.`,
        variant: "success",
      });
      router.push(`/app/jobs/${job.id}`);
      router.refresh();
    } catch (err) {
      setExampleError(friendlySubmitError(err, EXAMPLE_JOB.toolName));
      setRunningExample(false);
    }
  }

  // ─── Submit ──────────────────────────────────────────────────────────────────
  async function handleRun() {
    if (selectedToolIds.length === 0 || !inputStepValid) return;
    setSubmitting(true);
    setFailedTools([]);
    const submissionId = newSubmissionId();

    const { fields, toolParams } = buildJobRequest({
      inputKind,
      ligandReq,
      ligand,
      complex,
      backbone,
      sequences,
      effectiveTargetPdb,
      targetChain: selectedTarget?.chain,
      projectId: projectIdParam,
      targetId: selectedTargetId,
    });

    const submissionToolIds = selectedWorkflow
      ? [selectedWorkflow.stages[0]!.toolId]
      : selectedToolIds;
    const results = await Promise.allSettled(
      submissionToolIds.map((toolId) => {
        const count = Math.max(1, perToolCounts[toolId] ?? 0);
        const seeds = cloneOf && copiedInput.seeds.length === count
          ? copiedInput.seeds : Array.from({ length: count }, (_v, i) => i + 1);
        const mergedToolParams = mergeToolParams(
          advancedParamsByTool[toolId],
          toolParams,
        );
        return submitMutation.mutateAsync({
          toolId,
          ...(selectedWorkflowId ? { workflowId: selectedWorkflowId } : {}),
          request: {
            ...(cloneOf && effectiveTargetPdb === copiedInput.targetPdb ? copiedInput.extras : {}),
            ...fields,
            seeds,
            numDesigns: count,
            ...(mergedToolParams ? { toolParams: mergedToolParams } : {}),
          },
          idempotencyKey: `${submissionId}-${toolId}`,
        });
      }),
    );

    const failed: string[] = [];
    results.forEach((r, i) => {
      const id = submissionToolIds[i];
      if (r.status === "rejected" && id) failed.push(id);
    });
    const successfulJobs = results.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : [],
    );
    const okCount = results.length - failed.length;
    const failedNames = failed.map((id) => toolNameMap[id] ?? id).join(", ");
    // A single successful submission goes straight to its live run screen.
    // Multi-tool comparisons stay grouped in the project/jobs overview.
    const onlyJob = successfulJobs.length === 1 ? successfulJobs[0] : null;
    const destination = onlyJob
      ? `/app/jobs/${onlyJob.id}`
      : projectIdParam
        ? `/app/projects/${projectIdParam}`
        : "/app/jobs";

    if (failed.length === 0) {
      utils?.jobs.list.invalidate?.();
      toast({
        title: "Jobs submitted",
        description: `${okCount} job${okCount === 1 ? "" : "s"} queued.`,
        variant: "success",
      });
      router.push(destination);
      router.refresh();
      return;
    }

    if (okCount === 0) {
      // Total failure: keep the user here to retry, and say WHY in plain
      // language rather than surfacing the raw tRPC message.
      const firstRejection = results.find(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      toast({
        title: "Nothing was submitted",
        description: firstRejection
          ? friendlySubmitError(firstRejection.reason, failedNames)
          : `Couldn't submit ${failedNames}. Nothing was queued.`,
        variant: "error",
      });
      setFailedTools(failed);
      setSubmitting(false);
      return;
    }

    // Partial: successes are real and proceed; surface the failures, redirect.
    utils?.jobs.list.invalidate?.();
    toast({
      title: "Some jobs failed",
      description: `Submitted ${okCount}, but ${failedNames} failed. The successful jobs are running.`,
      variant: "warning",
    });
    router.push(destination);
    router.refresh();
  }

  function handleNext() {
    if (isLast) {
      void handleRun();
    } else {
      setStep((s) => Math.min(STEPS.length - 1, s + 1));
    }
  }
  function handleBack() {
    setStep((s) => Math.max(0, s - 1));
  }

  // ─── Step bodies ──────────────────────────────────────────────────────────────
  // User-facing noun: "predictions" for co-fold (nothing is designed), "runs"
  // for sequence-only scoring, else "designs".
  const runNounPlural = isComplex
    ? "predictions"
    : inputKind === "sequences"
      ? "runs"
      : "designs";

  function renderStep() {
    const stepId = STEPS[step]?.id;

    if (stepId === "tools") {
      return (
        <div className="space-y-6">
          {showExample && (
            <details>
              <summary className="cursor-pointer py-2 text-sm text-graphite hover:text-ink">Use the PD-L1 example</summary>
              <ExampleRunCard
                ready={exampleReady}
                loadingCatalog={toolsQuery.isLoading}
                unavailableReason={
                  toolsQuery.error
                    ? "We couldn't load the tool catalog. Refresh the page and try again."
                    : !exampleTool
                      ? `${EXAMPLE_JOB.toolName} isn't in your catalog, so the example can't run. Pick a tool below instead.`
                      : `${EXAMPLE_JOB.toolName} isn't available to run right now. Pick a tool below instead.`
                }
                errorMessage={exampleError}
                costUsd={examplePreview.data?.estimatedUsd}
                capUsd={examplePreview.data?.capUsd}
                remainingUsd={examplePreview.data?.remainingUsd}
                wouldExceed={examplePreview.data?.wouldExceed}
                costLoading={examplePreview.isLoading && exampleReady}
                etaLabel={exampleEtaLabel}
                busy={runningExample}
                onRun={() => void handleRunExample()}
                onConfigureManually={() => setExampleDismissed(true)}
              />
            </details>
          )}
          <ToolPicker
            tools={toolItems}
            selectedIds={selectedToolIds}
            onSelectionChange={handleToolSelectionChange}
            userTier={userTier}
            isToolAllowed={isToolAllowed}
            isToolRunnable={isToolRunnable}
            loading={toolsQuery.isLoading}
          />
          <details className="pt-6">
            <summary className="cursor-pointer text-sm text-graphite hover:text-ink">Combine tools in a workflow</summary>
            <div className="pt-5">
          <WorkflowPicker
            selectedId={selectedWorkflowId}
            availableIds={availableWorkflowIds}
            onSelect={handleWorkflowSelection}
          />
            </div>
          </details>
          {toolsQuery.error && !toolsQuery.isLoading && (
            <p
              role="alert"
              className="rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
            >
              We couldn&apos;t load the tool catalog. Refresh the page: if it
              keeps happening, the catalog service is down and nothing can be
              submitted right now.
            </p>
          )}
        </div>
      );
    }

    if (stepId === "input") {
      return (
        <div className="space-y-5">
          <InputStepBody
            inputKind={inputKind}
            ligandReq={ligandReq}
            ligand={ligand}
            onLigandChange={(patch) =>
              setLigand((prev) => ({ ...prev, ...patch }))
            }
            targets={targets}
            projectId={projectIdParam ?? undefined}
            onTargetCreationChange={setCreatingTarget}
            selectedTargetId={selectedTargetId}
            onSelectTarget={setSelectedTargetId}
            targetsLoading={targetsQuery.isLoading}
            targetsError={
              targetsQuery.error
                ? "We couldn't load your saved targets. Refresh the page and try again."
                : selectedTarget && !targetPdb
                  ? "This target has no structure attached (no PDB ID and no uploaded file), so nothing can be designed against it. Pick another."
                  : undefined
            }
            complex={complex}
            onComplexChange={(patch) =>
              setComplex((prev) => ({ ...prev, ...patch }))
            }
            backbone={backbone}
            onBackboneChange={(patch) =>
              setBackbone((prev) => ({ ...prev, ...patch }))
            }
            sequences={sequences}
            onSequencesChange={(patch) =>
              setSequences((prev) => ({ ...prev, ...patch }))
            }
          />
          {!creatingTarget && <ToolParamsPanel
            tools={selectedTools}
            rawByTool={advancedParamsRaw}
            onChange={(toolId, raw) =>
              setAdvancedParamsRaw((current) => ({
                ...current,
                [toolId]: raw,
              }))
            }
          />}
        </div>
      );
    }

    if (stepId === "designs") {
      return (
        <DesignsStepBody
          runNounPlural={runNounPlural}
          selectedToolIds={selectedToolIds}
          selectedTools={selectedTools}
          toolNameMap={toolNameMap}
          totalDesigns={totalDesigns}
          onTotalDesignsChange={setTotalDesigns}
          strategy={strategy}
          onStrategyChange={handleStrategyChange}
          manualCounts={manualCounts}
          onManualChange={handleManualChange}
          perToolCounts={perToolCounts}
          remainingSeeds={remainingSeeds}
          seedsConsumed={usageQuery.data?.seedsConsumed}
          seedsIncluded={usageQuery.data?.seedsIncluded}
          overQuota={overQuota}
          cost={cost}
          eta={eta}
        />
      );
    }

    // review step: summarize the input per kind: backbone id, sequence count,
    // co-fold pair, or target name.
    const seqCount = sequences.sequences.length;
    const reviewTargetName =
      inputKind === "complex"
        ? complex.targetPdb.trim().toUpperCase() || "N/A"
        : inputKind === "backbone"
          ? backbone.pdb.trim().toUpperCase() ||
            (backbone.uploadKey ? "Uploaded backbone" : "N/A")
          : inputKind === "sequences"
            ? `${seqCount} sequence${seqCount === 1 ? "" : "s"}`
            : (selectedTarget?.name ?? "N/A");
    const reviewTargetSub =
      inputKind === "complex"
        ? `${complex.targetChain ? `chain ${complex.targetChain} · ` : ""}co-fold with ${complex.partnerPdb.trim().toUpperCase()}${complex.partnerChain ? ` chain ${complex.partnerChain}` : ""}`
        : inputKind === "backbone"
          ? backbone.chain
            ? `chain ${backbone.chain}`
            : undefined
          : inputKind === "sequences"
            ? undefined
            : selectedTarget
              ? `${selectedTarget.pdbId ?? targetPdb}${selectedTarget.chain ? ` · chain ${selectedTarget.chain}` : ""}`
              : undefined;
    const reviewRows = selectedWorkflow
      ? [
          {
            toolId: selectedWorkflow.id,
            name: selectedWorkflow.name,
            count: totalDesigns,
          },
        ]
      : selectedToolIds.map((id) => ({
          toolId: id,
          name: toolNameMap[id] ?? id,
          count: perToolCounts[id] ?? 0,
        }));
    return (
      <div className="space-y-6">
        <StepIntro
          title="Review job"
          sub="Check your inputs and estimated cost before running."
        />
        <NewJobReview
          runNoun={runNounPlural}
          targetName={reviewTargetName}
          targetSub={reviewTargetSub}
          rows={reviewRows}
          cost={cost}
          etaSeconds={eta.etaSeconds}
          strategy={strategy}
          failedTools={failedTools}
        />
        <PreSubmitSummary
          runNoun={runNounPlural}
          cost={{
            loading: reviewPreview.isLoading && primaryToolId.length > 0,
            unavailable: Boolean(reviewPreview.error),
            estimatedUsd: reviewPreview.data?.estimatedUsd,
            capUsd: reviewPreview.data?.capUsd,
            remainingUsd: reviewPreview.data?.remainingUsd,
            wouldExceed: reviewPreview.data?.wouldExceed,
            forToolName:
              selectedWorkflow?.name ?? toolNameMap[primaryToolId] ?? primaryToolId,
            partial: reviewRows.length > 1,
          }}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1180px] space-y-8">
      <header>
        <Link href="/app/tools" className="text-sm text-graphite hover:text-ink">← All tools</Link>
        <h1 className="mt-4 font-display text-display-md text-ink">{selectedTools.length === 1 && step > 0 ? `Run ${selectedTools[0]!.name}` : "New job"}</h1>
      </header>

      <JobWizard
        steps={STEPS}
        currentIndex={step}
        onBack={handleBack}
        onNext={handleNext}
        nextLabel={
          isLast
            ? `Run ${cost.totalDesigns.toLocaleString("en-US")} ${cost.totalDesigns === 1 ? runNounPlural.replace(/s$/, "") : runNounPlural}`
            : step === 0 ? "Set up inputs →" : step === 1 ? "Choose run size →" : "Review job →"
        }
        nextDisabled={!stepValid(step)}
        busy={submitting}
        hideNavigation={creatingTarget}
      >
        {renderStep()}
      </JobWizard>
    </div>
  );
}

export default function NewJobPage() {
  return (
    <Suspense
      fallback={
        <div className="font-sans text-[14px] text-graphite">Loading…</div>
      }
    >
      <NewJobWizard />
    </Suspense>
  );
}
