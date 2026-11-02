/**
 * Row-Level Security helpers.
 *
 * The API connects as a service role that has BYPASSRLS. To still benefit from
 * the policies defined in `prisma/migrations/*_enable_rls/migration.sql`, we
 * open a transaction, `SET LOCAL app.current_user = $uid`, and run all tenant
 * queries inside that transaction. The GUC is automatically cleared at commit
 * or rollback, so it cannot leak across requests.
 *
 * IMPORTANT: `SET LOCAL` does NOT accept bound parameters in Postgres. We
 * therefore validate the user id as a UUID before substituting it into the
 * statement via Prisma's tagged-template raw helper (which still parameterizes
 * the value; Postgres accepts a parameterized string and then casts it with
 * ::uuid). This makes the call injection-safe.
 */
import type { Prisma, PrismaClient } from "@prisma/client";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function assertUuid(value: string): void {
  if (!UUID_RE.test(value)) {
    throw new Error(`expected uuid, got: ${value}`);
  }
}

/**
 * Set the `app.current_user` GUC on an open transaction. Must be called
 * before any tenant-scoped query inside that tx.
 */
export async function setCurrentUser(
  tx: Prisma.TransactionClient,
  userId: string
): Promise<void> {
  assertUuid(userId);
  // Tagged-template form — Prisma parameterizes ${userId}. We cast the bound
  // text to uuid on the db side via set_config which accepts text values.
  // set_config(setting_name, new_value, is_local) — is_local=true == SET LOCAL.
  await tx.$executeRaw`SELECT set_config('app.current_user', ${userId}, true)`;
}

/**
 * Run `fn` inside an interactive transaction with the RLS current-user GUC set.
 * Use this from every API handler that needs tenant-scoped data.
 *
 * @example
 *   const jobs = await withRlsUser(prisma, req.auth.userId, (tx) =>
 *     tx.job.findMany({ where: { orgId } })
 *   );
 */
export async function withRlsUser<T>(
  prisma: PrismaClient,
  userId: string,
  fn: (tx: Prisma.TransactionClient) => Promise<T>
): Promise<T> {
  assertUuid(userId);
  return prisma.$transaction(
    async (tx) => {
      await setCurrentUser(tx, userId);
      return fn(tx);
    },
    // Supabase's transaction pooler can take several seconds to hand out a
    // connection after an idle period. Prisma's 2s default rejects otherwise
    // healthy request bursts before the pooled connection is ready.
    { maxWait: 10_000 },
  );
}
