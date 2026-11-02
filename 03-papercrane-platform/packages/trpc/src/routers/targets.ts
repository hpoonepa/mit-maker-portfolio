/**
 * Targets router — create uses presigned PUT URLs so large PDB files don't
 * tunnel through the API server. Flow:
 *
 *   1. Client calls `targets.create` with metadata → API returns a presigned
 *      PUT URL + object key.
 *   2. Client uploads the .pdb straight to R2 via the presigned URL.
 *   3. Client (or a webhook) calls `targets.finalize` once the upload is
 *      complete to promote the row out of "pending".
 *
 * For now we model only steps (1) and read operations; finalize lives in a
 * later plan slice alongside checksum verification.
 */
import { randomBytes, createHash } from 'node:crypto';
import { z } from 'zod';
import { TargetSchema, HotspotSchema } from '@papercrane/types';
import { orgTargetKey, orgUploadStagingKey } from '@papercrane/storage';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

/**
 * Normalise the JSONB `hotspots` column on a Target row.
 *
 * The picker writes `Hotspot[]`. Older seed/test fixtures sometimes wrote a
 * single `{chain, residues}` object directly. Wrap that legacy shape into an
 * array so consumers can always iterate uniformly.
 */
function normaliseHotspots(row: unknown): unknown {
  if (!row || typeof row !== 'object') return row;
  const r = row as Record<string, unknown>;
  const h = r.hotspots;
  if (h == null) return row;
  if (Array.isArray(h)) return row;
  // single object → wrap
  if (typeof h === 'object' && 'chain' in (h as object) && 'residues' in (h as object)) {
    return { ...r, hotspots: [h] };
  }
  return row;
}

const CreateInput = z
  .object({
    name: z.string().min(1).max(200),
    slug: z
      .string()
      .regex(/^[a-z0-9][a-z0-9-]*$/)
      .max(64),
    pdbId: z.string().regex(/^[A-Za-z0-9]{4}$/),
    chain: z.string().length(1),
    class: z.enum([
      'receptor',
      'enzyme',
      'antibody',
      'transcription-factor',
      'peptide',
      'other',
    ]),
    tier: z.enum(['easy', 'medium', 'hard']),
    hotspots: z.array(HotspotSchema).default([]),
    description: z.string().max(2000).optional(),
    /** Declared size of the input PDB in bytes — binds into presigned URL. */
    contentLength: z.number().int().positive().max(100 * 1024 * 1024).optional(),
  })
  .strict();

const CreateOutput = z.object({
  target: TargetSchema,
  upload: z.object({
    url: z.string().url(),
    key: z.string().min(1),
    /** SigV4 TTL seconds. */
    expiresInSec: z.number().int().positive(),
  }),
});

const UpdateHotspotsInput = z
  .object({
    targetId: z.string().min(1),
    hotspots: z.array(HotspotSchema).superRefine((hotspots, ctx) => {
      const residueCount = hotspots.reduce(
        (total, hotspot) => total + hotspot.residues.length,
        0,
      );
      if (residueCount > 20) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'a target can have at most 20 hotspot residues',
        });
      }

      const chains = new Set<string>();
      for (const hotspot of hotspots) {
        if (chains.has(hotspot.chain)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `chain ${hotspot.chain} appears more than once`,
          });
        }
        chains.add(hotspot.chain);

        if (new Set(hotspot.residues).size !== hotspot.residues.length) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `chain ${hotspot.chain} contains duplicate residues`,
          });
        }
      }
    }),
  })
  .strict();

// ── Upload helpers ─────────────────────────────────────────────────────────
//
// The drag-drop wizard uses a two-call flow:
//   1. `getUploadUrl({ filename })` — mints a staging key + presigned PUT URL
//      so the browser can stream the file directly to R2.
//   2. `createFromUpload({ uploadKey, name, projectId? })` — server fetches
//      the staged bytes, parses chains/residues/mass, persists a Target.
//
// We parse server-side as well as client-side — the client validation is for
// UX, this one is the trust boundary.

