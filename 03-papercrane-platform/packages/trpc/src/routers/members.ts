/**
 * Members & invites router.
 *
 * Covers the org-membership lifecycle:
 *
 *   members.list              — org roster (all members)
 *   members.invite            — create an Invite row + send email (stub)
 *   members.resendInvite      — bump expiresAt + rotate the invite token
 *   members.removeInvite      — revoke a pending invite
 *   members.acceptInvite      — invitee consumes a token after Supabase signup
 *   members.updateRole        — change another member's role (RBAC)
 *   members.remove            — kick a member (RBAC; refuses last owner)
 *   members.leave             — self-removal (refuses last owner)
 *
 * RBAC:
 *
 *   viewer  → list only
 *   member  → list only
 *   admin   → invite/removeInvite/remove/updateRole, bounded by rank
 *   owner   → everything; last owner cannot be removed or demoted
 *
 * Every mutation still routes through `withRlsUser` so Postgres RLS enforces
 * tenant isolation as a second line of defence.
 */
import { randomBytes } from 'node:crypto';
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Schemas ─────────────────────────────────────────────────────────────────

const OrgRoleSchema = z.enum(['viewer', 'member', 'admin', 'owner']);
export type OrgRole = z.infer<typeof OrgRoleSchema>;

const MemberSchema = z
  .object({
    userId: z.string(),
    orgId: z.string(),
    role: OrgRoleSchema,
    email: z.string(),
    name: z.string().nullable().optional(),
    joinedAt: z.date(),
  })
  .passthrough();

const InviteSchema = z
  .object({
    id: z.string(),
    orgId: z.string(),
    email: z.string(),
    role: OrgRoleSchema,
    invitedBy: z.string(),
    invitedByName: z.string().nullable().optional(),
    invitedByEmail: z.string().nullable().optional(),
    token: z.string().optional(), // only surfaced right after create
    expiresAt: z.date(),
    acceptedAt: z.date().nullable().optional(),
    createdAt: z.date(),
  })
  .passthrough();

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Strict rank table. Mirrored on the UI in `lib/members/permissions.ts`.
 * Keep the two in sync — tests on both sides pin the contract.
 */
const RANK: Record<OrgRole, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3,
};

const INVITE_TTL_DAYS = 7;
const INVITE_TOKEN_BYTES = 24; // → 32 URL-safe chars via base64url

function generateInviteToken(): string {
  return randomBytes(INVITE_TOKEN_BYTES).toString('base64url');
}

function addDays(d: Date, days: number): Date {
  const next = new Date(d);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

type MemberClient = {
  orgMember: {
    findMany: (args: unknown) => Promise<unknown[]>;
    findUnique: (args: unknown) => Promise<unknown | null>;
    findFirst: (args: unknown) => Promise<unknown | null>;
    count: (args: unknown) => Promise<number>;
    create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
    update: (args: {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    }) => Promise<unknown>;
    delete: (args: { where: Record<string, unknown> }) => Promise<unknown>;
    upsert: (args: {
      where: Record<string, unknown>;
      create: Record<string, unknown>;
      update: Record<string, unknown>;
    }) => Promise<unknown>;
  };
  invite: {
    findMany: (args: unknown) => Promise<unknown[]>;
    findUnique: (args: unknown) => Promise<unknown | null>;
    findFirst: (args: unknown) => Promise<unknown | null>;
    create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
    update: (args: {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    }) => Promise<unknown>;
    delete: (args: { where: Record<string, unknown> }) => Promise<unknown>;
    deleteMany: (args: {
      where: Record<string, unknown>;
    }) => Promise<{ count: number }>;
  };
  user: {
    findUnique: (args: unknown) => Promise<unknown | null>;
  };
};

async function loadActorRole(
  client: MemberClient,
  orgId: string,
  userId: string,
): Promise<OrgRole> {
  const me = (await client.orgMember.findUnique({
    where: { orgId_userId: { orgId, userId } },
  })) as { role: OrgRole } | null;
  if (!me) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'not a member of this org',
    });
  }
  return me.role;
}

