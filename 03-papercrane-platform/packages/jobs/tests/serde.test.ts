import { describe, it, expect } from 'vitest';
import { serializeEvent, deserializeEvent } from '../src/serde';
import {
  statusEvent,
  designEvent,
  progressEvent,
  errorEvent,
} from '../src/events';
import type { JobEvent } from '../src/events';

describe('serde round-trip', () => {
  it('round-trips a status event', () => {
    const ev = statusEvent('running');
    const wire = serializeEvent(ev);
    expect(typeof wire).toBe('string');
    const back = deserializeEvent(wire);
    expect(back).toEqual(ev);
  });

  it('round-trips every status value', () => {
    const statuses = [
      'queued',
      'preparing',
      'running',
      'partial',
      'succeeded',
      'failed',
      'cancelling',
      'cancelled',
      'purged',
    ] as const;
    for (const s of statuses) {
      const ev = statusEvent(s);
      expect(deserializeEvent(serializeEvent(ev))).toEqual(ev);
    }
  });

  it('round-trips a design event with metrics', () => {
    const ev = designEvent('design_abc123', 42, {
      iptm: 0.82,
      ipsae: 0.71,
      pae_interface: 4.5,
    });
    const back = deserializeEvent(serializeEvent(ev));
    expect(back).toEqual(ev);
  });

  it('round-trips a progress event', () => {
    const ev = progressEvent(17, 100);
    const back = deserializeEvent(serializeEvent(ev));
    expect(back).toEqual(ev);
  });

  it('round-trips an error event', () => {
    const ev = errorEvent(true, 'GPU preempted');
    const back = deserializeEvent(serializeEvent(ev));
    expect(back).toEqual(ev);
  });

  it('round-trips non-retryable error event', () => {
    const ev = errorEvent(false, 'Invalid PDB input');
    const back = deserializeEvent(serializeEvent(ev));
    expect(back).toEqual(ev);
  });

  it('serializes to valid JSON string', () => {
    const ev = statusEvent('running');
    const wire = serializeEvent(ev);
    expect(() => JSON.parse(wire)).not.toThrow();
  });

  it('deserializeEvent rejects malformed JSON', () => {
    expect(() => deserializeEvent('not json{{')).toThrow();
  });

  it('deserializeEvent rejects invalid schema', () => {
    expect(() => deserializeEvent('{"type":"unknown"}')).toThrow();
    expect(() =>
      deserializeEvent('{"type":"status","status":"not_a_status"}'),
    ).toThrow();
    expect(() => deserializeEvent('{"type":"progress"}')).toThrow();
    expect(() =>
      deserializeEvent('{"type":"design","designId":"x"}'),
    ).toThrow(); // missing seed, metrics
  });

  it('deserialized type matches JobEvent discriminated union', () => {
    const ev: JobEvent = statusEvent('succeeded');
    const back = deserializeEvent(serializeEvent(ev));
    if (back.type === 'status') {
      expect(back.status).toBe('succeeded');
    } else {
      throw new Error('expected status event');
    }
  });
});
