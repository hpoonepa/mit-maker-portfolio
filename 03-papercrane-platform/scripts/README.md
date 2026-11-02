# scripts/

Repo-wide utility scripts. Each script is self-contained and runnable via
`tsx` or Node; nothing here should require a build step.

## Index

| Script          | What it does                                                                                                                                                 |
|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `check-env.ts`  | Validates `.env.local` against the required variable list. Exits non-zero and prints missing vars grouped by scope (`web` / `api` / `worker` / `all`).       |

## Running

Run via `tsx` directly until a root `pnpm check:env` script is added to
`package.json`:

```bash
npx tsx scripts/check-env.ts
```

Once the root `package.json` is updated by the maintainer, the canonical
entry point will be:

```bash
pnpm check:env
```

Suggested root `package.json` script entry (add manually — do not let an
automated agent edit `package.json`):

```json
"scripts": {
  "check:env": "tsx scripts/check-env.ts"
}
```

## Conventions

- Every new script gets a one-line entry in the table above.
- Prefer `tsx`-executable TypeScript over plain JS so types stay in sync with the rest of the monorepo.
- No script should mutate repo state (commit, push, modify `package.json`, etc.) without an explicit flag.
- Scripts must exit non-zero on failure so they can be wired into CI.
