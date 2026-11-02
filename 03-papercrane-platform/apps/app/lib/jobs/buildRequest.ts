import type { LigandSupport, ToolInputKind } from "@papercrane/types";
import type { ComplexInput } from "@/components/jobs/ComplexInputStep";
import {
  backboneRequestValue,
  type BackboneValue,
} from "@/components/jobs/BackboneInput";
import type { SequenceValue } from "@/components/jobs/SequenceInput";
import {
  ligandToolParams,
  type LigandValue,
} from "@/components/jobs/LigandInput";

export interface BuildRequestInput {
  inputKind: ToolInputKind | null;
  ligandReq: LigandSupport;
  ligand: LigandValue;
  complex: ComplexInput;
  backbone: BackboneValue;
  sequences: SequenceValue;
  /** The resolved `targetPdb` for the `target` kind (id or artifact key). */
  effectiveTargetPdb: string;
  /** Saved target chain for target-conditioned tools. */
  targetChain?: string | null;
  projectId?: string | null;
  targetId?: string | null;
}

export interface BuiltRequest {
  /** Per-kind fields: targetPdb / partnerPdb / chains. */
  fields: Record<string, unknown>;
  /** Canonical adapter params, including a mirror of per-kind input fields. */
  toolParams?: Record<string, unknown>;
}

/**
 * Builds the `jobs.submit` request body for the current wizard state.
 *
 * Kept out of the page component because it is pure, per-input-kind branching
 * with real correctness stakes: `targetPdb` must be present for
 * target/backbone/complex and ABSENT for sequence-only tools (which carry
 * their input in `toolParams.sequences` instead), and `targetId`/`projectId`
 * must travel so the server can resolve saved hotspots and file the job under
 * the originating project.
 */
export function buildJobRequest(input: BuildRequestInput): BuiltRequest {
  const {
    inputKind,
    ligandReq,
    ligand,
    complex,
    backbone,
    sequences,
    effectiveTargetPdb,
    targetChain,
    projectId,
    targetId,
  } = input;

  const toolParams: Record<string, unknown> = {};
  if (projectId) toolParams.projectId = projectId;
  if (targetId) toolParams.targetId = targetId;
  if (ligandReq !== "none") Object.assign(toolParams, ligandToolParams(ligand));
  if (inputKind === "sequences") toolParams.sequences = sequences.sequences;

  const fields: Record<string, unknown> =
    inputKind === "complex"
      ? {
          targetPdb: complex.targetPdb.trim(),
          partnerPdb: complex.partnerPdb.trim(),
          ...(complex.targetChain ? { targetChain: complex.targetChain } : {}),
          ...(complex.partnerChain
            ? { partnerChain: complex.partnerChain }
            : {}),
        }
      : inputKind === "backbone"
        ? {
            targetPdb: backboneRequestValue(backbone),
            ...(backbone.chain ? { targetChain: backbone.chain } : {}),
          }
        : inputKind === "sequences"
          ? {}
          : {
              targetPdb: effectiveTargetPdb,
              ...(targetChain ? { targetChain } : {}),
            };

  // Modal adapters consume a flattened params object, while the public API
  // keeps canonical fields at the DesignRequest top level. Mirror those
  // fields into toolParams so defaults/advanced values can never shadow the
  // actual wizard input when Python adapters merge the nested object.
  Object.assign(toolParams, fields);
  const canonicalChain =
    inputKind === "complex"
      ? complex.targetChain
      : inputKind === "backbone"
        ? backbone.chain
        : targetChain;
  if (canonicalChain) {
    Object.assign(toolParams, {
      targetChain: canonicalChain,
      target_chain: canonicalChain,
      chain: canonicalChain,
      chainId: canonicalChain,
    });
  }
  if (inputKind === "complex" && complex.partnerChain) {
    toolParams.partner_chain = complex.partnerChain;
  }

  return {
    fields,
    ...(Object.keys(toolParams).length > 0 ? { toolParams } : {}),
  };
}
