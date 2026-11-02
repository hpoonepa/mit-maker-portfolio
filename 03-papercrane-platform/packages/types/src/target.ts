import { z } from 'zod';
import { HotspotSchema } from './design';

/**
 * Biological class of a target, for filtering / analytics.
 */
export const TargetClassSchema = z.enum([
  'receptor',
  'enzyme',
  'antibody',
  'transcription-factor',
  'peptide',
  'other',
] as const);
export type TargetClass = z.infer<typeof TargetClassSchema>;

/**
 * Curated difficulty tier for a target in the benchmark catalogue.
 */
export const TargetTierSchema = z.enum(['easy', 'medium', 'hard'] as const);
export type TargetTier = z.infer<typeof TargetTierSchema>;

/**
 * A target the user is trying to bind to.
 *
 * NOTE: The Prisma `Target` model is the source of truth (see
 * `packages/db/prisma/schema.prisma`). Several fields below are kept
 * `.optional()` so we accept rows produced by older seeds that pre-date
 * the slug/chain/class/tier columns being added to the DB. The schema is
 * `.passthrough()` so additional Prisma columns (`orgId`, `projectId`,
 * `artifactKey`, `checksum`, `updatedAt`, ...) flow through untouched
 * rather than tripping output validation in tRPC.
 *
 * `hotspots` historically stored a single `{chain, residues}` object on
 * the `Target.hotspots` JSONB column; the picker now writes an array of
 * those objects. Accept both shapes so legacy rows still validate.
 */
const HotspotsField = z.union([
  z.array(HotspotSchema),
  HotspotSchema, // legacy single-object shape
]);

export const TargetSchema = z
  .object({
    id: z.string().uuid(),
    /** URL-safe kebab-case slug. */
    slug: z
      .string()
      .regex(/^[a-z0-9][a-z0-9-]*$/)
      .optional(),
    name: z.string().min(1),
    /** 4-character RCSB PDB id (uppercase). Nullable in the DB. */
    pdbId: z
      .string()
      .regex(/^[A-Z0-9]{4}$/)
      .nullable()
      .optional(),
    /** Short-lived signed URL returned by the authenticated detail endpoint. */
    structureUrl: z.string().url().optional(),
    chain: z.string().length(1).optional(),
    class: TargetClassSchema.optional(),
    tier: TargetTierSchema.optional(),
    hotspots: HotspotsField.nullable().optional(),
    description: z.string().nullable().optional(),
    createdAt: z.union([z.string().datetime(), z.date()]),
  })
  .passthrough();
export type Target = z.infer<typeof TargetSchema>;
