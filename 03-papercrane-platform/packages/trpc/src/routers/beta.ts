/**
 * Beta router — invite-code gate, admin code generation, changelog cursor.
 *
 * Wave 15 ships Paper Crane as an invite-only private beta. This router is
 * the tRPC surface area for that program:
 *
 *   - `validateInvite({ code })`        public; called from /signup before submit
 *   - `claimInvite({ code? })`          authed; called by /auth/callback after Supabase signUp
 *   - `accessStatus()`                  authed; durable private-beta admission state
 *   - `listMyInvites()`                 admin/owner; lists codes the caller generated
 *   - `generateInvite({ … })`           admin/owner; mints N codes
 *   - `markChangelogSeen({ version })`  authed; updates `users.last_changelog_seen`
 *
 * Code format
 * -----------
 *   PC-XXXX-XXXX where each X ∈ [A-Z0-9]. Generated with `crypto.randomBytes`
 *   and a 32-character alphabet that omits I/O/0/1 to reduce transcription
 *   errors when admins share codes via Slack/email.
 *
 * Concurrency / atomicity
 * -----------------------
 *   The claim path is an atomic conditional UPDATE:
 *
 *     UPDATE beta_invites
 *        SET used_count = used_count + 1,
 *            used_by_user_id = COALESCE(used_by_user_id, $userId)
 *      WHERE code = $code
 *        AND (max_uses = 0 OR used_count < max_uses)
 *        AND (expires_at IS NULL OR expires_at > now())
 *      RETURNING id;
 *
 *   If two clients race the last seat on a single-use code, one of them
 *   gets 0 affected rows back and we reject with `INVITE_EXHAUSTED`.
 *
 * Logging
 * -------
 *   We deliberately never log the code itself — only the prefix or hash
 *   suffix. Treat invite codes like short-lived shared secrets.
 */
import { randomBytes } from 'node:crypto';
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Code format ────────────────────────────────────────────────────────────

/**
 * Crockford-ish alphabet: skip 0/1/I/O so codes survive whiteboard photos
 * and Slack DMs. 32 chars → 5 bits/char → 40 bits per 8-char half →
 * 8.8e23 collision space, which is ample for a private beta.
 */
const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const CODE_HALF_LEN = 4;

/** PC-XXXX-XXXX — 8 chars + 2 dashes + "PC-" = 13 chars total. */
const CODE_REGEX = /^PC-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}$/;

function generateCode(): string {
  // 8 random bytes → map each byte modulo alphabet length. The slight
  // modulo bias (256 mod 32 == 0) is exactly zero for this alphabet, so
  // the distribution is uniform.
  const bytes = randomBytes(CODE_HALF_LEN * 2);
  let out = 'PC-';
  for (let i = 0; i < CODE_HALF_LEN * 2; i++) {
    if (i === CODE_HALF_LEN) out += '-';
    out += CODE_ALPHABET[bytes[i]! % CODE_ALPHABET.length];
  }
  return out;
}

/** Normalise caller input: strip whitespace, uppercase. */
function normaliseCode(input: string): string {
  return input.trim().toUpperCase();
}

/** Mask all but the last 3 chars for safe logging. */
function maskCode(code: string): string {
  return `PC-****-***${code.slice(-3)}`;
}

// ─── Zod shapes ─────────────────────────────────────────────────────────────

const CodeInput = z.string().min(1).max(32);

const ValidateInput = z.object({ code: CodeInput }).strict();

const ValidateOutput = z.object({
  valid: z.boolean(),
  reason: z
    .enum(['ok', 'unknown', 'expired', 'exhausted', 'malformed'])
    .default('ok'),
  expiresAt: z.string().nullable(),
  maxUses: z.number().int().nonnegative(),
  usesRemaining: z.number().int().nonnegative(),
});

const ClaimInput = z.object({ code: CodeInput.optional() }).strict();

const ClaimOutput = z.object({
  ok: z.boolean(),
  reason: z
    .enum(['ok', 'required', 'unknown', 'expired', 'exhausted', 'malformed'])
    .default('ok'),
});

const AccessStatusOutput = z.object({ granted: z.boolean() });

