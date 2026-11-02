import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getApiBaseUrl, getPublicApiBaseUrl, getTrpcUrl } from "./shared";

beforeEach(() => {
  for (const key of ["API_BASE_URL", "API_URL", "NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_API_URL"]) vi.stubEnv(key, "");
  vi.stubEnv("NODE_ENV", "development");
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("API origin configuration", () => {
  it("uses canonical production API instead of a visitor's localhost", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(getTrpcUrl()).toBe("https://api.papercrane.bio/trpc");
    expect(getPublicApiBaseUrl()).toBe("https://api.papercrane.bio");
  });
  it("supports the deployed public API_URL alias", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/");
    expect(getTrpcUrl()).toBe("https://api.example.com/trpc");
  });
  it("preserves API_BASE_URL precedence when both public aliases are set", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://preferred.example.com");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://other.example.com");
    expect(getApiBaseUrl()).toBe("https://preferred.example.com");
  });
  it("uses server-only aliases only on the server", () => {
    vi.stubEnv("API_URL", "http://api.internal:8080");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");
    expect(getApiBaseUrl()).toBe("https://api.example.com");
    vi.stubGlobal("window", undefined);
    expect(getApiBaseUrl()).toBe("http://api.internal:8080");
    expect(getPublicApiBaseUrl()).toBe("https://api.example.com");
    vi.stubEnv("API_BASE_URL", "http://preferred.internal:8080");
    expect(getApiBaseUrl()).toBe("http://preferred.internal:8080");
  });
  it("skips malformed configuration and wrong Next.js dev ports", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:3002");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "not a url");
    expect(getApiBaseUrl()).toBe("http://localhost:3001");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8080/");
    expect(getApiBaseUrl()).toBe("http://127.0.0.1:8080");
  });
  it.each(["http://localhost:3001", "http://127.0.0.1:8080", "http://[::1]:8080"])("rejects production loopback %s", url => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", url);
    expect(getApiBaseUrl()).toBe("https://api.papercrane.bio");
  });
});
