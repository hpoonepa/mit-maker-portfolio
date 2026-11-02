/**
 * Ambient shim for `@papercrane/types`.
 *
 * The real types live in `packages/types/src/index.ts` and will be authored
 * as part of that workspace. This shim provides the minimum surface this
 * package needs so we compile and test independently. When the real package
 * defines these exports, TypeScript resolves those first via pnpm workspace
 * resolution and this shim becomes inert for names it already declares.
 *
 * Keep this file narrowly scoped to types actually used here.
 */
declare module '@papercrane/types' {
  /**
   * API key scopes. `'*'` is a wildcard (owner keys). All other scopes are
   * of the form `<resource>:<verb>` — extend as new resources land.
   */
  export type ApiKeyScope =
    | '*'
    | 'jobs:read'
    | 'jobs:write'
    | 'artifacts:read'
    | 'artifacts:write'
    | 'orgs:read'
    | 'orgs:write'
    | 'keys:read'
    | 'keys:write'
    | (string & {});

  /** Org subscription tier. Matches billing plan (see plan 05). */
  export type OrgTier = 'free' | 'pro' | 'frontier';
}