const GenerateInput = z
  .object({
    count: z.number().int().min(1).max(100),
    maxUses: z.number().int().min(0).max(10_000).default(1),
    expiresInDays: z.number().int().min(1).max(365).optional(),
    note: z.string().max(120).optional(),
  })
  .strict();

const InviteRow = z.object({
  id: z.string(),
  code: z.string(),
  maxUses: z.number().int(),
  usedCount: z.number().int(),
  expiresAt: z.string().nullable(),
  note: z.string().nullable(),
  createdAt: z.string(),
});

const GenerateOutput = z.object({ codes: z.array(InviteRow) });
const ListOutput = z.object({ codes: z.array(InviteRow) });

const MarkChangelogInput = z.object({ version: z.string().min(1).max(64) }).strict();

// ─── DB row shapes ──────────────────────────────────────────────────────────

type DbInvite = {
  id: string;
  code: string;
  max_uses: number;
  used_count: number;
  expires_at: Date | null;
  note: string | null;
  created_at: Date;
};

function rowToApi(row: DbInvite) {
  return {
    id: row.id,
    code: row.code,
    maxUses: row.max_uses,
    usedCount: row.used_count,
    expiresAt: row.expires_at ? row.expires_at.toISOString() : null,
    note: row.note,
    createdAt: row.created_at.toISOString(),
  };
}

// ─── Admin gate ─────────────────────────────────────────────────────────────

/**
 * Throws unless the caller is `admin` or `owner` on *any* org. Beta admin
 * is a global concept right now — we deliberately do not bind it to a
 * single designated org so the team can be split across multiple workspaces.
 *
 * If/when we need finer-grained gating, swap this for a `is_beta_admin`
 * column on `users` or a hard-coded list in env.
 */
async function assertBetaAdmin(ctx: {
  prisma: typeof import('@papercrane/db').prisma;
  withRlsUser: (
    p: typeof import('@papercrane/db').prisma,
    u: string,
    fn: (tx: import('@papercrane/db').Prisma.TransactionClient) => Promise<unknown>,
  ) => Promise<unknown>;
  auth: { userId: string };
}): Promise<void> {
  const userId = ctx.auth.userId;
  const rows = (await ctx.withRlsUser(ctx.prisma, userId, async (tx) => {
    return tx.$queryRawUnsafe<Array<{ role: string }>>(
      `SELECT role FROM org_members WHERE user_id = $1::uuid AND role IN ('admin','owner') LIMIT 1`,
      userId,
    );
  })) as Array<{ role: string }>;
  if (rows.length === 0) {
    throw new TRPCError({ code: 'FORBIDDEN', message: 'beta admin required' });
  }
}

// ─── Router ─────────────────────────────────────────────────────────────────