// First char must be alphanumeric (no leading dot/dash for safety); the rest
// allows the common set browsers produce: letters, digits, dot, underscore,
// hyphen, space, parentheses, plus, and tilde. Path separators (/ \) are
// still rejected. The presign helper URL-encodes the storage key, so spaces
// and parens are safe downstream.
const UPLOAD_FILENAME_RE = /^[A-Za-z0-9][A-Za-z0-9._()+~\- ]{0,127}$/;
const UPLOAD_EXT_RE = /\.(pdb|ent|cif|mmcif|sdf|mol)$/i;
const UPLOAD_MAX_BYTES = 10 * 1024 * 1024; // 10 MB per spec
const UPLOAD_TTL_SEC = 15 * 60;

const GetUploadUrlInput = z
  .object({
    filename: z
      .string()
      .min(3)
      .max(128)
      .regex(UPLOAD_FILENAME_RE, 'filename has unsupported characters')
      .refine((s) => UPLOAD_EXT_RE.test(s), 'filename must end in .pdb/.ent/.cif/.mmcif/.sdf/.mol'),
    contentLength: z.number().int().positive().max(UPLOAD_MAX_BYTES).optional(),
  })
  .strict();

const GetUploadUrlOutput = z.object({
  url: z.string().url(),
  uploadKey: z.string().min(1),
  expiresInSec: z.number().int().positive(),
});

const CreateFromUploadInput = z
  .object({
    uploadKey: z.string().min(1).max(512),
    name: z.string().trim().min(2).max(200),
    projectId: z.string().uuid().optional(),
    /** Optional chain id the user picked in the wizard. */
    chain: z.string().min(1).max(4).optional(),
  })
  .strict();

const CreateFromUploadOutput = z.object({
  target: TargetSchema,
  stats: z.object({
    chainCount: z.number().int().nonnegative(),
    residueCount: z.number().int().nonnegative(),
    /** Approx mass in Daltons (avg AA ~ 110 Da). */
    massDa: z.number().nonnegative(),
    format: z.enum(['pdb', 'cif']),
  }),
});

/**
 * Extremely small structure sniffer — counts unique (chain, resnum) pairs
 * across ATOM records and skips HETATM/water/ligand. It exists ONLY to
 * compute summary stats; the real Mol* viewer parses the file properly
 * client-side. Tolerant of malformed input (returns whatever it could read).
 */
