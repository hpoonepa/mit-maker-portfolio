# Job workflow update — 2026-10-01

- Overview starts with Boltz-2, BindCraft, and ProteinMPNN shortcuts. Recent jobs follow; usage is compact at the bottom.
- Molecular dynamics waitlist uses authenticated Feedback records with `metadata.waitlist = molecular-dynamics`. The button restores saved membership and only confirms after a successful write. No notification/email delivery was added.
- Catalog defaults to runnable tools. Tool names and Run actions open that tool's input step directly.
- Target creation happens inside the current job. On save, the target list refreshes and the new target is selected; the tool and parameters remain mounted. Inspecting a saved target opens a separate tab.
- Initial single-tool jobs default to one run. Review copy, decorative panels, and unnecessary animations were reduced.

## Validation

- Frontend suite: 73 files, 501 tests passed, followed by 3 additional waitlist UI tests passing.
- Waitlist router: 5 tests passed (auth, account scoping, persistence, repeat submission, failed write).
- App TypeScript and ESLint on changed files passed.
- Browser: Tools → BindCraft → inline public 1CRN target creation → saved target selected → review reached without launching compute.
- Overview verified at desktop and 390px width; no horizontal overflow. Live waitlist status endpoint responds successfully after restarting the local API.

## Viewer diagnosis and recovery points

- Viewer fix is a separate commit, `bcc8b43`. Saved Boltz result `fd796373-330f-4c38-afdb-1b433245d1cc` contains a single chain and 23 discontinuities between consecutive backbone residues. It came from a 10-sampling-step smoke run. The viewer now reports those discontinuities and defaults to atoms for that artifact, with real chain labels and a dark background; it does not alter scientific coordinates. No prediction was rerun.
- Original frontend: `2483834e25c6b6aeb90c587c28cc5465ad265903`, tagged `backup/papercrane-ui-before-brand-refresh-2026-09-30`.
- First clean brand refresh: `6af446d`.
- The blue cursor halo shown in the user's desktop capture was not found in app source or the live page DOM. Its browser/desktop origin remains unconfirmed; no system setting was changed.

Browser validation created one public test target named `UX verification · 1CRN` (`f7ac789f-1d37-4a23-bc58-20c81064a33b`) in the demo workspace.
