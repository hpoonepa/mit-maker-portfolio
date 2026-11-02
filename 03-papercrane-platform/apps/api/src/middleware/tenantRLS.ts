import { withRlsUser, type PrismaClient } from "@papercrane/db";
import type { Prisma } from "@papercrane/db";
import type { FastifyRequest } from "fastify";
import { AuthError } from "@papercrane/auth";

/**
 * Tenant-scoped Prisma helper.
 *
 * The API connects as a service role that bypasses RLS at the database
 * level. To still get the safety net of our RLS policies, every handler that
 * touches tenant rows should run its queries inside an interactive
 * transaction with `SET LOCAL app.current_user = <uid>`.
 *
 * This module wraps {@link withRlsUser} so routes do not need to reach into
 * @papercrane/db directly and can instead say:
 *
 * ```ts
 * const jobs = await runWithTenant(req, prisma, (tx) =>
 *   tx.job.findMany({ where: { orgId: req.auth!.orgId } }),
 * );
 * ```
 *
 * For API-key principals we derive the "current user" from a deterministic
 * service identity — `00000000-0000-0000-0000-<apiKeyId slice>`. This is a
 * placeholder that will be replaced once api_keys -> users mapping is
 * finalized; for now it lets us still scope transactions without granting
 * access to user-bound RLS policies that expect a real uid.
 */

/**
 * Resolve the RLS-bound user id for the current request. API-key calls have
 * no user id in the DB sense; return the special `orgId` as a stand-in so
 * the transaction can still run (policies that key on `auth.uid()` will
 * return no rows, which is the intended behavior for API keys without a
 * human owner).
 */
export function resolveRlsUserId(req: FastifyRequest): string {
  const auth = req.auth;
  if (!auth) throw new AuthError("auth required", "auth_required");
  if (auth.kind === "user") return auth.userId;
  // API-key: fall back to the orgId so RLS at least evaluates consistently.
  return auth.orgId;
}

export async function runWithTenant<T>(
  req: FastifyRequest,
  prisma: PrismaClient,
  fn: (tx: Prisma.TransactionClient) => Promise<T>,
): Promise<T> {
  const userId = resolveRlsUserId(req);
  return withRlsUser(prisma, userId, fn);
}
