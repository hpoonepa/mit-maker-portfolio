/**
 * HMAC signer tests.
 *
 * The signer matches Stripe's signing convention so downstream users can reuse
 * their existing verification helpers:
 *
 *   X-PaperCrane-Signature: t=<unix>,v1=<hex>
 *
 * where `hex = HMAC_SHA256(secret, `${unix}.${rawBody}`)`. `t` is included
 * inside the signed payload so replayed messages with a shifted timestamp
 * don't verify.
 */

import { describe, it, expect } from 'vitest';
import crypto from 'node:crypto';
import { signPayload, parseSignatureHeader, verifySignature } from '../../src/webhooks/signer';

describe('signPayload', () => {
  it('produces a Stripe-style header: t=<unix>,v1=<hex>', () => {
    const header = signPayload('body', 'secret', { timestamp: 1700000000 });
    expect(header).toMatch(/^t=1700000000,v1=[0-9a-f]{64}$/);
  });

  it('matches a known HMAC test vector', () => {
    // Manually computed: HMAC_SHA256('secret', '1700000000.body')
    const expected = crypto
      .createHmac('sha256', 'secret')
      .update('1700000000.body')
      .digest('hex');
    const header = signPayload('body', 'secret', { timestamp: 1700000000 });
    expect(header).toBe(`t=1700000000,v1=${expected}`);
  });

  it('different body produces different signature', () => {
    const a = signPayload('a', 'secret', { timestamp: 1 });
    const b = signPayload('b', 'secret', { timestamp: 1 });
    expect(a).not.toBe(b);
  });

  it('different secret produces different signature', () => {
    const a = signPayload('body', 'sec1', { timestamp: 1 });
    const b = signPayload('body', 'sec2', { timestamp: 1 });
    expect(a).not.toBe(b);
  });
});

describe('parseSignatureHeader', () => {
  it('extracts timestamp and v1 signature', () => {
    const parsed = parseSignatureHeader('t=1700000000,v1=abc123');
    expect(parsed).toEqual({ timestamp: 1700000000, signatures: ['abc123'] });
  });

  it('returns null on malformed header', () => {
    expect(parseSignatureHeader('garbage')).toBeNull();
    expect(parseSignatureHeader('t=notanumber,v1=abc')).toBeNull();
    expect(parseSignatureHeader('t=1,v2=abc')).toEqual({ timestamp: 1, signatures: [] });
  });
});

describe('verifySignature (timing-safe)', () => {
  it('returns true for a valid signature', () => {
    const header = signPayload('hello', 's3cr3t', { timestamp: 1700000000 });
    expect(verifySignature('hello', 's3cr3t', header)).toBe(true);
  });

  it('returns false when body has been tampered', () => {
    const header = signPayload('hello', 's3cr3t', { timestamp: 1700000000 });
    expect(verifySignature('hello!', 's3cr3t', header)).toBe(false);
  });

  it('returns false when secret is wrong', () => {
    const header = signPayload('hello', 's3cr3t', { timestamp: 1700000000 });
    expect(verifySignature('hello', 'wrong', header)).toBe(false);
  });

  it('returns false for a malformed header (does not throw)', () => {
    expect(verifySignature('hello', 's3cr3t', 'garbage')).toBe(false);
  });
});
