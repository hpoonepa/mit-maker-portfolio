/** Origin describes how a record was produced, not its scientific validity. */
export type DesignProvenance = 'real' | 'synthetic' | 'stub' | 'unknown';

export function normaliseDesignProvenance(value: unknown): DesignProvenance {
  const origin = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return origin === 'real' || origin === 'synthetic' || origin === 'stub'
    ? origin
    : 'unknown';
}
