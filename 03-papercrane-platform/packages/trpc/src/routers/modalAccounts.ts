import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';
import { validateModalToken } from '../config/modalTokenValidation.js';
import { encryptModalSecret } from '@papercrane/db';

const protectedProcedure = publicProcedure.use(requireAuth);

const ModalAccountStatusSchema = z.object({
  connected: z.boolean(),
  tokenIdSuffix: z.string().nullable(),
  workspace: z.string().nullable(),
  environment: z.string().nullable(),
  lastValidatedAt: z.date().nullable(),
  lastError: z.string().nullable(),
  updatedAt: z.date().nullable(),
});

const ConnectInput = z
  .object({
    tokenId: z.string().trim().min(8).max(160),
    tokenSecret: z.string().trim().min(8).max(240),
    workspace: z.string().trim().max(120).optional(),
    environment: z.string().trim().max(120).optional(),
  })
  .strict();

function suffix(value: string): string {
  return value.length <= 6 ? value : value.slice(-6);
}

function assertModalTokenShape(input: z.infer<typeof ConnectInput>): void {
  if (!/^ak-[A-Za-z0-9._-]+$/.test(input.tokenId)) {
    throw new TRPCError({
      code: 'BAD_REQUEST',
      message: 'Modal token id must start with "ak-".',
    });
  }
  if (!/^as-[A-Za-z0-9._-]+$/.test(input.tokenSecret)) {
    throw new TRPCError({
      code: 'BAD_REQUEST',
      message: 'Modal token secret must start with "as-".',
    });
  }
  if (input.workspace && !/^[A-Za-z0-9._-]+$/.test(input.workspace)) {
    throw new TRPCError({
      code: 'BAD_REQUEST',
      message: 'Modal workspace contains unsupported characters.',
    });
  }
  if (input.environment && !/^[A-Za-z0-9._-]+$/.test(input.environment)) {
    throw new TRPCError({
      code: 'BAD_REQUEST',
      message: 'Modal environment contains unsupported characters.',
    });
  }
}

type ModalCredentialRow = {
  tokenId: string;
  workspace: string | null;
  environment: string | null;
  lastValidatedAt: Date | null;
  lastError: string | null;
  updatedAt: Date;
};

async function findCredential(ctx: {
  prisma: unknown;
  withRlsUser: <T>(prisma: unknown, userId: string, fn: (tx: unknown) => Promise<T>) => Promise<T>;
  auth: { userId: string; orgId: string };
}): Promise<ModalCredentialRow | null> {
  return ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx: unknown) => {
    const client = tx as {
      modalCredential?: {
        findUnique: (args: unknown) => Promise<ModalCredentialRow | null>;
      };
      $queryRawUnsafe?: <T = unknown>(query: string, ...values: unknown[]) => Promise<T>;
    };
    if (client.modalCredential?.findUnique) {
      return client.modalCredential.findUnique({
        where: { orgId: ctx.auth.orgId },
        select: {
          tokenId: true,
          workspace: true,
          environment: true,
          lastValidatedAt: true,
          lastError: true,
          updatedAt: true,
        },
      });
    }
    if (!client.$queryRawUnsafe) return null;
    const rows = await client.$queryRawUnsafe<ModalCredentialRow[]>(
      `SELECT token_id AS "tokenId",
              workspace,
              environment,
              last_validated_at AS "lastValidatedAt",
              last_error AS "lastError",
              updated_at AS "updatedAt"
       FROM modal_credentials
       WHERE org_id = $1::uuid
       LIMIT 1`,
      ctx.auth.orgId,
    );
    return rows?.[0] ?? null;
  });
}

