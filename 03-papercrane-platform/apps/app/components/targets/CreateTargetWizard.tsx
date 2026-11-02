"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { z } from "zod";
import { trpc } from "@/lib/trpc/client";
import { largestChain } from "@/lib/pdb/parse";
import { pdbIdSchema, headFetchPdb } from "@/lib/pdb/fetch";
import { uploadStructureFile } from "@/lib/pdb/upload";
import type { PdbDropZonePayload } from "@/components/upload/PdbDropZone";
import type { UploadPhase } from "@/components/upload/PdbUploadProgress";
import { EXAMPLE_JOB } from "@/lib/jobs/exampleJob";
import {
  Step1,
  Step2,
  Step3,
  Stepper,
  type Source,
} from "@/components/targets/CreateTargetWizardSteps";

// Re-exported so existing tests (and any other caller) keep importing Step3
// from this module after the step bodies moved to their own file.
export { Step3 } from "@/components/targets/CreateTargetWizardSteps";

const NameSchema = z
  .string()
  .trim()
  .min(
    2,
    "Give the target a name of at least 2 characters so you can find it later",
  )
  .max(80, "That name is too long: keep it under 80 characters");

export interface CreateTargetWizardProps {
  /** Optional project to attach the target to (preselected in step 2). */
  projectId?: string;
  /** Keep a caller’s job draft mounted when creating a target inline. */
  onCreated?: (targetId: string) => void | Promise<void>;
}

/**
 * Three-step wizard for creating a Target:
 *   1. Pick a source: RCSB id or file upload (paste-sequence is not wired)
 *   2. Configure: name, chain, project
 *   3. Confirm: show a summary, then submit
 *
 * Both live paths converge on the same pipeline: the RCSB path downloads the
 * structure through our same-origin `/api/pdb` proxy (never rcsb.org from the
 * browser) and then reuses the presign → PUT → server-side parse flow that a
 * manual upload uses, so the two produce identical Target rows.
 */