function parseStructureStats(text: string): {
  format: 'pdb' | 'cif';
  chainCount: number;
  residueCount: number;
  massDa: number;
  pdbId: string | null;
} {
  const isCif = /^data_/m.test(text) && /_atom_site\./m.test(text);
  const seen = new Set<string>();
  const chains = new Set<string>();
  let pdbId: string | null = null;

  if (isCif) {
    const lines = text.split(/\r?\n/);
    let loopStart = -1;
    for (let i = 0; i < lines.length; i++) {
      const t = lines[i]!.trim();
      if (t.startsWith('_entry.id')) {
        const m = t.match(/_entry\.id\s+(\S+)/);
        if (m && /^[0-9][A-Za-z0-9]{3}$/.test(m[1] ?? '')) pdbId = m[1]!.toUpperCase();
      }
      if (t === 'loop_') {
        let j = i + 1;
        while (j < lines.length && lines[j]!.trim() === '') j++;
        if (j < lines.length && lines[j]!.trim().startsWith('_atom_site.')) {
          loopStart = i;
          break;
        }
      }
    }
    if (loopStart === -1) return { format: 'cif', chainCount: 0, residueCount: 0, massDa: 0, pdbId };
    const cols: string[] = [];
    let k = loopStart + 1;
    while (k < lines.length && lines[k]!.trim().startsWith('_atom_site.')) {
      cols.push(lines[k]!.trim().replace(/^_atom_site\./, ''));
      k++;
    }
    const iGroup = cols.indexOf('group_PDB');
    const iChain = cols.indexOf('auth_asym_id') >= 0 ? cols.indexOf('auth_asym_id') : cols.indexOf('label_asym_id');
    const iSeq = cols.indexOf('auth_seq_id') >= 0 ? cols.indexOf('auth_seq_id') : cols.indexOf('label_seq_id');
    const iIns = cols.indexOf('pdbx_PDB_ins_code');
    if (iChain < 0 || iSeq < 0) return { format: 'cif', chainCount: 0, residueCount: 0, massDa: 0, pdbId };
    for (; k < lines.length; k++) {
      const raw = lines[k]!;
      const trimmed = raw.trim();
      if (trimmed === '' || trimmed.startsWith('#')) continue;
      if (trimmed.startsWith('loop_') || trimmed.startsWith('_') || trimmed.startsWith('save_')) break;
      const tokens = trimmed.split(/\s+/);
      if (tokens.length < cols.length) continue;
      if (iGroup >= 0 && tokens[iGroup]!.toUpperCase() !== 'ATOM') continue;
      const c = tokens[iChain]!;
      const s = tokens[iSeq]!;
      const ins = iIns >= 0 ? (tokens[iIns] === '?' || tokens[iIns] === '.' ? '' : tokens[iIns] ?? '') : '';
      const key = `${c}|${s}|${ins}`;
      if (seen.has(key)) continue;
      seen.add(key);
      chains.add(c);
    }
    const residueCount = seen.size;
    return { format: 'cif', chainCount: chains.size, residueCount, massDa: residueCount * 110, pdbId };
  }

  // PDB
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    if (raw.startsWith('HEADER')) {
      const m = raw.slice(62, 66).trim();
      if (/^[0-9][A-Za-z0-9]{3}$/.test(m)) pdbId = m.toUpperCase();
      continue;
    }
    if (!raw.startsWith('ATOM') || raw.length < 27) continue;
    const altLoc = raw.charAt(16);
    if (altLoc !== ' ' && altLoc !== 'A') continue;
    const chainId = raw.charAt(21).trim() || 'A';
    const seqRaw = raw.slice(22, 26).trim();
    const insCode = raw.charAt(26).trim();
    const seqNum = Number.parseInt(seqRaw, 10);
    if (!Number.isFinite(seqNum)) continue;
    const key = `${chainId}|${seqNum}|${insCode}`;
    if (seen.has(key)) continue;
    seen.add(key);
    chains.add(chainId);
  }
  const residueCount = seen.size;
  return { format: 'pdb', chainCount: chains.size, residueCount, massDa: residueCount * 110, pdbId };
}

/**
 * Verifies a caller-supplied uploadKey lives in the caller's org bucket and
 * is a staging key minted by `getUploadUrl` — prevents a user from passing
 * an arbitrary key (e.g. another org's target).
 */
function assertOwnedUploadKey(uploadKey: string, orgId: string): void {
  const expected = `orgs/${orgId}/uploads/`;
  if (!uploadKey.startsWith(expected)) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'uploadKey does not belong to this org',
    });
  }
  // Block path traversal / absolute paths even though our prefix check should
  // already make them impossible.
  if (uploadKey.includes('..') || uploadKey.includes('//')) {
    throw new TRPCError({ code: 'BAD_REQUEST', message: 'invalid uploadKey' });
  }
}

