import { describe, expect, it } from "vitest";
import {
  decryptModalSecret,
  encryptModalSecret,
  isEncryptedModalSecret,
} from "../src/secrets";

const KEY = Buffer.alloc(32, 7).toString("base64");

describe("Modal credential encryption", () => {
  it("round-trips a secret in a versioned authenticated envelope", () => {
    const encrypted = encryptModalSecret("as-super-secret", KEY);

    expect(isEncryptedModalSecret(encrypted)).toBe(true);
    expect(encrypted).not.toContain("as-super-secret");
    expect(decryptModalSecret(encrypted, KEY)).toBe("as-super-secret");
  });

  it("uses a fresh nonce for each encryption", () => {
    expect(encryptModalSecret("same", KEY)).not.toBe(
      encryptModalSecret("same", KEY),
    );
  });

  it("rejects tampering and the wrong key", () => {
    const encrypted = encryptModalSecret("as-super-secret", KEY);
    const otherKey = Buffer.alloc(32, 9).toString("base64");

    expect(() => decryptModalSecret(encrypted, otherKey)).toThrow(
      "could not be decrypted",
    );
    const parts = encrypted.split(".");
    parts[3] = `${parts[3]!.startsWith("A") ? "B" : "A"}${parts[3]!.slice(1)}`;
    expect(() => decryptModalSecret(parts.join("."), KEY)).toThrow(
      "could not be decrypted",
    );
  });

  it("rejects missing or malformed keys", () => {
    expect(() => encryptModalSecret("secret", undefined)).toThrow(
      "not configured",
    );
    expect(() => encryptModalSecret("secret", "too-short")).toThrow(
      "must be 32 bytes",
    );
  });
});
