import { describe, expect, it } from "vitest";

import { resolveApiProxyTarget } from "./vite.config";

describe("Vite API proxy target", () => {
  it("uses the launcher's allowlisted loopback API origin including a custom port", () => {
    expect(resolveApiProxyTarget({
      SQUASHVISION_API_ORIGIN: "http://127.0.0.1:43127",
    })).toBe("http://127.0.0.1:43127");
  });

  it("rejects non-loopback, credentialed, and path-bearing API origins", () => {
    expect(() => resolveApiProxyTarget({
      SQUASHVISION_API_ORIGIN: "http://api.example.test:8765",
    })).toThrow(/loopback/);
    expect(() => resolveApiProxyTarget({
      SQUASHVISION_API_ORIGIN: "http://user@127.0.0.1:8765",
    })).toThrow(/credentials/);
    expect(() => resolveApiProxyTarget({
      SQUASHVISION_API_ORIGIN: "http://127.0.0.1:8765/api",
    })).toThrow(/origin without a path/);
  });
});
