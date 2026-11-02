/**
 * Catches targets a design tool physically cannot parse, before we spend a GPU
 * finding out.
 *
 * Verified failure this exists to prevent: PDB `2LGV` is a 20-model solution-NMR
 * ensemble. BoltzGen's mmCIF reader assumes a single model, so `parse_polymer`
 * dereferences `None` and the run dies with a bare
 * `TypeError: 'NoneType' object is not iterable` after the job has already been
 * queued, started, and billed. The same target as a single-model entry (e.g.
 * `5MV5`, cryo-EM, 1 model) completes normally in ~5 minutes.
 *
 * Only `deposited_model_count > 1` is treated as blocking, and only for the
 * tools listed in `MULTI_MODEL_INCOMPATIBLE`. Everything else is advisory --
 * we would rather let an unusual-but-workable target through than block a user
 * on a guess.
 */

/** Public RCSB metadata endpoint. Covered by the app CSP via `https://*.rcsb.org`. */
const RCSB_ENTRY_API = "https://data.rcsb.org/rest/v1/core/entry";

/**
 * Tools observed to crash on multi-model ensembles rather than picking model 1.
 * Keep this list to tools whose failure has actually been reproduced -- an
 * over-broad list blocks legitimate work.
 */
export const MULTI_MODEL_INCOMPATIBLE = new Set(["boltzgen"]);

export interface StructureSuitability {
  pdbId: string;
  /** e.g. "X-RAY DIFFRACTION", "SOLUTION NMR", "ELECTRON MICROSCOPY". */
  method: string | null;
  /** Deposited model count. NMR ensembles are typically 10-20. */
  modelCount: number | null;
  atomCount: number | null;
  /** True when the selected tool cannot parse this structure at all. */
  blocking: boolean;
  /** Plain-language explanation, or null when nothing is wrong. */
  warning: string | null;
}

const UNKNOWN: Omit<StructureSuitability, "pdbId"> = {
  method: null,
  modelCount: null,
  atomCount: null,
  blocking: false,
  warning: null,
};

/**
 * Look up structural metadata for a PDB ID and decide whether `toolSlug` can
 * use it.
 *
 * Network or parse failures resolve to a non-blocking "unknown" result: this is
 * a guard rail, not a gate, and RCSB being slow must never stop a submission.
 */
export async function fetchStructureSuitability(
  pdbId: string,
  toolSlug?: string,
  signal?: AbortSignal,
): Promise<StructureSuitability> {
  const id = pdbId.trim().toUpperCase();
  if (!/^[0-9A-Z]{4}$/.test(id)) {
    return { pdbId: id, ...UNKNOWN };
  }

  let payload: unknown;
  try {
    const res = await fetch(`${RCSB_ENTRY_API}/${id}`, { signal });
    if (!res.ok) return { pdbId: id, ...UNKNOWN };
    payload = await res.json();
  } catch {
    return { pdbId: id, ...UNKNOWN };
  }

  const doc = (payload ?? {}) as {
    exptl?: Array<{ method?: string }>;
    rcsb_entry_info?: {
      deposited_model_count?: number;
      deposited_atom_count?: number;
    };
  };

  const method = doc.exptl?.[0]?.method ?? null;
  const info = doc.rcsb_entry_info ?? {};
  const modelCount =
    typeof info.deposited_model_count === "number" ? info.deposited_model_count : null;
  const atomCount =
    typeof info.deposited_atom_count === "number" ? info.deposited_atom_count : null;

  return {
    pdbId: id,
    method,
    modelCount,
    atomCount,
    ...describeMultiModel(id, method, modelCount, toolSlug),
  };
}

function describeMultiModel(
  id: string,
  method: string | null,
  modelCount: number | null,
  toolSlug?: string,
): Pick<StructureSuitability, "blocking" | "warning"> {
  if (modelCount === null || modelCount <= 1) {
    return { blocking: false, warning: null };
  }

  const kind = method?.toUpperCase().includes("NMR")
    ? `an NMR ensemble with ${modelCount} models`
    : `a multi-model structure (${modelCount} models)`;

  if (toolSlug && MULTI_MODEL_INCOMPATIBLE.has(toolSlug)) {
    return {
      blocking: true,
      warning:
        `${id} is ${kind}. This tool can only read single-model structures and ` +
        `will fail partway through the run. Choose an X-ray or cryo-EM entry instead.`,
    };
  }

  return {
    blocking: false,
    warning:
      `${id} is ${kind}. Most design tools use only the first model, so results ` +
      `may not reflect the full ensemble.`,
  };
}

/**
 * Rewrites tool-internal structure-parsing crashes into something a
 * non-scientist can act on. Matches the signature seen in the failed job rather
 * than the tool name, since every mmCIF reader in the catalogue fails the same
 * way on the same inputs.
 */
export function friendlyStructureRuntimeError(raw: string): string | null {
  const lower = raw.toLowerCase();
  const isParseCrash =
    lower.includes("parse_polymer") ||
    lower.includes("parse_mmcif") ||
    lower.includes("mmcif_from_block");

  if (isParseCrash && lower.includes("nonetype")) {
    return (
      "The tool couldn't read that structure file. This usually means the target " +
      "is an NMR ensemble or has multiple models — try a single-model X-ray or " +
      "cryo-EM entry."
    );
  }
  if (isParseCrash) {
    return (
      "The tool couldn't parse that structure. Try a different target, or " +
      "re-upload the file in mmCIF format."
    );
  }
  return null;
}