export const betaRouter = router({
  /**
   * Public — validates an invite code from the /signup form.
   *
   * Does NOT consume the code. The signup flow calls `claimInvite`
   * after Supabase confirms the new user, so validation can be done
   * pre-submit without burning a single-use code on a typo'd password.
   */
  validateInvite: publicProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/beta/validate-invite',
        tags: ['beta'],
        summary: 'Check whether an invite code is currently usable',
      },
    })
    .input(ValidateInput)
    .output(ValidateOutput)
    .mutation(async ({ ctx, input }) => {
      const code = normaliseCode(input.code);
      if (!CODE_REGEX.test(code)) {
        return {
          valid: false,
          reason: 'malformed' as const,
          expiresAt: null,
          maxUses: 0,
          usesRemaining: 0,
        };
      }

      // Service-role read — no RLS user binding because the signup flow
      // is unauthenticated. The query is constant-shape and bound, so
      // there's no injection risk; the response is deliberately terse.
      const rows = await ctx.prisma.$queryRawUnsafe<
        Array<{
          max_uses: number;
          used_count: number;
          expires_at: Date | null;
        }>
      >(
        `SELECT max_uses, used_count, expires_at
           FROM beta_invites
          WHERE code = $1
          LIMIT 1`,
        code,
      );

      const row = rows[0];
      if (!row) {
        return {
          valid: false,
          reason: 'unknown' as const,
          expiresAt: null,
          maxUses: 0,
          usesRemaining: 0,
        };
      }

      const now = ctx.now();
      if (row.expires_at && row.expires_at <= now) {
        return {
          valid: false,
          reason: 'expired' as const,
          expiresAt: row.expires_at.toISOString(),
          maxUses: row.max_uses,
          usesRemaining: 0,
        };
      }

      // maxUses === 0 means unlimited.
      const remaining =
        row.max_uses === 0 ? Number.MAX_SAFE_INTEGER : row.max_uses - row.used_count;
      if (remaining <= 0) {
        return {
          valid: false,
          reason: 'exhausted' as const,
          expiresAt: row.expires_at ? row.expires_at.toISOString() : null,
          maxUses: row.max_uses,
          usesRemaining: 0,
        };
      }

      return {
        valid: true,
        reason: 'ok' as const,
        expiresAt: row.expires_at ? row.expires_at.toISOString() : null,
        maxUses: row.max_uses,
        usesRemaining: row.max_uses === 0 ? 0 : remaining,
      };
    }),

  /** Read the authenticated user's durable beta-admission state. */
  accessStatus: protectedProcedure
    .input(z.void())
    .output(AccessStatusOutput)
    .query(async ({ ctx }) => {
      const user = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) =>
          tx.user.findUnique({
            where: { id: ctx.auth.userId },
            select: { betaAccessGrantedAt: true },
          }),
      );
      return { granted: user?.betaAccessGrantedAt != null };
    }),

  /**
   * Atomically consume an invite and admit the authenticated user. Replaying
   * the callback is idempotent: an already-admitted user returns success
   * without consuming another use. Identity always comes from the verified
   * session; callers cannot claim a code on behalf of another user.
   */
  claimInvite: protectedProcedure
    .input(ClaimInput)
    .output(ClaimOutput)
    .mutation(async ({ ctx, input }) => {
      const userId = ctx.auth.userId;
      return ctx.prisma.$transaction(async (tx) => {
        const users = await tx.$queryRawUnsafe<
          Array<{ beta_access_granted_at: Date | null }>
        >(
          `SELECT beta_access_granted_at
             FROM users
            WHERE id = $1::uuid
            FOR UPDATE`,
          userId,
        );
        const user = users[0];
        if (!user) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'authenticated user profile is not ready',
          });
        }
        if (user.beta_access_granted_at) {
          return { ok: true, reason: 'ok' as const };
        }

        if (!input.code) return { ok: false, reason: 'required' as const };
        const code = normaliseCode(input.code);
        if (!CODE_REGEX.test(code)) {
          return { ok: false, reason: 'malformed' as const };
        }

        const updated = await tx.$queryRawUnsafe<Array<{ id: string }>>(
          `UPDATE beta_invites
              SET used_count = used_count + 1,
                  used_by_user_id = COALESCE(used_by_user_id, $2::uuid)
            WHERE code = $1
              AND (max_uses = 0 OR used_count < max_uses)
              AND (expires_at IS NULL OR expires_at > now())
            RETURNING id`,
          code,
          userId,
        );

        if (updated.length === 0) {
          const probe = await tx.$queryRawUnsafe<
            Array<{ max_uses: number; used_count: number; expires_at: Date | null }>
          >(
            `SELECT max_uses, used_count, expires_at
               FROM beta_invites
              WHERE code = $1
              LIMIT 1`,
            code,
          );
          if (probe.length === 0) {
            return { ok: false, reason: 'unknown' as const };
          }
          const invite = probe[0]!;
          if (invite.expires_at && invite.expires_at <= ctx.now()) {
            return { ok: false, reason: 'expired' as const };
          }
          return { ok: false, reason: 'exhausted' as const };
        }

        await tx.user.update({
          where: { id: userId },
          data: { betaAccessGrantedAt: ctx.now() },
        });
        return { ok: true, reason: 'ok' as const };
      });
    }),

  /**
   * Admin — list every code generated by the caller. We deliberately do
   * NOT include the actual code value of multi-use codes that other
   * admins generated; for now this only filters by `generated_by`.
   */
  listMyInvites: protectedProcedure
    .input(z.void())
    .output(ListOutput)
    .query(async ({ ctx }) => {
      await assertBetaAdmin({
        prisma: ctx.prisma,
        withRlsUser: ctx.withRlsUser as never,
        auth: { userId: ctx.auth.userId },
      });

      const rows = await ctx.prisma.$queryRawUnsafe<DbInvite[]>(
        `SELECT id, code, max_uses, used_count, expires_at, note, created_at
           FROM beta_invites
          WHERE generated_by = $1::uuid
          ORDER BY created_at DESC
          LIMIT 200`,
        ctx.auth.userId,
      );

      return { codes: rows.map(rowToApi) };
    }),

  /**
   * Admin — mint a fresh batch of codes. Returns them in the response
   * exactly once; the admin must copy them out (we don't email).
   *
   * Collision handling: per code we retry up to 3 times before giving
   * up. With a 40-bit half-space and an empty table the probability of
   * collision in a 100-code batch is < 1e-19, but if we ever pre-seed
   * a ton of codes we want graceful degradation.
   */
  generateInvite: protectedProcedure
    .input(GenerateInput)
    .output(GenerateOutput)
    .mutation(async ({ ctx, input }) => {
      await assertBetaAdmin({
        prisma: ctx.prisma,
        withRlsUser: ctx.withRlsUser as never,
        auth: { userId: ctx.auth.userId },
      });

      const expiresAt = input.expiresInDays
        ? new Date(ctx.now().getTime() + input.expiresInDays * 86_400_000)
        : null;

      const created: DbInvite[] = [];
      for (let i = 0; i < input.count; i++) {
        let inserted: DbInvite | null = null;
        for (let attempt = 0; attempt < 3 && !inserted; attempt++) {
          const code = generateCode();
          try {
            const rows = await ctx.prisma.$queryRawUnsafe<DbInvite[]>(
              `INSERT INTO beta_invites
                 (id, code, max_uses, expires_at, note, generated_by)
               VALUES (gen_random_uuid()::text, $1, $2, $3, $4, $5::uuid)
               RETURNING id, code, max_uses, used_count, expires_at, note, created_at`,
              code,
              input.maxUses,
              expiresAt,
              input.note ?? null,
              ctx.auth.userId,
            );
            inserted = rows[0] ?? null;
          } catch {
            // unique-violation on `code` — retry with a fresh value.
          }
        }
        if (!inserted) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'failed to generate unique code after 3 attempts',
          });
        }
        created.push(inserted);
      }

      return { codes: created.map(rowToApi) };
    }),

  /**
   * Authed — read the caller's `last_changelog_seen` cursor. Returned
   * directly to the WhatsNew client component so it can decide whether
   * to render. Cheap query, called once per dashboard mount.
   */
  getChangelogCursor: protectedProcedure
    .input(z.void())
    .output(z.object({ lastChangelogSeen: z.string().nullable() }))
    .query(async ({ ctx }) => {
      const userId = ctx.auth.userId;
      const rows = (await ctx.withRlsUser(ctx.prisma, userId, async (tx) => {
        return tx.$queryRawUnsafe<Array<{ last_changelog_seen: string | null }>>(
          `SELECT last_changelog_seen FROM users WHERE id = $1::uuid LIMIT 1`,
          userId,
        );
      })) as Array<{ last_changelog_seen: string | null }>;
      return { lastChangelogSeen: rows[0]?.last_changelog_seen ?? null };
    }),

  /**
   * Authed — write the most recent changelog version the caller has seen.
   * The WhatsNew modal calls this on dismiss; the dashboard layout reads
   * it back from `users.last_changelog_seen` to decide whether to pop
   * the modal again.
   */
  markChangelogSeen: protectedProcedure
    .input(MarkChangelogInput)
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const userId = ctx.auth.userId;
      await ctx.withRlsUser(ctx.prisma, userId, async (tx) => {
        await tx.$executeRawUnsafe(
          `UPDATE users SET last_changelog_seen = $1 WHERE id = $2::uuid`,
          input.version,
          userId,
        );
      });
      return { ok: true as const };
    }),
});

// ─── Test-only exports ─────────────────────────────────────────────────────
// The router doesn't expose these on the wire; they're imported by unit
// tests so we can exercise the format without round-tripping a procedure.
export const __testing = { generateCode, normaliseCode, maskCode, CODE_REGEX };
