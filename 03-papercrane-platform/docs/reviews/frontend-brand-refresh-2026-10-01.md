# Platform brand refresh — 2026-10-01

The local platform at http://localhost:3002 now uses papercrane.bio's night palette, Instrument Sans, and folded-crane mark. The reference was checked in the live website and its local route-shell styles.

## Original version and rollback

Before editing the frontend, all existing `apps/app` changes were saved in commit `2483834e25c6b6aeb90c587c28cc5465ad265903`:

```text
chore(app): checkpoint frontend before Papercrane brand refresh
```

The permanent local Git tag for that version is:

```text
backup/papercrane-ui-before-brand-refresh-2026-09-30
```

To restore the original frontend, first commit any later frontend work you want to keep, then run from the repository root:

```sh
git restore --source=backup/papercrane-ui-before-brand-refresh-2026-09-30 -- apps/app
git add apps/app
git commit -m "Restore frontend before brand refresh"
```

The redesign is a separate commit immediately after the checkpoint. It can also be reverted using `git revert` with its commit ID. Neither approach requires resetting the repository or changing backend files. These are local Git saves; nothing was pushed remotely.

## Changes

- Exact public-site background `oklch(0.16 0.018 160)`, text `oklch(0.94 0.016 148)`, muted text `oklch(0.73 0.028 152)`, and mint accent `oklch(0.81 0.10 153)`.
- Open layouts across projects, jobs, designs, tools, settings, and the job wizard. Decorative frames, rules, uppercase kickers, and repeated introductory copy removed. Form controls, selections, status information, and scientific results retain their purpose.
- Shared responsive navigation, authentic crane icons, and the same live workspace shell on the overview route.
- Example configuration and input glossaries are expandable in the wizard.
- Fixed client filter URL updates so clearing search and browser Back/Forward preserve the expected results without updating the router during a React state update.
- Added the shared UI source directory to Tailwind content scanning and styled the root error fallback to match the site.

## Verification

- App suite: **71 files, 493 tests passed**.
- TypeScript: `pnpm --filter @papercrane/app typecheck` passed.
- ESLint checked changed frontend files with no errors. Existing warnings remain for the member avatar image and the global error boundary's error-ID memo dependency.
- `git diff --check -- apps/app` passed.
- Browser checks at desktop and 390px mobile widths covered navigation, projects, jobs, designs, tools, settings, the overview, and the initial job-wizard steps. No page-level horizontal overflow on the checked mobile pages; the designs table scrolls within its container.
- Project search, clear, Back, and Forward were exercised in the browser and covered by two new hook tests.
- The authenticated login route redirects to the overview. A signed-out form session and all scientific tools were not exercised; no compute job was submitted.

The frontend remains available on port 3002. The API and worker were left running. Existing changes outside `apps/app` were not included in either frontend commit.
