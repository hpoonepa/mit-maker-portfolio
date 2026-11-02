// Load env from monorepo root .env.local before anything else reads process.env.
// The dev server runs from apps/api, but secrets (DATABASE_URL, REDIS_URL, ...)
// live in the repo-root .env.local that web/worker/app share. Without this,
// `loadConfig()` below sees an empty DATABASE_URL and /healthz reports db:false.
import { config as loadDotenv } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// src/server.ts -> ../../../.env.local resolves to <repo>/.env.local
loadDotenv({ path: path.resolve(__dirname, "../../../.env.local") });

import { initSentry } from "@papercrane/observability";
import {
  loadConfig,
  preferSessionPoolForDevServer,
} from "./config.js";
import { loadApiEnv } from "./env.js";

/**
 * Process entrypoint. Loads config, wires Sentry, builds the server and
 * listens on the configured port. Any startup error is logged and the
 * process exits non-zero so orchestrators (Fly, Docker) trigger a restart.
 *
 * Env validation runs FIRST — before `loadConfig`, before Sentry, before
 * Fastify. A missing `DATABASE_URL` should crash with a human-readable error
 * instead of surfacing as a Prisma connection failure five seconds later.
 * Pass `--check-env` to validate without booting (used by CI + Docker
 * healthchecks).
 */
async function main(): Promise<void> {
  // The local API is long-lived, so use the configured session pool. Import
  // the server only after selecting the URL; that import creates Prisma.
  preferSessionPoolForDevServer();

  // Crash-fast on bad env. `--check-env` exits 0/1 with a status banner.
  loadApiEnv(process.argv);

  const config = loadConfig();
  const { buildServer } = await import("./index.js");

  initSentry({
    dsn: config.sentryDsn,
    environment: config.sentryEnvironment ?? config.nodeEnv,
    tracesSampleRate: config.sentryTracesSampleRate,
  });

  const app = await buildServer({ config });

  const close = async (signal: string): Promise<void> => {
    app.log.info({ signal }, "shutting down");
    try {
      await app.close();
      process.exit(0);
    } catch (err) {
      app.log.error({ err }, "error during shutdown");
      process.exit(1);
    }
  };
  process.on("SIGTERM", () => void close("SIGTERM"));
  process.on("SIGINT", () => void close("SIGINT"));

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (err) {
    app.log.error({ err }, "failed to start API server");
    process.exit(1);
  }
}

void main();
