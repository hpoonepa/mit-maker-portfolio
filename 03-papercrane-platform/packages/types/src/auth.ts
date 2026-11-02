import { z } from 'zod';

/**
 * Plan tier — drives quota, concurrency, and tool availability.
 */
export const TierSchema = z.enum(['free', 'pro', 'frontier'] as const);
export type Tier = z.infer<typeof TierSchema>;

/**
 * Alias for {@link Tier}. Several internal packages refer to the org
 * subscription tier as `OrgTier`; both names point at the same enum.
 */
export const OrgTierSchema = TierSchema;
export type OrgTier = Tier;

/**
 * Granular API key permissions.
 */
export const ApiKeyScopeSchema = z.enum([
  'jobs:read',
  'jobs:write',
  'designs:read',
  'targets:write',
  'usage:read',
  'usage:write',
  'keys:manage',
  'admin:*',
  '*',
] as const);
export type ApiKeyScope = z.infer<typeof ApiKeyScopeSchema>;

/**
 * Resolved auth context attached to every authenticated request.
 */
export const AuthContextSchema = z
  .object({
    userId: z.string().uuid(),
    orgSlug: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
    tier: TierSchema,
    scopes: z.array(ApiKeyScopeSchema).min(1),
    keyId: z.string().uuid().optional(),
  })
  .strict();
export type AuthContext = z.infer<typeof AuthContextSchema>;
