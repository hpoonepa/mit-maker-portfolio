import { describe, it, expect } from "vitest";

import {
  MAX_WEBHOOK_URL_LENGTH,
  validateWebhookUrl,
} from "./validateUrl";

describe("validateWebhookUrl: basics", () => {
  it("rejects empty input", () => {
    const r = validateWebhookUrl("", { isProduction: true });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("empty");
  });

  it("rejects whitespace-only input as empty", () => {
    const r = validateWebhookUrl("   \t\n", { isProduction: true });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("empty");
  });

  it("rejects non-https schemes", () => {
    for (const u of [
      "http://example.com/hook",
      "ftp://example.com/hook",
      "javascript:alert(1)",
      "file:///etc/passwd",
    ]) {
      const r = validateWebhookUrl(u, { isProduction: true });
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.error).toBe("not_https");
    }
  });

  it("rejects unparseable URLs", () => {
    const r = validateWebhookUrl("https://", { isProduction: true });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      // Either unparseable or forbidden_host: both are acceptable failures
      // here, what matters is we don't accept it.
      expect(["unparseable", "forbidden_host", "not_https"]).toContain(r.error);
    }
  });

  it("rejects URLs longer than 2048 chars", () => {
    const long = "https://example.com/" + "a".repeat(MAX_WEBHOOK_URL_LENGTH);
    const r = validateWebhookUrl(long, { isProduction: true });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("too_long");
  });

  it("accepts a plain https URL in production", () => {
    const r = validateWebhookUrl("https://hooks.example.com/abc", {
      isProduction: true,
    });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.url).toMatch(/^https:\/\//);
  });
});

describe("validateWebhookUrl: forbidden hosts in production", () => {
  const forbidden = [
    "https://localhost/hook",
    "https://LOCALHOST/hook",
    "https://127.0.0.1/hook",
    "https://0.0.0.0/hook",
    "https://my-mac.local/hook",
    "https://server.lab.local/hook",
    "https://169.254.169.254/latest", // link-local / metadata endpoint
    "https://10.0.0.5/hook",
    "https://192.168.1.10/hook",
    "https://172.16.0.9/hook",
    "https://172.31.255.254/hook",
  ];

  for (const url of forbidden) {
    it(`rejects ${url} in production`, () => {
      const r = validateWebhookUrl(url, { isProduction: true });
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.error).toBe("forbidden_host");
    });
  }

  it("allows edge IPs outside the private ranges", () => {
    // 172.15.x.x is NOT private; 172.32.x.x is NOT private.
    for (const url of [
      "https://172.15.0.1/hook",
      "https://172.32.0.1/hook",
      "https://8.8.8.8/hook",
    ]) {
      const r = validateWebhookUrl(url, { isProduction: true });
      expect(r.ok).toBe(true);
    }
  });
});

describe("validateWebhookUrl: dev mode relaxations", () => {
  it("allows localhost in non-production", () => {
    const r = validateWebhookUrl("https://localhost:3001/hook", {
      isProduction: false,
    });
    expect(r.ok).toBe(true);
  });

  it("allows .local hosts in non-production", () => {
    const r = validateWebhookUrl("https://dev.local/hook", {
      isProduction: false,
    });
    expect(r.ok).toBe(true);
  });

  it("still requires https in non-production", () => {
    const r = validateWebhookUrl("http://localhost:3001/hook", {
      isProduction: false,
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("not_https");
  });
});
