/**
 * Gravatar URL helper for member avatars.
 *
 * Gravatar requests an md5 hash of a normalised email address. We compute the
 * hash on the client (Web Crypto exposes SubtleCrypto via SHA-* only, not
 * MD5), so we ship a tiny, dependency-free MD5 implementation. It runs once
 * per row at first paint and the result memoises naturally via React state.
 *
 * Behaviour:
 *  - `?d=blank` returns a transparent 1×1 PNG when no Gravatar exists, so the
 *    initials fallback rendered behind the <img> stays visible.
 *  - `?s=64` is double the rendered size (32px) for retina sharpness.
 *
 * If the email is unknown we still return a deterministic URL: the
 * `d=identicon` fallback yields a stable geometric tile keyed on the email
 * which reads nicer than a question mark.
 */

const GRAVATAR_BASE = "https://www.gravatar.com/avatar";

export interface GravatarOptions {
  /** Pixel size to request (we render at half this for retina). Default 64. */
  size?: number;
  /** Default behaviour when no gravatar exists. Default `"identicon"`. */
  fallback?: "identicon" | "mp" | "blank" | "404" | "retro";
}

export function gravatarUrl(
  email: string | null | undefined,
  opts: GravatarOptions = {},
): string {
  const size = opts.size ?? 64;
  const fallback = opts.fallback ?? "identicon";
  const normalised = (email ?? "").trim().toLowerCase();
  const hash = md5(normalised);
  return `${GRAVATAR_BASE}/${hash}?s=${size}&d=${fallback}`;
}

// ─── md5 (RFC 1321): minimal, dependency-free, JS-only. ────────────────────
// Not security-critical; Gravatar themselves use MD5 by convention. This is
// the canonical "Joseph Myers" implementation, ported to TypeScript and
// shrunk to one screen. Inputs are short ASCII emails so we skip the
// utf16->utf8 hot-path optimisations.

