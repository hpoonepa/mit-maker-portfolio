import { afterEach, describe, expect, it } from "vitest";
import { encryptModalSecret } from "@papercrane/db";
import { loadOrgModalCredentials } from "../src/providers/modalCredentials";

const KEY = Buffer.alloc(32, 4).toString("base64");
const previousKey = process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY;

afterEach(() => {
  if (previousKey === undefined) delete process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY;
  else process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY = previousKey;
});

describe("loadOrgModalCredentials", () => {
  it("decrypts an authenticated stored secret", async () => {
    process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY = KEY;
    const prisma = {
      $queryRaw: async () => [
        {
          token_id: "ak-test",
          token_secret: encryptModalSecret("as-secret", KEY),
          workspace: "lab",
          environment: "main",
        },
      ],
    };

    await expect(
      loadOrgModalCredentials(prisma as never, "00000000-0000-0000-0000-000000000001"),
    ).resolves.toEqual({
      tokenId: "ak-test",
      tokenSecret: "as-secret",
      workspace: "lab",
      environment: "main",
    });
  });

  it("refuses a legacy plaintext row", async () => {
    process.env.MODAL_CREDENTIAL_ENCRYPTION_KEY = KEY;
    const prisma = {
      $queryRaw: async () => [
        {
          token_id: "ak-test",
          token_secret: "as-plaintext",
          workspace: null,
          environment: null,
        },
      ],
    };

    await expect(
      loadOrgModalCredentials(prisma as never, "00000000-0000-0000-0000-000000000001"),
    ).rejects.toThrow("still plaintext");
  });
});
