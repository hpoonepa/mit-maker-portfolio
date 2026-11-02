/**
 * @papercrane/trpc — shared tRPC surface.
 *
 * Consumed by:
 *   - `apps/web` as a first-class tRPC client
 *   - `apps/api` wrapped by `trpc-to-openapi` for REST + OpenAPI emission
 */
import { appRouter } from './routers/index.js';

export { appRouter, type AppRouter } from './routers/index.js';

/**
 * Factory used by the API's lazy tRPC mount (`apps/api/src/routes/trpc.ts`).
 * Returns the already-constructed `appRouter` — the factory shape lets the
 * API dynamic-import this package and stay decoupled from how the router is
 * built internally (e.g. if a future version needs per-request router config,
 * only this factory changes).
 */
export function createRouter(): typeof appRouter {
  return appRouter;
}
export {
  createContext,
  createInnerContext,
  type Context,
  type InnerContext,
  type CreateContextOptions,
  type CreateInnerContextOptions,
  type AuthContext,
  type UserAuth,
  type ApiKeyAuth,
  type EnqueueJobFn,
  type PublishCancelFn,
  type PresignGetFn,
  type PresignPutFn,
  type WithRlsUserFn,
} from './context.js';
export { t, router, publicProcedure, middleware, TRPCError } from './trpc.js';
export { requireAuth, requireScope, requireTier } from './middleware/auth.js';
export { rateLimit, type RateLimiter, type RateLimitOptions } from './middleware/rateLimit.js';
export {
  TIER_TOOL_ALLOWLIST,
  isToolAllowedForTier,
} from './config/tierTools.js';
export type { ToolCatalogEntry } from './routers/tools.js';