export const targetsRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/targets',
        tags: ['targets'],
        summary: 'List targets in the caller’s org',
        protect: true,
      },
    })
    .input(z.object({ limit: z.number().int().positive().max(200).optional(), projectId: z.string().uuid().optional() }))
    .output(z.object({ items: z.array(TargetSchema) }))
    .query(async ({ ctx, input }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          target: { findMany: (args: unknown) => Promise<unknown[]> };
        };
        return client.target.findMany({
          where: { orgId: ctx.auth!.orgId, ...(input.projectId ? { projectId: input.projectId } : {}) },
          orderBy: { createdAt: 'desc' },
          take: input.limit ?? 50,
        });
      });
      return {
        items: (items as unknown[]).map(normaliseHotspots) as z.infer<
          typeof TargetSchema
        >[],
      };
    }),

  get: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/targets/{id}',
        tags: ['targets'],
        summary: 'Get a target by id',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(TargetSchema)
    .query(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          target: { findFirst: (args: unknown) => Promise<unknown | null> };
        };
        return client.target.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
      });
      if (!row) throw new TRPCError({ code: 'NOT_FOUND', message: 'target not found' });

      const normalised = normaliseHotspots(row) as Record<string, unknown>;
      const artifactKey =
        typeof normalised.artifactKey === 'string'
          ? normalised.artifactKey
          : null;
      const structureUrl = artifactKey
        ? await ctx.presignGet(artifactKey, 15 * 60)
        : undefined;

      return {
        ...normalised,
        ...(structureUrl ? { structureUrl } : {}),
      } as z.infer<typeof TargetSchema>;
    }),

  /**
   * Persist hotspots from the standalone target editor. Unlike
   * `saveHotspots`, this procedure does not require the target to belong to
   * a project, so catalogue/unassigned targets can be edited too.
   */
  updateHotspots: protectedProcedure
    .input(UpdateHotspotsInput)
    .output(z.object({ target: TargetSchema }))
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          target: {
            findFirst: (args: unknown) => Promise<{ id: string } | null>;
            update: (args: {
              where: Record<string, unknown>;
              data: Record<string, unknown>;
            }) => Promise<unknown>;
          };
        };

        const target = await client.target.findFirst({
          where: { id: input.targetId, orgId: ctx.auth!.orgId },
        });
        if (!target) {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'target not found' });
        }

        return client.target.update({
          where: { id: target.id, orgId: ctx.auth!.orgId },
          data: { hotspots: input.hotspots },
        });
      });

      return { target: normaliseHotspots(row) as z.infer<typeof TargetSchema> };
    }),

  saveHotspots: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/projects/{projectId}/hotspots',
        tags: ['targets'],
        summary: 'Persist hotspots picked in the 3D viewer for a project target',
        protect: true,
      },
    })
    .input(
      z
        .object({
          projectId: z.string().min(1),
          /** Optional explicit target — when omitted we update the project's
           * most-recent target (matches the dashboard's "one target per
           * project" UX). */
          targetId: z.string().min(1).optional(),
          hotspots: z.array(HotspotSchema),
        })
        .strict(),
    )
    .output(z.object({ target: TargetSchema }))
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          target: {
            findFirst: (args: unknown) => Promise<{ id: string } | null>;
            update: (args: {
              where: Record<string, unknown>;
              data: Record<string, unknown>;
            }) => Promise<unknown>;
          };
        };

        // Resolve the target row: explicit id wins, otherwise pick the most
        // recent target attached to the project. If no target exists yet
        // we surface a NOT_FOUND so the UI can prompt the user to upload one.
        const targetRow = input.targetId
          ? await client.target.findFirst({
              where: {
                id: input.targetId,
                orgId: ctx.auth!.orgId,
                projectId: input.projectId,
              },
            })
          : await client.target.findFirst({
              where: { orgId: ctx.auth!.orgId, projectId: input.projectId },
              // Newest first — the project's "current" target.
              orderBy: { createdAt: 'desc' },
            } as unknown as Record<string, unknown>);

        if (!targetRow) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'No target found for this project — upload a PDB first.',
          });
        }

        return client.target.update({
          where: { id: targetRow.id, orgId: ctx.auth!.orgId },
          data: { hotspots: input.hotspots },
        });
      });
      return { target: normaliseHotspots(row) as z.infer<typeof TargetSchema> };
    }),

  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/targets',
        tags: ['targets'],
        summary: 'Create a target and receive a presigned PUT URL for its PDB',
        protect: true,
      },
    })
    .input(CreateInput)
    .output(CreateOutput)
    .mutation(async ({ ctx, input }) => {
      let target: unknown;
      try {
        target = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              target: {
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
              };
            };
            return client.target.create({
              data: {
                orgId: ctx.auth!.orgId,
                name: input.name,
                slug: input.slug,
                pdbId: input.pdbId.toUpperCase(),
                chain: input.chain,
                class: input.class,
                tier: input.tier,
                hotspots: input.hotspots,
                description: input.description ?? null,
              },
            });
          },
        );
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2002') {
          throw new TRPCError({
            code: 'CONFLICT',
            message: 'a target with this slug already exists',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to create target',
        });
      }
      const typed = target as { id: string };
      const key = orgTargetKey(ctx.auth!.orgId, typed.id);
      const url = await ctx.presignPut(
        key,
        'chemical/x-pdb',
        input.contentLength,
        15 * 60,
      );
      return {
        target: target as z.infer<typeof TargetSchema>,
        upload: { url, key, expiresInSec: 15 * 60 },
      };
    }),

  /**
   * Step 1 of the drag-drop wizard: mint a presigned PUT URL the browser can
   * stream the file to. We do NOT create a Target row yet — the row is
   * created in `createFromUpload` after the bytes have actually landed.
   */
  getUploadUrl: protectedProcedure
    .input(GetUploadUrlInput)
    .output(GetUploadUrlOutput)
    .mutation(async ({ ctx, input }) => {
      const uploadId = randomBytes(12).toString('hex');
      const key = orgUploadStagingKey(ctx.auth!.orgId, uploadId, input.filename);
      const url = await ctx.presignPut(
        key,
        'chemical/x-pdb',
        input.contentLength,
        UPLOAD_TTL_SEC,
      );
      return { url, uploadKey: key, expiresInSec: UPLOAD_TTL_SEC };
    }),

  /**
   * Step 2 of the wizard: server fetches the staged blob, parses chains and
   * residues, persists a Target row, returns it. The R2 object stays at the
   * staging key — `artifactKey` on the row points at it (rename is async / a
   * later sweep concern).
   */
  createFromUpload: protectedProcedure
    .input(CreateFromUploadInput)
    .output(CreateFromUploadOutput)
    .mutation(async ({ ctx, input }) => {
      assertOwnedUploadKey(input.uploadKey, ctx.auth!.orgId);

      // Fetch bytes via a short-lived GET URL — we re-use presignGet so we
      // don't have to plumb an S3 client into the router.
      const getUrl = await ctx.presignGet(input.uploadKey, 60);
      let buf: ArrayBuffer;
      try {
        const res = await fetch(getUrl);
        if (!res.ok) {
          throw new TRPCError({
            code: 'BAD_REQUEST',
            message: `upload not found at key (status ${res.status})`,
          });
        }
        buf = await res.arrayBuffer();
      } catch (err) {
        if (err instanceof TRPCError) throw err;
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: 'failed to fetch upload from storage',
        });
      }

      if (buf.byteLength === 0) {
        throw new TRPCError({ code: 'BAD_REQUEST', message: 'upload is empty' });
      }
      if (buf.byteLength > UPLOAD_MAX_BYTES) {
        throw new TRPCError({
          code: 'PAYLOAD_TOO_LARGE',
          message: `upload exceeds ${UPLOAD_MAX_BYTES} bytes`,
        });
      }

      const text = new TextDecoder('utf-8', { fatal: false }).decode(buf);
      const stats = parseStructureStats(text);
      if (stats.residueCount === 0) {
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: 'no ATOM records found — file is not a valid PDB or mmCIF',
        });
      }

      const checksum = createHash('sha256').update(new Uint8Array(buf)).digest('hex');

      let target: unknown;
      try {
        target = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              target: {
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
              };
            };
            return client.target.create({
              data: {
                orgId: ctx.auth!.orgId,
                projectId: input.projectId ?? null,
                name: input.name,
                pdbId: stats.pdbId,
                artifactKey: input.uploadKey,
                checksum,
                hotspots: [],
              },
            });
          },
        );
      } catch (err) {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: (err as Error)?.message ?? 'failed to create target from upload',
        });
      }

      return {
        target: normaliseHotspots(target) as z.infer<typeof TargetSchema>,
        stats: {
          chainCount: stats.chainCount,
          residueCount: stats.residueCount,
          massDa: stats.massDa,
          format: stats.format,
        },
      };
    }),
});
