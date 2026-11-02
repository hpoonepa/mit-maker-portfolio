import { z } from 'zod';

/**
 * Pricing/access tier a tool is available under.
 */
export const ToolTierSchema = z.enum(['free', 'pro', 'frontier'] as const);
export type ToolTier = z.infer<typeof ToolTierSchema>;

/**
 * High-level functional grouping used by the dashboard's tool picker.
 */
export const ToolCategorySchema = z.enum([
  'binder-design',
  'structure-prediction',
  'sequence-design',
  'validation',
  'utility',
] as const);
export type ToolCategory = z.infer<typeof ToolCategorySchema>;

/**
 * Compute requirement shape for a tool — drives scheduler decisions.
 */
export const ComputeProfileSchema = z
  .object({
    gpuType: z.string().min(1),
    gpuCount: z.number().int().positive(),
    memoryGb: z.number().positive(),
    estimatedMinutes: z.number().positive(),
    minVramGb: z.number().positive().optional(),
  })
  .strict();
export type ComputeProfile = z.infer<typeof ComputeProfileSchema>;

/**
 * Metadata describing a registered tool (see plan 02 §6).
 */
export const ToolManifestSchema = z
  .object({
    toolId: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
    name: z.string().min(1),
    version: z.string().min(1),
    category: ToolCategorySchema,
    tier: ToolTierSchema,
    description: z.string().min(1),
    /** Named reference into a shared schema registry. */
    inputSchemaRef: z.string().min(1),
    outputSchemaRef: z.string().min(1),
    compute: ComputeProfileSchema,
    seedCostPerDesign: z.number().nonnegative(),
    /** Optional docs URL. */
    docsUrl: z.string().url().optional(),
    /** Tool author / maintainer. */
    maintainer: z.string().optional(),
  })
  .strict();
export type ToolManifest = z.infer<typeof ToolManifestSchema>;
