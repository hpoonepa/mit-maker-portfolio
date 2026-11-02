/**
 * Onboarding router — wizard completion + step tracking.
 *
 * Procedures
 * ----------
 *   - markComplete    flip `users.onboardingCompleted = true` (idempotent)
 *   - status          legacy helper, kept for the auth middleware
 *   - getProgress     read the user's `user_onboarding` row (Wave 8)
 *   - setStep         upsert the user's current step + persona (Wave 8)
 *
 * The Wave 8 `getProgress`/`setStep` pair are the source-of-truth for the
 * wizard's resume logic — the client falls back to localStorage only for
 * paint-speed.
 */
import { z } from 'zod';
import { router, publicProcedure } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const OnboardingStepSchema = z.enum([
  'welcome',
  'create-org',
  'first-target',
  'first-job',
  'invite-team',
  'done',
]);

const LegacyOnboardingStepSchema = z.enum([
  'welcome',
  'create-org',
  'first-target',
  'first-job',
  'connect-modal',
  'invite-team',
  'done',
]);

const PersonaSchema = z.enum(['pi', 'grad', 'industry']);

const WorkspaceTypeSchema = z.enum(['lab', 'industry', 'student']);

function normaliseStoredStep(
  value: string | null | undefined,
): z.infer<typeof OnboardingStepSchema> {
  const parsed = value ? LegacyOnboardingStepSchema.safeParse(value) : null;
  if (!parsed?.success) return 'welcome';
  return parsed.data === 'connect-modal'
    ? 'invite-team'
    : (parsed.data as z.infer<typeof OnboardingStepSchema>);
}

/**
 * Organizations currently store a slug rather than a separate display name.
 * Keep the transformation here so account bootstrap and the UI cannot drift.
 */
function workspaceSlug(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return slug || 'my-workspace';
}

