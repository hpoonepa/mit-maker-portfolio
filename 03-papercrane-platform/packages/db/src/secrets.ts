import {
  createCipheriv,
  createDecipheriv,
  createSecretKey,
  randomBytes,
  type KeyObject,
} from "node:crypto";

const ENVELOPE_PREFIX = "pc-modal-v1";
const AAD = new TextEncoder().encode(ENVELOPE_PREFIX);

function parseKey(encodedKey: string | undefined): KeyObject {
  const value = encodedKey?.trim();
  if (!value) {
    throw new Error("MODAL_CREDENTIAL_ENCRYPTION_KEY is not configured");
  }

  const key = /^[0-9a-f]{64}$/i.test(value)
    ? Buffer.from(value, "hex")
    : Buffer.from(value, "base64");

  if (key.length !== 32) {
    throw new Error(
      "MODAL_CREDENTIAL_ENCRYPTION_KEY must be 32 bytes encoded as 64 hex characters or base64",
    );
  }
  return createSecretKey(Uint8Array.from(key));
}

export function isEncryptedModalSecret(value: string): boolean {
  return value.startsWith(`${ENVELOPE_PREFIX}.`);
}

export function encryptModalSecret(
  plaintext: string,
  encodedKey = process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY,
): string {
  if (!plaintext) throw new Error("Cannot encrypt an empty Modal token secret");

  const key = parseKey(encodedKey);
  const iv = Uint8Array.from(randomBytes(12));
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(AAD);
  const ciphertext =
    cipher.update(plaintext, "utf8", "base64url") +
    cipher.final("base64url");
  const tag = cipher.getAuthTag();

  return [
    ENVELOPE_PREFIX,
    Buffer.from(iv).toString("base64url"),
    tag.toString("base64url"),
    ciphertext,
  ].join(".");
}

export function decryptModalSecret(
  envelope: string,
  encodedKey = process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY,
): string {
  const [prefix, ivPart, tagPart, ciphertextPart, extra] = envelope.split(".");
  if (
    prefix !== ENVELOPE_PREFIX ||
    !ivPart ||
    !tagPart ||
    !ciphertextPart ||
    extra !== undefined
  ) {
    throw new Error("Stored Modal token secret is not a supported encrypted value");
  }

  const key = parseKey(encodedKey);
  try {
    const decipher = createDecipheriv(
      "aes-256-gcm",
      key,
      Uint8Array.from(Buffer.from(ivPart, "base64url")),
    );
    decipher.setAAD(AAD);
    decipher.setAuthTag(Uint8Array.from(Buffer.from(tagPart, "base64url")));
    return (
      decipher.update(ciphertextPart, "base64url", "utf8") +
      decipher.final("utf8")
    );
  } catch {
    throw new Error("Stored Modal token secret could not be decrypted");
  }
}
