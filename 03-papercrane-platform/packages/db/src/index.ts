/**
 * @papercrane/db — Prisma client singleton + type re-exports.
 *
 * Why a singleton:
 *   Next.js dev + turbopack hot-reload re-evaluates modules frequently. Each
 *   evaluation would otherwise build a new PrismaClient and leak DB
 *   connections until the pool is exhausted. Stashing the instance on
 *   globalThis under a namespaced key keeps one client per process.
 */
import { PrismaClient } from "@prisma/client";

const GLOBAL_KEY = "__papercranePrisma" as const;

type GlobalWithPrisma = typeof globalThis & {
  [GLOBAL_KEY]?: PrismaClient;
};

const globalForPrisma = globalThis as GlobalWithPrisma;

export const prisma: PrismaClient =
  globalForPrisma[GLOBAL_KEY] ??
  new PrismaClient({
    log: ["error", "warn"],
  });

// Cache unconditionally. A single PrismaClient per process is always the goal;
// the guard only matters in dev where hot-reload re-evaluates this module,
// but there's no downside to caching in prod either.
globalForPrisma[GLOBAL_KEY] = prisma;

// ── Re-exports ───────────────────────────────────────────────────────────────
export { Prisma, PrismaClient } from "@prisma/client";
export * from "./types";
export { setCurrentUser, withRlsUser } from "./rls";
export {
  decryptModalSecret,
  encryptModalSecret,
  isEncryptedModalSecret,
} from "./secrets";
