import { describe, expect, it, vi } from 'vitest';
import {
  MODAL_TOKEN_VALIDATION_TIMEOUT_MS,
  validateModalToken,
  type RunModalTokenInfo,
} from '../src/config/modalTokenValidation';

describe('validateModalToken', () => {
  it('accepts only a successful Modal CLI handshake', async () => {
    const run = vi.fn<RunModalTokenInfo>().mockResolvedValue({
      exitCode: 0,
      stderr: '',
      timedOut: false,
    });

    await expect(validateModalToken('ak-valid', 'as-valid', 'main', run)).resolves.toEqual({ ok: true });
    expect(run).toHaveBeenCalledWith({
      tokenId: 'ak-valid',
      tokenSecret: 'as-valid',
      environment: 'main',
      timeoutMs: MODAL_TOKEN_VALIDATION_TIMEOUT_MS,
    });
  });

  it.each(['Token not found', 'Token ID is malformed', 'Unauthenticated']) (
    'classifies an auth failure as rejected: %s',
    async (stderr) => {
      const run = vi.fn<RunModalTokenInfo>().mockResolvedValue({
        exitCode: 1,
        stderr,
        timedOut: false,
      });

      await expect(validateModalToken('ak-invalid', 'as-invalid', undefined, run)).resolves.toEqual({
        ok: false,
        reason: 'rejected',
      });
    },
  );

  it('reports timeouts and infrastructure failures as unavailable', async () => {
    const timedOut = vi.fn<RunModalTokenInfo>().mockResolvedValue({
      exitCode: null,
      stderr: '',
      timedOut: true,
    });
    const unavailable = vi.fn<RunModalTokenInfo>().mockResolvedValue({
      exitCode: 1,
      stderr: 'Could not connect to the Modal server',
      timedOut: false,
    });

    await expect(validateModalToken('ak-valid', 'as-valid', undefined, timedOut)).resolves.toEqual({
      ok: false,
      reason: 'unavailable',
    });
    await expect(validateModalToken('ak-valid', 'as-valid', undefined, unavailable)).resolves.toEqual({
      ok: false,
      reason: 'unavailable',
    });
  });
});
