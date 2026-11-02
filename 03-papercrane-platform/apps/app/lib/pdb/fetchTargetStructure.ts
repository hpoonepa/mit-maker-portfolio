export type TargetStructureSource = {
  url: string;
  label: "uploaded structure" | "RCSB";
};

/**
 * Prefer the exact uploaded object, then fall back to the canonical RCSB
 * structure when an older upload has expired or been removed from storage.
 */
export function targetStructureSources(
  structureUrl: string | null,
  pdbId: string | null,
): TargetStructureSource[] {
  const sources: TargetStructureSource[] = [];
  if (structureUrl) {
    sources.push({ url: structureUrl, label: "uploaded structure" });
  }
  if (pdbId) {
    const url = `/api/pdb/${pdbId.toUpperCase()}?format=auto`;
    if (!sources.some((source) => source.url === url)) {
      sources.push({ url, label: "RCSB" });
    }
  }
  return sources;
}

export async function fetchTargetStructure(
  sources: TargetStructureSource[],
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<string> {
  let lastError: Error | null = null;

  for (const source of sources) {
    try {
      const response = await fetchImpl(source.url, { signal });
      if (!response.ok) {
        throw new Error(`${source.label} returned ${response.status}`);
      }
      const text = await response.text();
      if (!text.trim()) throw new Error(`${source.label} returned an empty file`);
      return text;
    } catch (error) {
      if ((error as Error).name === "AbortError") throw error;
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError ?? new Error("No structure source is available");
}
