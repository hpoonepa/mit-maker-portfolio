# @papercrane/auth

HTTP-framework-agnostic auth primitives for Paper Crane.

Two principals, one context:

- **API key** — server-to-server / CLI calls. Format `pc_<env>_sk_<26b62>`.
  Stored as `{ prefix, argon2id(fullKey) }`; verified with `argon2.verify`.
- **User session** — Supabase-issued RS256 JWT, verified against the project's
  JWKS with signature + `iss` + `aud` + `exp` checks.

## Install

Workspace package. Consumed by `@papercrane/trpc` and the Fastify API.

## Usage

```ts
import {
  generateApiKey,
  verifyApiKey,
  hasScope,
  verifySupabaseJwt,
  buildApiKeyContext,
  requireScope,
  AuthError,
} from '@papercrane/auth';

// Issue a new key
const { fullKey, prefix, hash } = await generateApiKey('live');
// store { prefix, hash } — reveal fullKey to the user exactly once

// Verify an incoming key
const ok = await verifyApiKey(incoming, row.hash);

// Verify a Supabase JWT
const payload = await verifySupabaseJwt(token, { projectRef: 'abcd1234' });

// Enforce scopes
requireScope(ctx, 'jobs:write'); // throws ForbiddenError on denial
```

## API key format

```
pc_live_sk_<26 base62>   # production
pc_test_sk_<26 base62>   # test mode
```

Entropy: 26 base62 chars ≈ 154 bits.

Prefix length: 8 chars (`pc_live_`, `pc_test_`) — stored plaintext for UI.

## Argon2id parameters

| Param | Value |
|---|---|
| `type` | `argon2id` |
| `memoryCost` | `2^16` KiB (64 MiB) |
| `timeCost` | `3` |
| `parallelism` | `1` |

Exceeds OWASP 2023 minimums. Bumping these later remains backwards-compatible
because argon2 encodes params in the hash string; rehash on next successful
verify if you want to migrate.

## Scopes

`hasScope` supports exact-match and `'*'` wildcard (owner keys only). Scope
strings are defined in `@papercrane/types#ApiKeyScope`.

`requireScope(ctx, scope)`:
- No-op for user principals (RBAC lives elsewhere).
- Throws `ForbiddenError` (HTTP 403) for API keys lacking the scope.

## Errors

- `AuthError` — HTTP 401. Subclass for any auth failure.
- `ForbiddenError` — HTTP 403. Subclass of `AuthError`.

HTTP adapters (Fastify plugin, tRPC middleware) translate these into responses.
This package never imports an HTTP framework.

## Testing

```bash
pnpm --filter @papercrane/auth test
pnpm --filter @papercrane/auth typecheck
```

JWT tests stub `globalThis.fetch` to serve a locally-generated JWKS; no network.
