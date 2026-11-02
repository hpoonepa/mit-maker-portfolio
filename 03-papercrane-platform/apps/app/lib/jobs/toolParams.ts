export type ParsedToolParams =
  | { value: Record<string, unknown>; error: null }
  | { value: null; error: string };

export function serializeToolParams(
  defaults: Record<string, unknown> | undefined,
): string {
  return JSON.stringify(defaults ?? {}, null, 2);
}

/** Parse the advanced-parameters editor while rejecting non-object JSON. */
export function parseToolParamsJson(raw: string): ParsedToolParams {
  const source = raw.trim();
  if (!source) return { value: {}, error: null };

  try {
    const parsed: unknown = JSON.parse(source);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, error: "Parameters must be a JSON object." };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch {
    return { value: null, error: "Enter valid JSON before continuing." };
  }
}

/**
 * User overrides go first so canonical identity/input values cannot be
 * replaced by the advanced editor.
 */
export function mergeToolParams(
  advanced: Record<string, unknown> | undefined,
  canonical: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  const safeAdvanced = Object.fromEntries(
    Object.entries(advanced ?? {}).filter(
      ([key]) =>
        ![
          "_papercrane",
          "params",
          "toolParams",
          "prevOutput",
          "seeds",
          "numDesigns",
          "num_designs",
          "num_seq_per_target",
        ].includes(key),
    ),
  );
  const merged = { ...safeAdvanced, ...(canonical ?? {}) };
  return Object.keys(merged).length > 0 ? merged : undefined;
}
