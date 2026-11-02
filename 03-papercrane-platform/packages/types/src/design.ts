import { z } from 'zod';

/**
 * A hotspot marks residues on a target chain that a binder should contact.
 */
export const HotspotSchema = z
  .object({
    chain: z.string().length(1),
    residues: z.array(z.number().int().nonnegative()).min(1),
  })
  .strict();
export type Hotspot = z.infer<typeof HotspotSchema>;

/**
 * Optional structural / biophysical constraints applied to the design.
 */
export const DesignConstraintsSchema = z
  .object({
    lengthRange: z
      .tuple([z.number().int().positive(), z.number().int().positive()])
      .optional(),
    disulfides: z.boolean().optional(),
    solubility: z.enum(['default', 'strict']).optional(),
  })
  .strict();
export type DesignConstraints = z.infer<typeof DesignConstraintsSchema>;

/**
 * Open-ended numeric metric record (ipsae, iptm, pLDDT, pDockQ, ...).
 * Using z.record allows new metrics to be added without a breaking change.
 */
export const DesignMetricsSchema = z.record(z.string(), z.number());
export type DesignMetrics = z.infer<typeof DesignMetricsSchema>;

/**
 * A design request sent by a user to a tool backend.
 */
export const DesignRequestSchema = z
  .object({
    /**
     * Either an S3 URI (s3://...), an R2 upload key, or a 4-character RCSB PDB
     * id. Required for target/backbone/complex-input tools; omitted for
     * sequence-only tools (ESM-2/ESM-C/Boltz-1), which carry their input in
     * `toolParams.sequences` instead. The wizard enforces presence per input
     * kind, so absence here only happens for the sequence path.
     */
    targetPdb: z.string().min(4).optional(),
    hotspots: z.array(HotspotSchema).optional(),
    seeds: z.array(z.number().int().nonnegative().max(0xffff_ffff)).min(1),
    numDesigns: z.number().int().positive(),
    constraints: DesignConstraintsSchema.optional(),
    /** Tool-specific freeform params — validated by each tool adapter. */
    toolParams: z.record(z.string(), z.unknown()).optional(),
    /**
     * Co-fold structure prediction (Boltz-2 / Chai-1 / AlphaFold3): the second
     * structure to fold together with {@link targetPdb}. When set, the job is a
     * complex prediction of two given structures rather than binder design
     * against a single target — so `hotspots` is not used. Either an S3 URI or
     * a 4-character RCSB PDB id. Optional; absent for binder/sequence-design.
     */
    partnerPdb: z.string().min(4).optional(),
    /** Which chain to take from {@link targetPdb} (single letter). */
    targetChain: z.string().length(1).optional(),
    /** Which chain to take from {@link partnerPdb} (single letter). */
    partnerChain: z.string().length(1).optional(),
  })
  .strict()
  .superRefine((request, ctx) => {
    if (new Set(request.seeds).size !== request.seeds.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['seeds'],
        message: 'seeds must be unique',
      });
    }
    if (request.numDesigns !== request.seeds.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['numDesigns'],
        message: 'numDesigns must match the number of seeds',
      });
    }
  });
export type DesignRequest = z.infer<typeof DesignRequestSchema>;

/**
 * A single design result emitted by a tool worker.
 */
export const DesignResultSchema = z
  .object({
    id: z.string().uuid(),
    jobId: z.string().uuid(),
    sequence: z.string().min(1),
    length: z.number().int().positive(),
    seed: z.number().int().nonnegative(),
    metrics: DesignMetricsSchema,
    /**
     * R2 object key of the predicted structure (pdb/cif), if available.
     * Matches the `artifact_key` column on the `designs` table; the API
     * presigns this key to produce the short-lived `structureUrl`.
     */
    artifactKey: z.string().optional(),
    createdAt: z.string().datetime(),
  })
  .strict();
export type DesignResult = z.infer<typeof DesignResultSchema>;
