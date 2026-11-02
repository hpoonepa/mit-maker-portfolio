import { describe, it, expect } from 'vitest';
import {
  WebhookEventSchema,
  WebhookSubscriptionSchema,
} from '../src/webhook.js';

describe('WebhookEventSchema (discriminated union)', () => {
  const jobId = '550e8400-e29b-41d4-a716-446655440000';
  const at = '2026-04-23T10:00:00.000Z';

  it('accepts job.status event', () => {
    const e = WebhookEventSchema.parse({
      type: 'job.status',
      jobId,
      status: 'running',
      at,
    });
    expect(e.type).toBe('job.status');
  });

  it('accepts job.succeeded event', () => {
    const e = WebhookEventSchema.parse({
      type: 'job.succeeded',
      jobId,
      totalDesigns: 10,
      at,
    });
    expect(e.type).toBe('job.succeeded');
  });

  it('accepts job.failed event', () => {
    const e = WebhookEventSchema.parse({
      type: 'job.failed',
      jobId,
      message: 'tool crashed',
      at,
    });
    expect(e.type).toBe('job.failed');
  });

  it('accepts design.created event', () => {
    const e = WebhookEventSchema.parse({
      type: 'design.created',
      jobId,
      designId: '550e8400-e29b-41d4-a716-446655440001',
      at,
    });
    expect(e.type).toBe('design.created');
  });

  it('rejects unknown event type', () => {
    expect(() =>
      WebhookEventSchema.parse({ type: 'job.weird', jobId, at }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      WebhookEventSchema.parse({
        type: 'job.status',
        jobId,
        status: 'running',
        at,
        extra: 1,
      } as unknown),
    ).toThrow();
  });
});

describe('WebhookSubscriptionSchema', () => {
  const base = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    orgSlug: 'paper-crane',
    url: 'https://example.com/hook',
    events: ['job.status', 'job.succeeded'],
    secret: 'whsec_abc123',
    active: true,
    createdAt: '2026-04-23T10:00:00.000Z',
  };

  it('accepts a valid subscription', () => {
    const parsed = WebhookSubscriptionSchema.parse(base);
    expect(parsed.events).toContain('job.status');
  });

  it('rejects non-URL', () => {
    expect(() =>
      WebhookSubscriptionSchema.parse({ ...base, url: 'not-a-url' }),
    ).toThrow();
  });

  it('rejects empty events array', () => {
    expect(() =>
      WebhookSubscriptionSchema.parse({ ...base, events: [] }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      WebhookSubscriptionSchema.parse({ ...base, bonus: true } as unknown),
    ).toThrow();
  });
});