export function CreateTargetWizard({ projectId, onCreated }: CreateTargetWizardProps) {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [source, setSource] = useState<Source>("rcsb");

  // Upload-path state
  const [payload, setPayload] = useState<PdbDropZonePayload | null>(null);
  const [chain, setChain] = useState<string>("");
  const [name, setName] = useState<string>("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | "">(
    projectId ?? "",
  );
  const [pdbId, setPdbId] = useState<string>("");
  const [sequence, setSequence] = useState<string>("");

  const [phase, setPhase] = useState<UploadPhase>({ phase: "idle" });
  const [submitError, setSubmitError] = useState<string | null>(null);

  // tRPC
  const projectsQuery = trpc.projects.list.useQuery(
    { limit: 50 },
    { staleTime: 60_000 },
  );
  const getUploadUrl = trpc.targets.getUploadUrl.useMutation();
  const createFromUpload = trpc.targets.createFromUpload.useMutation();

  const parsed = payload?.validation.parsed ?? null;
  const parsedChains = useMemo(() => parsed?.chains ?? [], [parsed]);
  const chosenChain = useMemo(
    () => parsedChains.find((c) => c.id === chain) ?? null,
    [parsedChains, chain],
  );

  const onAccepted = (p: PdbDropZonePayload) => {
    setPayload(p);
    const best = largestChain(p.validation.parsed);
    setChain(best?.id ?? p.validation.parsed.chains[0]?.id ?? "");
    if (!name) {
      const suggested =
        p.validation.parsed.pdbId ??
        p.file.name.replace(/\.(pdb|ent|cif|mmcif)$/i, "");
      setName(suggested);
    }
  };

  /** One-click prefill of the known-good demo target (PD-L1 · 5O45). */
  const useExample = () => {
    setPdbId(EXAMPLE_JOB.targetPdb);
    setName(`${EXAMPLE_JOB.targetName} (${EXAMPLE_JOB.targetPdb})`);
    setSubmitError(null);
  };

  // ─── Friendly, specific validation ────────────────────────────────────────
  // Shown live under the field rather than waiting for a server rejection.
  const pdbParsed = pdbIdSchema.safeParse(pdbId);
  const pdbError =
    source === "rcsb" && pdbId.trim().length > 0 && !pdbParsed.success
      ? `"${pdbId.trim()}" isn't a PDB ID. They're four characters starting with a digit: for example ${EXAMPLE_JOB.targetPdb} (${EXAMPLE_JOB.targetName}).`
      : null;
  const nameParsed = NameSchema.safeParse(name);
  const nameError =
    name.trim().length > 0 && !nameParsed.success
      ? (nameParsed.error.issues[0]?.message ?? "That name won't work")
      : null;

  // Paste-sequence needs a structure-prediction step that isn't switched on,
  // so it can never advance: the card says so rather than dead-ending here.
  const canAdvanceFrom1 =
    (source === "upload" && !!payload) ||
    (source === "rcsb" && pdbParsed.success);

  const canAdvanceFrom2 =
    nameParsed.success && (source !== "upload" || !!chain);

  const busy =
    phase.phase === "signing" ||
    phase.phase === "uploading" ||
    phase.phase === "parsing";

  /**
   * Stream an already-acquired structure File through the wired upload
   * pipeline (presign → PUT → server-side parse + persist) and route to the
   * new target. Shared by the upload and RCSB paths.
   */
  const uploadAndCreate = async (
    file: File,
    validatedName: string,
    chainId?: string,
  ) => {
    const { uploadKey } = await uploadStructureFile({
      file,
      getSignedUrl: async ({ filename, contentLength }) => {
        const out = await getUploadUrl.mutateAsync({ filename, contentLength });
        return { url: out.url, uploadKey: out.uploadKey };
      },
      onProgress: (pct) => setPhase({ phase: "uploading", pct }),
    });

    setPhase({ phase: "parsing" });
    const result = await createFromUpload.mutateAsync({
      uploadKey,
      name: validatedName,
      projectId: selectedProjectId || undefined,
      chain: chainId || undefined,
    });

    setPhase({ phase: "done" });
    const id = (result.target as { id: string }).id;
    if (onCreated) await onCreated(id);
    else router.push(`/app/targets/${id}`);
  };

  const handleSubmit = async () => {
    setSubmitError(null);

    if (source === "sequence") {
      setSubmitError(
        "Starting from a raw sequence isn't switched on yet. Use an RCSB ID or upload a structure file instead.",
      );
      return;
    }

    const nameResult = NameSchema.safeParse(name);
    if (!nameResult.success) {
      setSubmitError(
        nameResult.error.issues[0]?.message ?? "Give the target a name first",
      );
      return;
    }

    // ── RCSB by ID ──────────────────────────────────────────────────────
    // Download the structure from RCSB via our same-origin /api/pdb proxy
    // (no CORS), then reuse the exact upload pipeline so the server parses
    // and persists it identically to a manual upload.
    if (source === "rcsb") {
      const idResult = pdbIdSchema.safeParse(pdbId);
      if (!idResult.success) {
        setSubmitError(
          `"${pdbId.trim()}" isn't a PDB ID. Try ${EXAMPLE_JOB.targetPdb} (${EXAMPLE_JOB.targetName}) if you just want to see this work.`,
        );
        return;
      }
      const validId = idResult.data;

      setPhase({ phase: "signing" });
      try {
        // Resolves cif→pdb with retries and surfaces typo'd IDs as 404s.
        const resolved = await headFetchPdb(validId, "auto");
        const res = await fetch(resolved.url);
        if (!res.ok) {
          throw new Error(
            `We reached RCSB but couldn't download ${validId} (status ${res.status}). Try again in a moment.`,
          );
        }
        const blob = await res.blob();
        const ext = resolved.format === "cif" ? "cif" : "pdb";
        const file = new File([blob], `${validId}.${ext}`, {
          type: "chemical/x-pdb",
        });

        await uploadAndCreate(file, nameResult.data);
      } catch (err) {
        const msg = friendlyTargetError(err, validId);
        setPhase({ phase: "error", message: msg });
        setSubmitError(msg);
      }
      return;
    }

    // ── File upload ─────────────────────────────────────────────────────
    if (!payload) return;
    setPhase({ phase: "signing" });
    try {
      await uploadAndCreate(payload.file, nameResult.data, chain || undefined);
    } catch (err) {
      const msg = friendlyTargetError(err);
      setPhase({ phase: "error", message: msg });
      setSubmitError(msg);
    }
  };

  return (
    <div className="space-y-6">
      {!onCreated && <Stepper step={step} />}

      {step === 1 && (
        <Step1
          source={source}
          setSource={setSource}
          payload={payload}
          onAccepted={onAccepted}
          pdbId={pdbId}
          setPdbId={setPdbId}
          sequence={sequence}
          setSequence={setSequence}
          pdbError={pdbError}
          onUseExample={useExample}
        />
      )}

      {step === 2 && (
        <Step2
          source={source}
          name={name}
          setName={setName}
          chain={chain}
          setChain={setChain}
          parsedChains={parsedChains}
          projects={projectsQuery.data?.items ?? []}
          selectedProjectId={selectedProjectId}
          setSelectedProjectId={setSelectedProjectId}
          nameError={nameError}
        />
      )}

      {step === 3 && (
        <Step3
          source={source}
          name={name}
          pdbId={pdbId}
          chain={chain}
          chosenChainSeq={chosenChain?.sequence ?? ""}
          chosenChainResidues={chosenChain?.residues.length ?? 0}
          payloadFilename={payload?.file.name ?? ""}
          payloadSize={payload?.file.size ?? 0}
          phase={phase}
          submitError={submitError}
        />
      )}

      <div className="flex items-center justify-between gap-3 pt-2">
        <button
          type="button"
          onClick={() => setStep((s) => (s > 1 ? ((s - 1) as 1 | 2) : 1))}
          disabled={step === 1 || busy}
          className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors disabled:opacity-40 disabled:hover:text-graphite"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>

        {step < 3 ? (
          <button
            type="button"
            onClick={() => {
              if (step === 1 && source === "rcsb" && !name.trim()) setName(pdbId.toUpperCase());
              setStep((s) => (s + 1) as 2 | 3);
            }}
            disabled={
              (step === 1 && !canAdvanceFrom1) ||
              (step === 2 && !canAdvanceFrom2)
            }
            className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
          >
            Continue
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={busy}
            className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
          >
            {busy ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Creating…
              </>
            ) : (
              <>
                {onCreated ? "Save target & return to job" : "Create target"}
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Rewrites the raw failure into something a non-scientist can act on. The
 * RCSB probe already produces friendly text for 404 / rate-limit / outage, so
 * those pass through; anything else gets a plain fallback rather than a stack
 * trace or a bare status code.
 */
function friendlyTargetError(err: unknown, pdbId?: string): string {
  const raw = err instanceof Error ? err.message : String(err);
  const lower = raw.toLowerCase();
  if (lower.includes("upload")) {
    return "We downloaded the structure, but couldn't save it to your workspace. Try again in a moment.";
  }
  if (lower.includes("not found")) {
    return `RCSB has no entry called ${pdbId ?? "that"}. Check the ID, or use ${EXAMPLE_JOB.targetPdb} (${EXAMPLE_JOB.targetName}) to see this work.`;
  }
  if (lower.includes("rate limit")) {
    return "RCSB is throttling us right now. Wait a few seconds and press Create target again.";
  }
  if (lower.includes("unavailable") || lower.includes("network")) {
    return "We couldn't reach RCSB just now. Check your connection and try again in a moment.";
  }
  if (lower.includes("too large") || lower.includes("size")) {
    return "That structure file is too large to upload. Try a single chain or a trimmed file.";
  }
  return raw || "We couldn't create the target. Try again.";
}
