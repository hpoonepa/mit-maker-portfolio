# @papercrane/storage

Cloudflare R2 client wrapper for Paper Crane artifacts (targets, designs, logs,
metrics). Thin layer on top of `@aws-sdk/client-s3` plus presigned-URL helpers
and the R2 key layout from plan 01 §6.

## Install

Workspace package — referenced via `workspace:*` from `apps/*`. No standalone
install; run `pnpm install` at the repo root.

## Config

`createR2Client(config?)` resolves from env if a field is not passed:

| Env var | Required | Description |
|---|---|---|
| `R2_ACCOUNT_ID` | yes | Cloudflare account id — endpoint is derived as `https://{accountId}.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | yes | R2 access key |
| `R2_SECRET_ACCESS_KEY` | yes | R2 secret |
| `R2_BUCKET` | yes | Default bucket (e.g. `papercrane-prod`) |
| `R2_ENDPOINT` | no | Explicit endpoint override (mainly for local mock) |

Region is pinned to `auto` (R2 convention).

## Usage

```ts
import {
  createR2Client,
  presignGet,
  presignPut,
  uploadObject,
  streamObject,
  deletePrefix,
  orgTargetKey,
  jobDesignKey,
  jobLogKey,
  jobPrefix,
  sha256Tee,
} from "@papercrane/storage";

const r2 = createR2Client();

// Presigned URLs (default TTL 15 min)
const getUrl = await presignGet(r2, orgTargetKey("org_1", "tgt_1"));
const putUrl = await presignPut(
  r2,
  orgTargetKey("org_1", "tgt_1"),
  "chemical/x-pdb",
  1_234_567, // content length bound into the signature
);

// Direct upload (small bodies)
await uploadObject(r2, jobDesignKey("org_1", "job_1", 42), cifBytes, {
  contentType: "chemical/x-cif",
  meta: { seed: "42" },
});

// Stream download
const { body, contentType } = await streamObject(
  r2,
  jobLogKey("org_1", "job_1", 0),
);

// Retention sweeper — delete every artifact under a job prefix
const result = await deletePrefix(r2, jobPrefix("org_1", "job_1"));
console.log(`deleted ${result.deleted}, errors ${result.errors.length}`);
```

## Key layout (plan 01 §6)

```
r2://papercrane-prod/
  orgs/{org_id}/targets/{target_id}/input.pdb
  orgs/{org_id}/jobs/{job_id}/designs/{seed}.cif
  orgs/{org_id}/jobs/{job_id}/logs/worker-{attempt}.log
  orgs/{org_id}/jobs/{job_id}/metrics.parquet
```

All ids are validated (`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`) so key builders
can't be tricked into path traversal.

## Scripts

```bash
pnpm --filter @papercrane/storage test
pnpm --filter @papercrane/storage typecheck
```
