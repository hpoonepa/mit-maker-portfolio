import { describe, it, expect } from 'vitest';
import {
  shouldRetry,
  backoffSeconds,
  MAX_RETRIES,
  INFRA_ERROR_CODES,
  USER_ERROR_CODES,
} from '../src/retry';
import type { JobError } from '../src/retry';

const infra = (code: (typeof INFRA_ERROR_CODES)[number]): JobError => ({
  code,
  message: 'infra failure',
});

const user = (code: (typeof USER_ERROR_CODES)[number]): JobError => ({
  code,
  message: 'user error',
});

describe('shouldRetry()', () => {
  it('retries infra errors up to MAX_RETRIES (3)', () => {
    expect(shouldRetry(infra('GPU_PREEMPT'), 1)).toBe(true);
    expect(shouldRetry(infra('GPU_PREEMPT'), 2)).toBe(true);
    expect(shouldRetry(infra('GPU_PREEMPT'), 3)).toBe(true);
  });

  it('does not retry infra errors beyond MAX_RETRIES', () => {
    expect(shouldRetry(infra('NETWORK_TIMEOUT'), 4)).toBe(false);
    expect(shouldRetry(infra('NETWORK_TIMEOUT'), 10)).toBe(false);
  });

  it('retries all known infra error codes', () => {
    for (const code of INFRA_ERROR_CODES) {
      expect(shouldRetry(infra(code), 1)).toBe(true);
    }
  });

  it('never retries user errors, even on attempt 1', () => {
    for (const code of USER_ERROR_CODES) {
      expect(shouldRetry(user(code), 1)).toBe(false);
      expect(shouldRetry(user(code), 2)).toBe(false);
    }
  });

  it('does not retry unknown error codes', () => {
    const unknown: JobError = {
      code: 'WEIRD_UNKNOWN_CODE' as never,
      message: 'huh',
    };
    expect(shouldRetry(unknown, 1)).toBe(false);
  });

  it('rejects attempt numbers < 1', () => {
    expect(shouldRetry(infra('GPU_PREEMPT'), 0)).toBe(false);
    expect(shouldRetry(infra('GPU_PREEMPT'), -1)).toBe(false);
  });

  it('MAX_RETRIES is 3', () => {
    expect(MAX_RETRIES).toBe(3);
  });
});

describe('backoffSeconds()', () => {
  it('returns 60s for attempt 1', () => {
    expect(backoffSeconds(1)).toBe(60);
  });

  it('returns 120s for attempt 2', () => {
    expect(backoffSeconds(2)).toBe(120);
  });

  it('returns 240s for attempt 3', () => {
    expect(backoffSeconds(3)).toBe(240);
  });

  it('caps at 600s for attempt 4+', () => {
    expect(backoffSeconds(4)).toBe(480);
    expect(backoffSeconds(5)).toBe(600);
    expect(backoffSeconds(6)).toBe(600);
    expect(backoffSeconds(100)).toBe(600);
  });

  it('grows monotonically up to cap', () => {
    let prev = 0;
    for (let a = 1; a <= 10; a++) {
      const v = backoffSeconds(a);
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });
});
