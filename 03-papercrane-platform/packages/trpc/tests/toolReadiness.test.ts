import { describe, expect, it } from 'vitest';

import {
  BETA_RUNNABLE_TOOL_SLUGS,
  GA_TOOL_SLUGS,
  isToolRunnable,
  toolReleaseStatus,
} from '../src/config/toolReadiness.js';
import { isToolAllowedForTier, TIER_TOOL_ALLOWLIST } from '../src/config/tierTools.js';

describe('tool readiness', () => {
  it('keeps GA and beta-runnable status separate', () => {
    expect(GA_TOOL_SLUGS).toHaveLength(12);
    expect(BETA_RUNNABLE_TOOL_SLUGS).toHaveLength(39);
    expect(isToolRunnable('antifold')).toBe(true);
    expect(toolReleaseStatus('antifold')).toBe('beta');
    expect(toolReleaseStatus('boltz2')).toBe('ga');
  });

  it('keeps the explicit Germinal stub unavailable', () => {
    expect(isToolRunnable('germinal')).toBe(false);
    expect(toolReleaseStatus('germinal')).toBe('beta');
  });

  it('allows all open tools on free and keeps frontier tools gated', () => {
    expect(TIER_TOOL_ALLOWLIST.free).toHaveLength(49);
    expect(isToolAllowedForTier('free', 'foldseek')).toBe(true);
    expect(isToolAllowedForTier('pro', 'alphafold3')).toBe(false);
    expect(isToolAllowedForTier('frontier', 'alphafold3')).toBe(true);
  });
});
