# Researcher roadmap: first implementation tranche

Updated 8 September 2026. Implements part of the [researcher roadmap](2026-09-08-researcher-evaluation-and-roadmap.md), not the entire beta release. Changes are local; production deployment, database migration, live authentication, and GPU execution have not been verified by this implementation pass.

## Implemented

- **Honest provenance:** a shared normalizer preserves unknown, missing, and invalid origins as `unknown`. API results, badges, comparison, decision reports, JSON, CSV, FASTA, and archive manifests retain the origin. A new migration changes the database default to `unknown`; existing historical `real` rows are deliberately not relabeled without evidence.
- **Accounted-for downloads:** bulk export enumerates organization-scoped records beyond the first 500, produces independent files in a ZIP, and includes a manifest with counts, per-file outcomes, provenance, and SHA-256 hashes. Missing/empty downloads produce an explicitly incomplete archive and persistent warning, not a successful completion callback. Structure downloads reject mismatched PDB/CIF formats instead of changing the extension. Missing sequences return an error.
- **Consistent beta admission:** one configuration parser handles `true/on/1`, `false/off/0`, and rejects invalid values. Protected tRPC calls and direct design downloads check admission when enabled; invite claiming and access-status checks remain reachable. App and API must use matching configuration.
- **Clearer availability:** catalog cards distinguish experimental, integrated, non-runnable, and unknown availability. Static fallback no longer invents CPU/runtime availability. Removed the example card's unconditional verification claim. Successful execution and scientific accuracy require separate tool-specific checks.

## Verification completed locally

- Backend: 48 passing tests across research-integrity/admission, design routes, candidate reports, onboarding, and beta suites.
- App: 35 distinct passing tests across archive pagination/failures, export UI completion behavior, CSV, provenance badges, download routes, auth callback, OAuth helper, and catalog regression suites. The archive suite was also rerun with the new export UI tests.
- App and tRPC TypeScript checks passed with `--noEmit --incremental false`.
- Prisma client generation passed. Migration application still requires verification.

Some installed dependency files were empty or blocked reads. They were repaired using frozen-lockfile installs before rerunning checks. Live provider configuration, email delivery and deployed admission behavior still require separate checks. No rendered-browser or mobile accessibility validation was performed.

## Release steps still required

1. Review this tranche alongside existing uncommitted work. Verify pending migration state in the intended beta environment, including the earlier beta-admission migration. Apply `20260908120000_unknown_design_provenance_default` through the normal reviewed release process. Separately audit historical records against execution evidence.
2. Deploy coordinated app/API builds. To require beta admission, set `NEXT_PUBLIC_BETA_GATE=true` for the app build/runtime and API runtime only after the admission schema and intended users/invites are ready. See [deployment environment](../deploy-env.md) and [beta checklist](../BETA-LAUNCH-CHECKLIST.md). Do not enable one side alone.
3. Run the deployed fresh-account matrix: each advertised provider, magic-link delivery, expired/reused links, denied consent, valid/expired/exhausted invitations, returning sessions, and onboarding recovery. Confirm non-admitted accounts cannot bypass the UI through APIs or direct downloads. Use dedicated test accounts and records.
4. Smoke-test ZIP extraction and format validity against representative existing beta records, including more than 500 records and unavailable artifacts. Check incomplete download warnings in a real browser.
5. Reconcile the actually served static marketing homepage with pricing and availability. Qualify the supported release with dated execution/artifact evidence before promoting any integration as verified. The full 52-tool catalog has not been certified as working by these changes.

## Remaining scope and constraints

- Archives have a 128 MB browser-export limit, with an explicit error rather than silent truncation. A server-side streaming/background export is future work for larger records.
- The enumeration cutoff excludes newly created records; it is not a transactionally frozen snapshot of existing records or artifacts.
- These archives account for requested output files. They are not yet full reproducibility packages containing every input, exact runtime/weight identifier, parameter, citation, and selection history.
- A record marked `real` describes its execution origin; scientific validation is separate. Existing historical defaults still need an evidence-based audit.
- Live sign-in reliability, actual tool readiness, retention/deletion verification, pricing consistency, and observed usability remain release work. Provider migration was not attempted.
