import { z } from 'zod';
import { promises as fs } from 'node:fs';
import type { ToolManifest } from './types';

const SHA256_DIGEST_RE = /^sha256:[a-f0-9]{64}$/;

const toolComputeProfileSchema = z.object({
  gpu: z.string().min(1),
  gpuCount: z.number().int().min(0),
  cpuCores: z.number().int().min(1),
  memoryGb: z.number().positive(),
  estSecondsPerDesign: z.number().positive(),
  note: z.string().optional(),
});

const toolTransportSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('https'),
    endpoint: z.string().url(),
  }),
  z.object({
    type: z.literal('modal'),
    app: z.string().min(1),
    function: z.string().min(1),
  }),
]);

export const toolManifestSchema = z.object({
  id: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/, {
    message: 'id must be lowercase alphanumeric (underscore/dash allowed)',
  }),
  displayName: z.string().min(1),
  version: z.string().min(1),
  adapterVersion: z.string().min(1),
  category: z.enum([
    'backbone',
    'backbone_generation',
    'sequence',
    'sequence_design',
    'binder_design',
    'structure',
    'structure_prediction',
    'embed',
    'embedding_scoring',
    'generative',
    'composite',
    'other',
  ]),
  tier: z.enum(['open', 'open-weights', 'frontier']),
  licenseGate: z.boolean().optional(),
  license: z.string().min(1),
  image: z.string().min(1),
  imageDigest: z.string().regex(SHA256_DIGEST_RE, {
    message: 'imageDigest must be "sha256:<64 hex chars>"',
  }),
  compute: toolComputeProfileSchema,
  inputSchema: z.string().optional(),
  outputSchema: z.string().optional(),
  defaultParams: z.record(z.unknown()).optional(),
  composes: z.array(z.string()).optional(),
  transport: toolTransportSchema.optional(),
});

/**
 * Parse a ToolManifest from a JSON string. Throws `z.ZodError` on schema failure,
 * `SyntaxError` on malformed JSON.
 */
export function parseManifest(raw: string): ToolManifest {
  const json = JSON.parse(raw);
  return toolManifestSchema.parse(json) as ToolManifest;
}

/**
 * Load and validate a `manifest.json` from disk.
 */
export async function loadManifest(path: string): Promise<ToolManifest> {
  const raw = await fs.readFile(path, 'utf8');
  try {
    return parseManifest(raw);
  } catch (err) {
    if (err instanceof z.ZodError) {
      const flat = err.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`).join('; ');
      throw new Error(`Invalid manifest at ${path}: ${flat}`);
    }
    throw err;
  }
}
