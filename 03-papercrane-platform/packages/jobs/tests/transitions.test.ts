import { describe, it, expect } from 'vitest';
import {
  TRANSITIONS,
  transition,
  IllegalTransitionError,
} from '../src/transitions';
import { JobStatus, isTerminal, canTransition } from '../src/status';

describe('TRANSITIONS table', () => {
  it('defines an entry for every JobStatus', () => {
    const allStatuses: JobStatus[] = [
      'queued',
      'preparing',
      'running',
      'partial',
      'succeeded',
      'failed',
      'cancelling',
      'cancelled',
      'purged',
    ];
    for (const status of allStatuses) {
      expect(TRANSITIONS).toHaveProperty(status);
    }
  });

  it('queued allows preparing and cancelled', () => {
    expect(TRANSITIONS.queued).toEqual(['preparing', 'cancelled']);
  });

  it('preparing allows running, failed, and cancelling', () => {
    expect(TRANSITIONS.preparing).toEqual(['running', 'failed', 'cancelling']);
  });

  it('running allows partial, succeeded, failed, cancelling', () => {
    expect(TRANSITIONS.running).toEqual([
      'partial',
      'succeeded',
      'failed',
      'cancelling',
    ]);
  });

  it('partial allows succeeded, failed, cancelling (continue path)', () => {
    expect(TRANSITIONS.partial).toEqual(['succeeded', 'failed', 'cancelling']);
  });

  it('cancelling allows cancelled', () => {
    expect(TRANSITIONS.cancelling).toEqual(['cancelled']);
  });

  it('succeeded allows purged (retention cron)', () => {
    expect(TRANSITIONS.succeeded).toEqual(['purged']);
  });

  it('failed allows queued (retry) and purged', () => {
    expect(TRANSITIONS.failed).toEqual(['queued', 'purged']);
  });

  it('cancelled is terminal (no transitions)', () => {
    expect(TRANSITIONS.cancelled).toEqual([]);
  });

  it('purged is terminal (no transitions)', () => {
    expect(TRANSITIONS.purged).toEqual([]);
  });
});

describe('transition() guard', () => {
  it('accepts every legal transition', () => {
    for (const [from, allowed] of Object.entries(TRANSITIONS) as [
      JobStatus,
      JobStatus[],
    ][]) {
      for (const next of allowed) {
        expect(() => transition(from, next)).not.toThrow();
        expect(transition(from, next)).toBe(next);
      }
    }
  });

  it('throws IllegalTransitionError for illegal transitions', () => {
    expect(() => transition('queued', 'succeeded')).toThrow(
      IllegalTransitionError,
    );
    expect(() => transition('succeeded', 'running')).toThrow(
      IllegalTransitionError,
    );
    expect(() => transition('cancelled', 'queued')).toThrow(
      IllegalTransitionError,
    );
    expect(() => transition('purged', 'queued')).toThrow(
      IllegalTransitionError,
    );
  });

  it('error message contains from and next status', () => {
    try {
      transition('queued', 'running');
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(IllegalTransitionError);
      expect((err as Error).message).toContain('queued');
      expect((err as Error).message).toContain('running');
    }
  });

  it('no-op self-transition is illegal (except where explicitly allowed)', () => {
    expect(() => transition('running', 'running')).toThrow();
    expect(() => transition('queued', 'queued')).toThrow();
  });
});

describe('isTerminal()', () => {
  it('returns true for succeeded, failed, cancelled, purged', () => {
    expect(isTerminal('succeeded')).toBe(true);
    expect(isTerminal('failed')).toBe(true);
    expect(isTerminal('cancelled')).toBe(true);
    expect(isTerminal('purged')).toBe(true);
  });

  it('returns false for non-terminal states', () => {
    expect(isTerminal('queued')).toBe(false);
    expect(isTerminal('preparing')).toBe(false);
    expect(isTerminal('running')).toBe(false);
    expect(isTerminal('partial')).toBe(false);
    expect(isTerminal('cancelling')).toBe(false);
  });
});

describe('canTransition()', () => {
  it('returns true for legal transitions', () => {
    expect(canTransition('queued', 'preparing')).toBe(true);
    expect(canTransition('preparing', 'failed')).toBe(true);
    expect(canTransition('running', 'succeeded')).toBe(true);
    expect(canTransition('failed', 'queued')).toBe(true);
  });

  it('returns false for illegal transitions', () => {
    expect(canTransition('queued', 'succeeded')).toBe(false);
    expect(canTransition('cancelled', 'queued')).toBe(false);
    expect(canTransition('purged', 'running')).toBe(false);
  });
});
