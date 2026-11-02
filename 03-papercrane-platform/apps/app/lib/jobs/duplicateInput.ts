import type { Target } from "@papercrane/types";
import type { BackboneValue } from "@/components/jobs/BackboneInput";
import type { ComplexInput } from "@/components/jobs/ComplexInputStep";
import type { LigandValue } from "@/components/jobs/LigandInput";
import { parseSequences, type SequenceValue } from "@/components/jobs/SequenceInput";

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === "string" ? value : "";

/** Rehydrate authenticated job inputs without serializing them into a URL. */
export function duplicateInput(params: Record<string, unknown> | null | undefined, targets: Target[]) {
  const raw = object(params);
  const request = raw.request ? object(raw.request) : raw;
  const tool = object(request.toolParams);
  const targetPdb = text(request.targetPdb ?? tool.targetPdb);
  const chain = text(request.targetChain ?? tool.targetChain ?? tool.target_chain);
  const target = targets.find(t => t.id === tool.targetId) ?? targets.find(t =>
    targetPdb && (t.pdbId === targetPdb || t.artifactKey === targetPdb) && (!chain || t.chain === chain));
  const backbone: BackboneValue = {
    pdb: targetPdb, chain,
    ...(!/^[a-z0-9]{4}$/i.test(targetPdb) && targetPdb ? { uploadKey: targetPdb } : {}),
  };
  const complex: ComplexInput = {
    targetPdb, targetChain: chain,
    partnerPdb: text(request.partnerPdb ?? tool.partnerPdb),
    partnerChain: text(request.partnerChain ?? tool.partnerChain ?? tool.partner_chain),
  };
  const entries = request.sequences ?? tool.sequences;
  const rawSequences = Array.isArray(entries) ? entries.map((entry, i) => {
    const row = object(entry);
    return `>${text(row.id) || `seq_${i + 1}`}\n${typeof entry === "string" ? entry : text(row.sequence)}`;
  }).join("\n") : text(tool.fasta ?? entries);
  const sequences: SequenceValue = { raw: rawSequences, sequences: parseSequences(rawSequences) };
  const ligand: LigandValue = tool.ligand_sdf ? { mode: "file", sdfKey: text(tool.ligand_sdf) }
    : tool.ligand ? { mode: "ccd", ccd: text(tool.ligand) } : { mode: "none" };
  const extras = Object.fromEntries(["hotspots", "constraints", "lengthRange"].flatMap(key =>
    request[key] !== undefined ? [[key, request[key]]] : []));
  return { targetId: target?.id ?? null, targetPdb, backbone, complex, sequences, ligand,
    projectId: text(tool.projectId), toolParams: tool, extras,
    seeds: Array.isArray(request.seeds) ? request.seeds.filter((s): s is number => Number.isInteger(s)) : [],
  };
}
