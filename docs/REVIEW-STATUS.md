# Checks on this source snapshot

The checks below were run during the November 2026 preparation pass. They test local software behavior; no new GPU campaign, protein assay or production deployment was run.

These checks ran before media was separated from the source-only GitHub copy. Executable source is unchanged; notebook image outputs and visual assets are supplied separately.

| Area | Result |
| --- | --- |
| MiniBinder | 49 focused tests passed; 9 scorer self-checks passed; all 13 retained CLI commands resolve. |
| PRINCE | 200 focused offline tests passed, 6 optional tests skipped; 64 frozen artifact hashes matched. The broader import/check run and Astro web check timed out in the available local environment, so they are not marked passing. |
| Paper Crane | All 52 tool dispatch mappings passed their dry-run checks; 12 fake-provider worker tests passed. These tests do not execute the upstream GPU models. |
| SENBA and Studio | 47 selected SENBA tests and 8 subtests passed. The saved viewer rendered in Chrome/WebGL, MD playback advanced, and all 8 served assets matched their file hashes. |
| Ember research | 60 contract tests passed without loading model modules. This work has no trained release in the snapshot. |
| SquashVision backend | 555 distinct tests passed: 537 in the restricted run and 18 local-server tests in the permitted loopback rerun. |
| SquashVision frontend | 234 tests in 31 files passed; full and production TypeScript checks passed; Vite production build passed. |
| Original source preservation | Header restorations were checked against original bodies, ASTs or token streams. Python dependency metadata and executable file modes were restored. Original working folders were not overwritten. |

The project guides give setup requirements for model downloads, GPU providers, databases and authentication. Saved demonstrations work independently of a fresh training or design campaign. SENBA Studio has its own saved-viewer checks documented in its README.

Historical verification records remain in the project folders with their original dates. They do not replace this current check summary.