function md5(input: string): string {
  const bytes = new TextEncoder().encode(input);
  const blocks: number[] = [];
  for (let i = 0; i < bytes.length; i++) {
    blocks[i >> 2] = (blocks[i >> 2] ?? 0) | (bytes[i]! << ((i % 4) * 8));
  }
  blocks[bytes.length >> 2] =
    (blocks[bytes.length >> 2] ?? 0) | (0x80 << ((bytes.length % 4) * 8));
  const lenIndex = ((bytes.length + 8) >> 6) * 16 + 14;
  blocks[lenIndex] = bytes.length * 8;

  let a = 0x67452301;
  let b = 0xefcdab89;
  let c = 0x98badcfe;
  let d = 0x10325476;

  for (let i = 0; i < blocks.length; i += 16) {
    const oa = a;
    const ob = b;
    const oc = c;
    const od = d;
    a = ff(a, b, c, d, blocks[i + 0] ?? 0, 7, -680876936);
    d = ff(d, a, b, c, blocks[i + 1] ?? 0, 12, -389564586);
    c = ff(c, d, a, b, blocks[i + 2] ?? 0, 17, 606105819);
    b = ff(b, c, d, a, blocks[i + 3] ?? 0, 22, -1044525330);
    a = ff(a, b, c, d, blocks[i + 4] ?? 0, 7, -176418897);
    d = ff(d, a, b, c, blocks[i + 5] ?? 0, 12, 1200080426);
    c = ff(c, d, a, b, blocks[i + 6] ?? 0, 17, -1473231341);
    b = ff(b, c, d, a, blocks[i + 7] ?? 0, 22, -45705983);
    a = ff(a, b, c, d, blocks[i + 8] ?? 0, 7, 1770035416);
    d = ff(d, a, b, c, blocks[i + 9] ?? 0, 12, -1958414417);
    c = ff(c, d, a, b, blocks[i + 10] ?? 0, 17, -42063);
    b = ff(b, c, d, a, blocks[i + 11] ?? 0, 22, -1990404162);
    a = ff(a, b, c, d, blocks[i + 12] ?? 0, 7, 1804603682);
    d = ff(d, a, b, c, blocks[i + 13] ?? 0, 12, -40341101);
    c = ff(c, d, a, b, blocks[i + 14] ?? 0, 17, -1502002290);
    b = ff(b, c, d, a, blocks[i + 15] ?? 0, 22, 1236535329);

    a = gg(a, b, c, d, blocks[i + 1] ?? 0, 5, -165796510);
    d = gg(d, a, b, c, blocks[i + 6] ?? 0, 9, -1069501632);
    c = gg(c, d, a, b, blocks[i + 11] ?? 0, 14, 643717713);
    b = gg(b, c, d, a, blocks[i + 0] ?? 0, 20, -373897302);
    a = gg(a, b, c, d, blocks[i + 5] ?? 0, 5, -701558691);
    d = gg(d, a, b, c, blocks[i + 10] ?? 0, 9, 38016083);
    c = gg(c, d, a, b, blocks[i + 15] ?? 0, 14, -660478335);
    b = gg(b, c, d, a, blocks[i + 4] ?? 0, 20, -405537848);
    a = gg(a, b, c, d, blocks[i + 9] ?? 0, 5, 568446438);
    d = gg(d, a, b, c, blocks[i + 14] ?? 0, 9, -1019803690);
    c = gg(c, d, a, b, blocks[i + 3] ?? 0, 14, -187363961);
    b = gg(b, c, d, a, blocks[i + 8] ?? 0, 20, 1163531501);
    a = gg(a, b, c, d, blocks[i + 13] ?? 0, 5, -1444681467);
    d = gg(d, a, b, c, blocks[i + 2] ?? 0, 9, -51403784);
    c = gg(c, d, a, b, blocks[i + 7] ?? 0, 14, 1735328473);
    b = gg(b, c, d, a, blocks[i + 12] ?? 0, 20, -1926607734);

    a = hh(a, b, c, d, blocks[i + 5] ?? 0, 4, -378558);
    d = hh(d, a, b, c, blocks[i + 8] ?? 0, 11, -2022574463);
    c = hh(c, d, a, b, blocks[i + 11] ?? 0, 16, 1839030562);
    b = hh(b, c, d, a, blocks[i + 14] ?? 0, 23, -35309556);
    a = hh(a, b, c, d, blocks[i + 1] ?? 0, 4, -1530992060);
    d = hh(d, a, b, c, blocks[i + 4] ?? 0, 11, 1272893353);
    c = hh(c, d, a, b, blocks[i + 7] ?? 0, 16, -155497632);
    b = hh(b, c, d, a, blocks[i + 10] ?? 0, 23, -1094730640);
    a = hh(a, b, c, d, blocks[i + 13] ?? 0, 4, 681279174);
    d = hh(d, a, b, c, blocks[i + 0] ?? 0, 11, -358537222);
    c = hh(c, d, a, b, blocks[i + 3] ?? 0, 16, -722521979);
    b = hh(b, c, d, a, blocks[i + 6] ?? 0, 23, 76029189);
    a = hh(a, b, c, d, blocks[i + 9] ?? 0, 4, -640364487);
    d = hh(d, a, b, c, blocks[i + 12] ?? 0, 11, -421815835);
    c = hh(c, d, a, b, blocks[i + 15] ?? 0, 16, 530742520);
    b = hh(b, c, d, a, blocks[i + 2] ?? 0, 23, -995338651);

    a = ii(a, b, c, d, blocks[i + 0] ?? 0, 6, -198630844);
    d = ii(d, a, b, c, blocks[i + 7] ?? 0, 10, 1126891415);
    c = ii(c, d, a, b, blocks[i + 14] ?? 0, 15, -1416354905);
    b = ii(b, c, d, a, blocks[i + 5] ?? 0, 21, -57434055);
    a = ii(a, b, c, d, blocks[i + 12] ?? 0, 6, 1700485571);
    d = ii(d, a, b, c, blocks[i + 3] ?? 0, 10, -1894986606);
    c = ii(c, d, a, b, blocks[i + 10] ?? 0, 15, -1051523);
    b = ii(b, c, d, a, blocks[i + 1] ?? 0, 21, -2054922799);
    a = ii(a, b, c, d, blocks[i + 8] ?? 0, 6, 1873313359);
    d = ii(d, a, b, c, blocks[i + 15] ?? 0, 10, -30611744);
    c = ii(c, d, a, b, blocks[i + 6] ?? 0, 15, -1560198380);
    b = ii(b, c, d, a, blocks[i + 13] ?? 0, 21, 1309151649);
    a = ii(a, b, c, d, blocks[i + 4] ?? 0, 6, -145523070);
    d = ii(d, a, b, c, blocks[i + 11] ?? 0, 10, -1120210379);
    c = ii(c, d, a, b, blocks[i + 2] ?? 0, 15, 718787259);
    b = ii(b, c, d, a, blocks[i + 9] ?? 0, 21, -343485551);

    a = add32(a, oa);
    b = add32(b, ob);
    c = add32(c, oc);
    d = add32(d, od);
  }
  return [a, b, c, d].map(toHex).join("");
}

function add32(x: number, y: number): number {
  return (x + y) | 0;
}
function rol(x: number, n: number): number {
  return (x << n) | (x >>> (32 - n));
}
function cmn(q: number, a: number, b: number, x: number, s: number, t: number) {
  return add32(rol(add32(add32(a, q), add32(x, t)), s), b);
}
function ff(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
  return cmn((b & c) | (~b & d), a, b, x, s, t);
}
function gg(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
  return cmn((b & d) | (c & ~d), a, b, x, s, t);
}
function hh(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
  return cmn(b ^ c ^ d, a, b, x, s, t);
}
function ii(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
  return cmn(c ^ (b | ~d), a, b, x, s, t);
}
function toHex(n: number): string {
  let out = "";
  for (let i = 0; i < 4; i++) {
    out +=
      ((n >> (i * 8 + 4)) & 0x0f).toString(16) +
      ((n >> (i * 8)) & 0x0f).toString(16);
  }
  return out;
}
