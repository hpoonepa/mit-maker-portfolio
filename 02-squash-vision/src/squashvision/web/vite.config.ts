import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const DEFAULT_API_ORIGIN = "http://127.0.0.1:8765";
const LOOPBACK_HOSTS: Record<string, true> = { "127.0.0.1": true, "[::1]": true };

const runtimeEnvironment = (
  globalThis as typeof globalThis & {
    process?: { env?: Readonly<Record<string, string | undefined>> };
  }
).process?.env ?? {};

export function resolveApiProxyTarget(
  environment: Readonly<Record<string, string | undefined>> = runtimeEnvironment,
): string {
  const configured = environment.SQUASHVISION_API_ORIGIN ?? DEFAULT_API_ORIGIN;
  let target: URL;
  try {
    target = new URL(configured);
  } catch {
    throw new TypeError("SQUASHVISION_API_ORIGIN must be an absolute loopback HTTP origin");
  }
  if (target.protocol !== "http:" || LOOPBACK_HOSTS[target.hostname] !== true) {
    throw new TypeError("SQUASHVISION_API_ORIGIN must use an allowlisted loopback HTTP host");
  }
  if (target.username !== "" || target.password !== "") {
    throw new TypeError("SQUASHVISION_API_ORIGIN must not contain credentials");
  }
  if (target.pathname !== "/" || target.search !== "" || target.hash !== "") {
    throw new TypeError("SQUASHVISION_API_ORIGIN must be an origin without a path, query, or fragment");
  }
  if (target.port === "") {
    throw new TypeError("SQUASHVISION_API_ORIGIN must include the launcher-selected API port");
  }
  const port = Number(target.port);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new TypeError("SQUASHVISION_API_ORIGIN has an invalid API port");
  }
  return target.origin;
}

const apiProxyTarget = resolveApiProxyTarget();

export default defineConfig({
  plugins: [react()],
  test: {
    exclude: [
      "e2e/**",
      "node_modules/**",
      "dist/**",
      "test-results/**",
      "playwright-report/**",
    ],
  },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": apiProxyTarget,
    },
  },
  preview: {
    host: "127.0.0.1",
  },
});
