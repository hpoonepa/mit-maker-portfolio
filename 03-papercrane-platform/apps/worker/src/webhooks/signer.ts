/**
 * HMAC-SHA256 signer for outbound webhooks.
 *
 * Signature format matches Stripe so user-side libraries are portable:
 *
 *   X-PaperCrane-Signature: t=<unix-seconds>,v1=<hex>
 *
 * where `hex = HMAC_SHA256(secret, `${t}.${rawBody}`)`. Including `t` inside
 * the HMAC input prevents an attacker from replaying a captured signature
 * against a different timestamp header.
 *
 * Verification uses `crypto.timingSafeEqual` to avoid leaking the signature
 * via response-time side channels.
 */

import crypto from 'node:crypto';

export interface SignOptions {
  /** Unix-seconds timestamp. Injected for deterministic tests. */
  timestamp?: number;
}

/** Produce the `X-PaperCrane-Signature` header value for a raw body. */
export function signPayload(rawBody: string, secret: string, opts: SignOptions = {}): string {
  const t = opts.timestamp ?? Math.floor(Date.now() / 1000);
  const v1 = crypto.createHmac('sha256', secret).update(`${t}.${rawBody}`).digest('hex');
  return `t=${t},v1=${v1}`;
}

export interface ParsedSignatureHeader {
  timestamp: number;
  /** All v1 signatures present (Stripe supports multiple for rotation). */
  signatures: string[];
}

/**
 * Parse `t=<n>,v1=<hex>[,v1=<hex>...]`. Returns `null` if the required `t=`
 * segment is missing or not numeric. Unknown scheme labels are ignored.
 */
export function parseSignatureHeader(header: string): ParsedSignatureHeader | null {
  const parts = header.split(',');
  let timestamp: number | null = null;
  const signatures: string[] = [];

  for (const raw of parts) {
    const [k, v] = raw.split('=');
    if (!k || v === undefined) continue;
    if (k === 't') {
      const n = Number.parseInt(v, 10);
      if (Number.isFinite(n) && /^\d+$/.test(v)) timestamp = n;
    } else if (k === 'v1') {
      signatures.push(v);
    }
  }

  if (timestamp === null) return null;
  return { timestamp, signatures };
}

/**
 * Timing-safe verification. Returns `false` (never throws) for malformed
 * headers so callers can treat all failures uniformly.
 */
export function verifySignature(rawBody: string, secret: string, header: string): boolean {
  const parsed = parseSignatureHeader(header);
  if (!parsed || parsed.signatures.length === 0) return false;

  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${parsed.timestamp}.${rawBody}`)
    .digest('hex');
  const expectedBuf = Buffer.from(expected, 'hex');

  for (const sig of parsed.signatures) {
    // `timingSafeEqual` throws on length mismatch — guard first.
    let sigBuf: Buffer;
    try {
      sigBuf = Buffer.from(sig, 'hex');
    } catch {
      continue;
    }
    if (sigBuf.length !== expectedBuf.length) continue;
    if (crypto.timingSafeEqual(sigBuf as Uint8Array, expectedBuf as Uint8Array)) return true;
  }
  return false;
}
