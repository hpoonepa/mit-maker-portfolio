import { describe, it, expect } from 'vitest';
import {
  JobStatusSchema,
  JobEventSchema,
  JobSubmissionSchema,
  JobSummarySchema,
} from '../src/job.js';

describe('JobStatusSchema', () => {
  it('accepts every valid state-machine value', () => {
    const states = [
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
    for (const s of states) {
      expect(JobStatusSchema.parse(s)).toBe(s);
    }
  });

  it('rejects unknown status strings', () => {
    expect(() => JobStatusSchema.parse('done')).toThrow();
    expect(() => JobStatusSchema.parse('')).toThrow();
  });
});

describe('JobSubmissionSchema', () => {
  const base = {
    toolId: 'boltzgen',
    request: {
      targetPdb: '7K3Q',
      seeds: [0, 1],
      numDesigns: 2,
    },
  };

  it('accepts minimal submission', () => {
    const parsed = JobSubmissionSchema.parse(base);
    expect(parsed.toolId).toBe('boltzgen');
  });

  it('accepts submission with optional org/webhook', () => {
    const parsed = JobSubmissionSchema.parse({
      ...base,
      orgSlug: 'paper-crane',
      webhookUrl: 'https://example.com/hook',
      idempotencyKey: 'abc-123',
    });
    expect(parsed.orgSlug).toBe('paper-crane');
  });

  it('accepts a trusted workflow id', () => {
    const parsed = JobSubmissionSchema.parse({
      ...base,
      toolId: 'rfdiffusion',
      workflowId: 'binder-standard',
    });
    expect(parsed.workflowId).toBe('binder-standard');
  });

  it('rejects an arbitrary workflow id', () => {
    expect(() =>
      JobSubmissionSchema.parse({ ...base, workflowId: 'run-anything' }),
    ).toThrow();
  });

  it('rejects bad webhook URL', () => {
    expect(() =>
      JobSubmissionSchema.parse({ ...base, webhookUrl: 'not-a-url' }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      JobSubmissionSchema.parse({ ...base, foo: 'bar' } as unknown),
    ).toThrow();
  });
});

describe('JobSummarySchema', () => {
  const base = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    toolId: 'bindcraft',
    status: 'running',
    submittedAt: '2026-04-23T10:00:00.000Z',
    numDesigns: 10,
    completedDesigns: 3,
  };

  it('accepts a valid summary', () => {
    const parsed = JobSummarySchema.parse(base);
    expect(parsed.status).toBe('running');
  });

  it('rejects completedDesigns < 0', () => {
    expect(() =>
      JobSummarySchema.parse({ ...base, completedDesigns: -1 }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      JobSummarySchema.parse({ ...base, weird: 1 } as unknown),
    ).toThrow();
  });
});

describe('JobEventSchema (discriminated union)', () => {
  it('accepts a status event', () => {
    const e = JobEventSchema.parse({
      type: 'status',
      jobId: '550e8400-e29b-41d4-a716-446655440000',
      status: 'running',
      at: '2026-04-23T10:00:00.000Z',
    });
    expect(e.type).toBe('status');
  });

  it('accepts a design event', () => {
    const e = JobEventSchema.parse({
      type: 'design',
      jobId: '550e8400-e29b-41d4-a716-446655440000',
      designId: '550e8400-e29b-41d4-a716-446655440001',
      seed: 0,
      at: '2026-04-23T10:00:00.000Z',
    });
    expect(e.type).toBe('design');
  });

  it('accepts a progress event', () => {
    const e = JobEventSchema.parse({
      type: 'progress',
      jobId: '550e8400-e29b-41d4-a716-446655440000',
      completed: 3,
      total: 10,
      at: '2026-04-23T10:00:00.000Z',
    });
    expect(e.type).toBe('progress');
  });

  it('accepts an error event', () => {
    const e = JobEventSchema.parse({
      type: 'error',
      jobId: '550e8400-e29b-41d4-a716-446655440000',
      message: 'GPU OOM',
      retryable: true,
      at: '2026-04-23T10:00:00.000Z',
    });
    expect(e.type).toBe('error');
  });

  it('rejects unknown event type', () => {
    expect(() =>
      JobEventSchema.parse({
        type: 'magic',
        jobId: '550e8400-e29b-41d4-a716-446655440000',
        at: '2026-04-23T10:00:00.000Z',
      }),
    ).toThrow();
  });

  it('rejects extra keys on a branch (.strict())', () => {
    expect(() =>
      JobEventSchema.parse({
        type: 'status',
        jobId: '550e8400-e29b-41d4-a716-446655440000',
        status: 'running',
        at: '2026-04-23T10:00:00.000Z',
        bogus: true,
      } as unknown),
    ).toThrow();
  });
});