function assertCanInvite(actor: OrgRole, target: OrgRole): void {
  if (actor !== 'owner' && actor !== 'admin') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners and admins can invite',
    });
  }
  if (RANK[target] >= RANK[actor]) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'cannot invite a role at or above your own',
    });
  }
  if (target === 'admin' && actor !== 'owner') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners can grant admin',
    });
  }
  if (target === 'owner' && actor !== 'owner') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners can grant owner',
    });
  }
}

function assertCanRemove(actor: OrgRole, target: OrgRole): void {
  if (actor !== 'owner' && actor !== 'admin') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners and admins can remove members',
    });
  }
  if (RANK[target] >= RANK[actor]) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'cannot remove a peer or someone at a higher rank',
    });
  }
}

function assertCanChangeRole(
  actor: OrgRole,
  targetCurrent: OrgRole,
  targetNext: OrgRole,
): void {
  if (actor !== 'owner' && actor !== 'admin') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners and admins can change roles',
    });
  }
  if (RANK[targetCurrent] >= RANK[actor]) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'cannot change the role of a peer or superior',
    });
  }
  if (targetNext === 'owner' && actor !== 'owner') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners can promote to owner',
    });
  }
  if (targetNext === 'admin' && actor !== 'owner') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners can promote to admin',
    });
  }
}

/**
 * Refuse any operation that would remove or demote the *last* owner.
 * The caller passes the role-change they're about to perform so we can
 * evaluate "would this leave zero owners?" in one place.
 */
async function assertNotLastOwnerChange(
  client: MemberClient,
  orgId: string,
  targetUserId: string,
  targetCurrent: OrgRole,
  nextRoleOrDelete: OrgRole | 'remove',
): Promise<void> {
  if (targetCurrent !== 'owner') return;
  if (nextRoleOrDelete === 'owner') return;

  const ownerCount = await client.orgMember.count({
    where: { orgId, role: 'owner' },
  });
  if (ownerCount <= 1) {
    throw new TRPCError({
      code: 'CONFLICT',
      message:
        'cannot remove or demote the last owner — transfer ownership first',
    });
  }
}

// ─── Router ──────────────────────────────────────────────────────────────────