export const modalAccountsRouter = router({
  status: protectedProcedure
    .input(z.void())
    .output(ModalAccountStatusSchema)
    .query(async ({ ctx }) => {
      const row = await findCredential(ctx as never);
      if (!row) {
        return {
          connected: false,
          tokenIdSuffix: null,
          workspace: null,
          environment: null,
          lastValidatedAt: null,
          lastError: null,
          updatedAt: null,
        };
      }
      return {
        connected: true,
        tokenIdSuffix: suffix(row.tokenId),
        workspace: row.workspace || null,
        environment: row.environment || null,
        lastValidatedAt: row.lastValidatedAt,
        lastError: row.lastError,
        updatedAt: row.updatedAt,
      };
    }),

  connect: protectedProcedure
    .input(ConnectInput)
    .output(ModalAccountStatusSchema)
    .mutation(async ({ ctx, input }) => {
      assertModalTokenShape(input);
      const workspace = input.workspace?.trim() ?? '';
      const environment = input.environment?.trim() ?? '';

      // Validate against Modal BEFORE persisting. A rejected token never
      // touches the database — keeps `lastValidatedAt` honest and stops
      // the worker from picking up creds that are guaranteed to fail.
      const probe = await validateModalToken(
        input.tokenId,
        input.tokenSecret,
        environment || undefined,
      );
      if (!probe.ok) {
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message:
            probe.reason === 'rejected'
              ? 'Modal rejected this token id / secret pair. Create a new API token and try again.'
              : 'Modal could not validate this token within 5 seconds. No credentials were saved; try again in a moment.',
        });
      }

      let encryptedTokenSecret: string;
      try {
        encryptedTokenSecret = encryptModalSecret(input.tokenSecret);
      } catch {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Modal credential encryption is not configured on this server.',
        });
      }

      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          modalCredential?: {
            upsert: (args: unknown) => Promise<ModalCredentialRow>;
          };
          $executeRawUnsafe?: (query: string, ...values: unknown[]) => Promise<number>;
        };
        if (client.modalCredential?.upsert) {
          return client.modalCredential.upsert({
            where: { orgId: ctx.auth!.orgId },
            create: {
              orgId: ctx.auth!.orgId,
              tokenId: input.tokenId,
              tokenSecret: encryptedTokenSecret,
              workspace,
              environment,
              lastValidatedAt: new Date(),
              lastError: null,
            },
            update: {
              tokenId: input.tokenId,
              tokenSecret: encryptedTokenSecret,
              workspace,
              environment,
              lastValidatedAt: new Date(),
              lastError: null,
            },
            select: {
              tokenId: true,
              workspace: true,
              environment: true,
              lastValidatedAt: true,
              lastError: true,
              updatedAt: true,
            },
          });
        }
        if (!client.$executeRawUnsafe) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'database client cannot save Modal credentials',
          });
        }
        await client.$executeRawUnsafe(
          `INSERT INTO modal_credentials (
             org_id,
             token_id,
             token_secret,
             workspace,
             environment,
             last_validated_at,
             last_error,
             updated_at
           )
           VALUES ($1::uuid, $2, $3, $4, $5, now(), NULL, now())
           ON CONFLICT (org_id) DO UPDATE SET
             token_id = EXCLUDED.token_id,
             token_secret = EXCLUDED.token_secret,
             workspace = EXCLUDED.workspace,
             environment = EXCLUDED.environment,
             last_validated_at = now(),
             last_error = NULL,
             updated_at = now()`,
          ctx.auth!.orgId,
          input.tokenId,
          encryptedTokenSecret,
          workspace,
          environment,
        );
        return {
          tokenId: input.tokenId,
          workspace,
          environment,
          lastValidatedAt: new Date(),
          lastError: null,
          updatedAt: new Date(),
        };
      });

      return {
        connected: true,
        tokenIdSuffix: suffix(row.tokenId),
        workspace: row.workspace || null,
        environment: row.environment || null,
        lastValidatedAt: row.lastValidatedAt,
        lastError: row.lastError,
        updatedAt: row.updatedAt,
      };
    }),

  disconnect: protectedProcedure
    .input(z.void())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          modalCredential?: { deleteMany: (args: unknown) => Promise<unknown> };
          $executeRawUnsafe?: (query: string, ...values: unknown[]) => Promise<number>;
        };
        if (client.modalCredential?.deleteMany) {
          await client.modalCredential.deleteMany({ where: { orgId: ctx.auth!.orgId } });
          return;
        }
        if (!client.$executeRawUnsafe) return;
        await client.$executeRawUnsafe(
          'DELETE FROM modal_credentials WHERE org_id = $1::uuid',
          ctx.auth!.orgId,
        );
      });
      return { ok: true as const };
    }),
});