export const onboardingRouter = router({
  /**
   * Bootstrap a real workspace for a brand-new user.
   *
   * This is intentionally part of onboarding rather than the regular
   * tenant-scoped org surface: before this call a valid user session has no
   * orgId yet. The mutation is idempotent for users who already belong to an
   * organization (including invite-link signups).
   */
  createWorkspace: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/onboarding/workspace',
        tags: ['onboarding'],
        summary: 'Create the current user’s first workspace',
        protect: true,
      },
    })
    .input(
      z.object({
        name: z.string().trim().min(1).max(80),
        type: WorkspaceTypeSchema,
      }),
    )
    .output(
      z.object({
        orgId: z.string().uuid(),
        slug: z.string(),
        created: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const userId = ctx.auth.userId;
      return ctx.withRlsUser(
        ctx.prisma,
        userId,
        async (tx) => {
          const existingMembership = await tx.orgMember.findFirst({
            where: { userId },
            orderBy: { createdAt: 'asc' },
            include: { org: { select: { id: true, slug: true } } },
          });

          let result: { orgId: string; slug: string; created: boolean };
          if (existingMembership) {
            await tx.user.update({
              where: { id: userId },
              data: { defaultOrgId: existingMembership.orgId },
            });
            result = {
              orgId: existingMembership.org.id,
              slug: existingMembership.org.slug,
              created: false,
            };
          } else {
            const baseSlug = workspaceSlug(input.name);
            const conflict = await tx.organization.findUnique({
              where: { slug: baseSlug },
              select: { id: true },
            });
            const slug = conflict
              ? `${baseSlug.slice(0, 39)}-${userId.slice(0, 8)}`
              : baseSlug;

            const org = await tx.organization.create({
              data: {
                slug,
                tier: 'free',
                seedsQuota: 500,
                retentionDays: 7,
              },
              select: { id: true, slug: true },
            });
            await tx.orgMember.create({
              data: { orgId: org.id, userId, role: 'owner' },
            });
            await tx.user.update({
              where: { id: userId },
              data: { defaultOrgId: org.id },
            });
            await tx.featureFlag.create({
              data: { orgId: org.id },
            });
            await tx.auditLog.create({
              data: {
                orgId: org.id,
                userId,
                action: 'org_created',
                resourceType: 'organization',
                resourceId: org.id,
                metadata: {
                  workspaceType: input.type,
                  requestedName: input.name,
                },
              },
            });
            result = { orgId: org.id, slug: org.slug, created: true };
          }

          await tx.userOnboarding.upsert({
            where: { userId },
            update: {
              orgId: result.orgId,
              currentStep: 'first-target',
              completedAt: null,
              lastUpdatedAt: new Date(),
            },
            create: {
              userId,
              orgId: result.orgId,
              currentStep: 'first-target',
              persona: null,
              completedAt: null,
            },
          });
          return result;
        },
      );
    }),

  /** Persist completion in `user_onboarding`. Idempotent across retries. */
  markComplete: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/onboarding/complete',
        tags: ['onboarding'],
        summary: 'Mark the current user as having finished onboarding',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx }) => {
      const userId = ctx.auth.userId;
      const completedAt = ctx.now();
      await ctx.withRlsUser(ctx.prisma, userId, async (tx) => {
        await tx.userOnboarding.upsert({
          where: { userId },
          update: {
            currentStep: 'done',
            completedAt,
            lastUpdatedAt: completedAt,
          },
          create: {
            userId,
            orgId: ctx.auth.orgId ?? null,
            currentStep: 'done',
            persona: null,
            completedAt,
            lastUpdatedAt: completedAt,
          },
        });
      });
      return { ok: true as const };
    }),

  /** Returns the user's durable last-known onboarding step. */
  status: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/onboarding/status',
        tags: ['onboarding'],
        summary: "Read the current user's onboarding step",
        protect: true,
      },
    })
    .input(z.void())
    .output(
      z.object({
        step: OnboardingStepSchema,
        completed: z.boolean(),
      }),
    )
    .query(async ({ ctx }) => {
      const userId = ctx.auth.userId;
      const row = await ctx.withRlsUser(ctx.prisma, userId, async (tx) =>
        tx.userOnboarding.findUnique({
          where: { userId },
          select: { currentStep: true, completedAt: true },
        }),
      );
      return {
        step: normaliseStoredStep(row?.currentStep),
        completed: row?.completedAt != null,
      };
    }),

  /**
   * Wave 8 — full progress row.
   *
   * Returns null if the user has never written a row yet (e.g. a brand
   * new signup). The wizard treats null as "start at welcome".
   */
  getProgress: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/onboarding/progress',
        tags: ['onboarding'],
        summary: "Read the current user's full onboarding progress",
        protect: true,
      },
    })
    .input(z.void())
    .output(
      z
        .object({
          currentStep: OnboardingStepSchema,
          persona: PersonaSchema.nullable(),
          orgId: z.string().uuid().nullable(),
          completed: z.boolean(),
          lastUpdatedAt: z.string(),
        })
        .nullable(),
    )
    .query(async ({ ctx }) => {
      const userId = ctx.auth.userId;
      const row = await ctx.withRlsUser(ctx.prisma, userId, async (tx) =>
        tx.userOnboarding.findUnique({ where: { userId } }),
      );
      if (!row) return null;
      const persona = row.persona ? PersonaSchema.safeParse(row.persona) : null;
      return {
        currentStep: normaliseStoredStep(row.currentStep),
        persona: persona?.success ? persona.data : null,
        orgId: row.orgId,
        completed: row.completedAt != null,
        lastUpdatedAt: row.lastUpdatedAt.toISOString(),
      };
    }),

  /**
   * Wave 8 — write the user's current step + (optional) persona/org.
   *
   * Returns the persisted row so callers can confirm the save without
   * a follow-up read. Idempotent: re-writing the same step is a no-op
   * apart from `last_updated_at`.
   */
  setStep: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/onboarding/step',
        tags: ['onboarding'],
        summary: "Update the current user's onboarding step",
        protect: true,
      },
    })
    .input(
      z.object({
        step: OnboardingStepSchema,
        persona: PersonaSchema.nullable().optional(),
        orgId: z.string().uuid().nullable().optional(),
      }),
    )
    .output(
      z.object({
        currentStep: OnboardingStepSchema,
        persona: PersonaSchema.nullable(),
        orgId: z.string().uuid().nullable(),
        completed: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const userId = ctx.auth.userId;
      const completedAt = input.step === 'done' ? new Date() : null;
      const row = await ctx.withRlsUser(ctx.prisma, userId, async (tx) =>
        tx.userOnboarding.upsert({
          where: { userId },
          update: {
            currentStep: input.step,
            ...(input.persona !== undefined ? { persona: input.persona } : {}),
            ...(input.orgId !== undefined ? { orgId: input.orgId } : {}),
            completedAt,
            lastUpdatedAt: ctx.now(),
          },
          create: {
            userId,
            currentStep: input.step,
            persona: input.persona ?? null,
            orgId: input.orgId ?? null,
            completedAt,
            lastUpdatedAt: ctx.now(),
          },
        }),
      );
      const persona = row.persona ? PersonaSchema.safeParse(row.persona) : null;
      return {
        currentStep: normaliseStoredStep(row.currentStep),
        persona: persona?.success ? persona.data : null,
        orgId: row.orgId,
        completed: row.completedAt != null,
      };
    }),
});