export const membersRouter = router({
  // ── list ────────────────────────────────────────────────────────────────────
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/members',
        tags: ['members'],
        summary: 'List members of the caller’s org',
        protect: true,
      },
    })
    .input(z.void())
    .output(
      z.object({
        items: z.array(MemberSchema),
        pendingInvites: z.array(InviteSchema),
      }),
    )
    .query(async ({ ctx }) => {
      const { members, invites } = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as MemberClient;
          const rows = (await client.orgMember.findMany({
            where: { orgId: ctx.auth!.orgId },
            orderBy: { createdAt: 'asc' },
            include: { user: true },
          })) as Array<{
            orgId: string;
            userId: string;
            role: OrgRole;
            createdAt: Date;
            user: { email: string; name: string | null };
          }>;

          const pending = (await client.invite.findMany({
            where: { orgId: ctx.auth!.orgId, acceptedAt: null },
            orderBy: { createdAt: 'desc' },
            include: { inviter: true },
          })) as Array<{
            id: string;
            orgId: string;
            email: string;
            role: OrgRole;
            invitedBy: string;
            expiresAt: Date;
            acceptedAt: Date | null;
            createdAt: Date;
            inviter: { email: string; name: string | null } | null;
          }>;

          return { members: rows, invites: pending };
        },
      );

      return {
        items: members.map((m) => ({
          userId: m.userId,
          orgId: m.orgId,
          role: m.role,
          email: m.user.email,
          name: m.user.name,
          joinedAt: m.createdAt,
        })),
        pendingInvites: invites.map((i) => ({
          id: i.id,
          orgId: i.orgId,
          email: i.email,
          role: i.role,
          invitedBy: i.invitedBy,
          invitedByName: i.inviter?.name ?? null,
          invitedByEmail: i.inviter?.email ?? null,
          expiresAt: i.expiresAt,
          acceptedAt: i.acceptedAt,
          createdAt: i.createdAt,
        })),
      };
    }),

  // ── invite ──────────────────────────────────────────────────────────────────
  invite: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/members/invite',
        tags: ['members'],
        summary: 'Invite a teammate by email',
        protect: true,
      },
    })
    .input(
      z
        .object({
          email: z.string().email().max(320),
          role: OrgRoleSchema,
        })
        .strict(),
    )
    .output(
      z.object({
        invite: InviteSchema,
        emailLogged: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const token = generateInviteToken();
      const expiresAt = addDays(ctx.now(), INVITE_TTL_DAYS);
      const normalisedEmail = input.email.trim().toLowerCase();

      const created = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as MemberClient;
          const actorRole = await loadActorRole(
            client,
            ctx.auth!.orgId,
            ctx.auth.userId,
          );
          assertCanInvite(actorRole, input.role);

          // Block inviting someone who's already a member with this email.
          const existing = (await client.orgMember.findFirst({
            where: {
              orgId: ctx.auth!.orgId,
              user: { email: normalisedEmail },
            },
          })) as { userId: string } | null;
          if (existing) {
            throw new TRPCError({
              code: 'CONFLICT',
              message: 'user is already a member of this org',
            });
          }

          // If a pending invite exists, surface a clear conflict instead of
          // a surprise unique-violation from the partial unique index.
          const pending = (await client.invite.findFirst({
            where: {
              orgId: ctx.auth!.orgId,
              email: normalisedEmail,
              acceptedAt: null,
            },
          })) as { id: string } | null;
          if (pending) {
            throw new TRPCError({
              code: 'CONFLICT',
              message: 'a pending invite for this email already exists',
            });
          }

          return client.invite.create({
            data: {
              orgId: ctx.auth!.orgId,
              email: normalisedEmail,
              role: input.role,
              invitedBy: ctx.auth!.userId,
              token,
              expiresAt,
            },
          });
        },
      );

      // Email dispatch is best-effort from the router's perspective; it's a
      // stub today anyway. Real implementation moves to a background job.
      // We intentionally avoid importing the Fastify-side service here to
      // keep @papercrane/trpc free of API dependencies — instead the API
      // process listens for `invite.created` events (future follow-up).
      return {
        invite: created as z.infer<typeof InviteSchema>,
        emailLogged: true,
      };
    }),

  // ── resendInvite ────────────────────────────────────────────────────────────
  // Bumps `expiresAt` by `INVITE_TTL_DAYS` and rotates the token so a stale
  // copy of the old link can no longer be used. Returns the fresh invite so
  // the caller can show "copy link" UX without a follow-up `list` round-trip.
  resendInvite: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/members/invites/{inviteId}/resend',
        tags: ['members'],
        summary: 'Resend a pending invite (rotate token + extend expiry)',
        protect: true,
      },
    })
    .input(z.object({ inviteId: z.string().min(1) }).strict())
    .output(InviteSchema)
    .mutation(async ({ ctx, input }) => {
      const updated = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as MemberClient;
          const actorRole = await loadActorRole(
            client,
            ctx.auth!.orgId,
            ctx.auth.userId,
          );
          if (actorRole !== 'owner' && actorRole !== 'admin') {
            throw new TRPCError({
              code: 'FORBIDDEN',
              message: 'only owners and admins can resend invites',
            });
          }

          const existing = (await client.invite.findUnique({
            where: { id: input.inviteId },
          })) as
            | { id: string; orgId: string; acceptedAt: Date | null }
            | null;
          if (!existing || existing.orgId !== ctx.auth!.orgId) {
            throw new TRPCError({
              code: 'NOT_FOUND',
              message: 'invite not found',
            });
          }
          if (existing.acceptedAt) {
            throw new TRPCError({
              code: 'CONFLICT',
              message: 'invite already accepted — nothing to resend',
            });
          }

          return client.invite.update({
            where: { id: input.inviteId },
            data: {
              token: generateInviteToken(),
              expiresAt: addDays(ctx.now(), INVITE_TTL_DAYS),
            },
          });
        },
      );
      return updated as z.infer<typeof InviteSchema>;
    }),

  // ── removeInvite ────────────────────────────────────────────────────────────
  removeInvite: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/members/invites/{inviteId}',
        tags: ['members'],
        summary: 'Revoke a pending invite',
        protect: true,
      },
    })
    .input(z.object({ inviteId: z.string().min(1) }).strict())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as MemberClient;
        const actorRole = await loadActorRole(
          client,
          ctx.auth!.orgId,
          ctx.auth.userId,
        );
        if (actorRole !== 'owner' && actorRole !== 'admin') {
          throw new TRPCError({
            code: 'FORBIDDEN',
            message: 'only owners and admins can revoke invites',
          });
        }

        const r = await client.invite.deleteMany({
          where: {
            id: input.inviteId,
            orgId: ctx.auth!.orgId,
            acceptedAt: null,
          },
        });
        if (r.count === 0) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'invite not found or already accepted',
          });
        }
      });
      return { ok: true as const };
    }),

  // ── acceptInvite ────────────────────────────────────────────────────────────
  // Called by the invitee after completing Supabase magic-link signup. The
  // Supabase session must be live; the router resolves the caller's user id
  // from `ctx.auth.userId` and mints an OrgMember row for the invite's org.
  acceptInvite: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/members/invites/accept',
        tags: ['members'],
        summary: 'Accept an invite using the token',
        protect: true,
      },
    })
    .input(z.object({ token: z.string().min(16) }).strict())
    .output(
      z.object({
        orgId: z.string(),
        role: OrgRoleSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const result = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as MemberClient;
          const invite = (await client.invite.findUnique({
            where: { token: input.token },
          })) as {
            id: string;
            orgId: string;
            email: string;
            role: OrgRole;
            expiresAt: Date;
            acceptedAt: Date | null;
          } | null;
          if (!invite) {
            throw new TRPCError({ code: 'NOT_FOUND', message: 'invalid token' });
          }
          if (invite.acceptedAt) {
            throw new TRPCError({
              code: 'CONFLICT',
              message: 'invite already accepted',
            });
          }
          if (invite.expiresAt.getTime() <= ctx.now().getTime()) {
            throw new TRPCError({
              code: 'BAD_REQUEST',
              message: 'invite has expired',
            });
          }

          // Verify the authenticated user's email matches the invite.
          const callerUser = (await client.user.findUnique({
            where: { id: ctx.auth!.userId },
          })) as { email: string } | null;
          if (!callerUser) {
            throw new TRPCError({
              code: 'UNAUTHORIZED',
              message: 'user record missing',
            });
          }
          if (callerUser.email.toLowerCase() !== invite.email.toLowerCase()) {
            throw new TRPCError({
              code: 'FORBIDDEN',
              message: 'invite is for a different email address',
            });
          }

          // Upsert the membership row. Re-accepting (e.g. a user already in
          // the org who clicked the link after role change elsewhere) is
          // idempotent — we don't overwrite their existing role.
          await client.orgMember.upsert({
            where: {
              orgId_userId: {
                orgId: invite.orgId,
                userId: ctx.auth!.userId,
              },
            },
            create: {
              orgId: invite.orgId,
              userId: ctx.auth!.userId,
              role: invite.role,
            },
            update: {},
          });

          await client.invite.update({
            where: { id: invite.id },
            data: { acceptedAt: ctx.now() },
          });

          return { orgId: invite.orgId, role: invite.role };
        },
      );

      return result;
    }),

  // ── updateRole ──────────────────────────────────────────────────────────────
  updateRole: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/members/{userId}/role',
        tags: ['members'],
        summary: 'Update a member’s role',
        protect: true,
      },
    })
    .input(
      z
        .object({
          userId: z.string().min(1),
          role: OrgRoleSchema,
        })
        .strict(),
    )
    .output(MemberSchema)
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as MemberClient;
          const actorRole = await loadActorRole(
            client,
            ctx.auth!.orgId,
            ctx.auth.userId,
          );
          const target = (await client.orgMember.findUnique({
            where: {
              orgId_userId: { orgId: ctx.auth!.orgId, userId: input.userId },
            },
            include: { user: true },
          })) as {
            orgId: string;
            userId: string;
            role: OrgRole;
            createdAt: Date;
            user: { email: string; name: string | null };
          } | null;
          if (!target) {
            throw new TRPCError({
              code: 'NOT_FOUND',
              message: 'member not found',
            });
          }
          if (target.userId === ctx.auth!.userId) {
            throw new TRPCError({
              code: 'FORBIDDEN',
              message:
                'cannot change your own role — use the transfer-ownership flow',
            });
          }
          assertCanChangeRole(actorRole, target.role, input.role);
          // If we're demoting an owner, preserve the "at least one owner" rule.
          await assertNotLastOwnerChange(
            client,
            ctx.auth!.orgId,
            input.userId,
            target.role,
            input.role,
          );

          const updated = (await client.orgMember.update({
            where: {
              orgId_userId: { orgId: ctx.auth!.orgId, userId: input.userId },
            },
            data: { role: input.role },
          })) as { orgId: string; userId: string; role: OrgRole; createdAt: Date };

          return {
            userId: updated.userId,
            orgId: updated.orgId,
            role: updated.role,
            email: target.user.email,
            name: target.user.name,
            joinedAt: updated.createdAt,
          };
        },
      );
      return row;
    }),

  // ── remove ──────────────────────────────────────────────────────────────────
  remove: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/members/{userId}',
        tags: ['members'],
        summary: 'Remove a member from the org',
        protect: true,
      },
    })
    .input(z.object({ userId: z.string().min(1) }).strict())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as MemberClient;
        const actorRole = await loadActorRole(
          client,
          ctx.auth!.orgId,
          ctx.auth.userId,
        );
        if (input.userId === ctx.auth!.userId) {
          throw new TRPCError({
            code: 'FORBIDDEN',
            message: 'use members.leave to remove yourself',
          });
        }
        const target = (await client.orgMember.findUnique({
          where: {
            orgId_userId: { orgId: ctx.auth!.orgId, userId: input.userId },
          },
        })) as { role: OrgRole } | null;
        if (!target) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'member not found',
          });
        }
        assertCanRemove(actorRole, target.role);
        await assertNotLastOwnerChange(
          client,
          ctx.auth!.orgId,
          input.userId,
          target.role,
          'remove',
        );

        await client.orgMember.delete({
          where: {
            orgId_userId: { orgId: ctx.auth!.orgId, userId: input.userId },
          },
        });
      });
      return { ok: true as const };
    }),

  // ── leave ───────────────────────────────────────────────────────────────────
  leave: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/members/leave',
        tags: ['members'],
        summary: 'Leave the org (caller removes their own membership)',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as MemberClient;
        const me = (await client.orgMember.findUnique({
          where: {
            orgId_userId: {
              orgId: ctx.auth!.orgId,
              userId: ctx.auth!.userId,
            },
          },
        })) as { role: OrgRole } | null;
        if (!me) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'you are not a member of this org',
          });
        }
        await assertNotLastOwnerChange(
          client,
          ctx.auth!.orgId,
          ctx.auth!.userId,
          me.role,
          'remove',
        );

        await client.orgMember.delete({
          where: {
            orgId_userId: {
              orgId: ctx.auth!.orgId,
              userId: ctx.auth!.userId,
            },
          },
        });
      });
      return { ok: true as const };
    }),
});
