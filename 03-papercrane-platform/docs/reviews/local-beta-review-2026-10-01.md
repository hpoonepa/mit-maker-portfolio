# Local beta review — 1 October 2026

The local website and product share **http://localhost:4444**. The public page
comes from the existing `../papercrane-website/kriss-replica` checkout. Its
**Open app** link shows sign-in, including for an existing signed-in session,
then returns to `/app`. Unauthenticated product routes still require sign-in.

Start or restore the services from the platform repository:

```sh
pnpm dev:platform
```

The launcher keeps existing listeners, starts durable local Redis when needed,
and serves API :3001, Next app :3002, worker :9090, and website :4444. It needs
the existing local environment file and sibling website checkout. Existing
services must be restarted to pick up changed environment variables.

## Verified

- Browser: existing landing page → Open app → sign-in on the same localhost.
- Before the sign-in entry change: authenticated overview and product navigation
  through :4444; dashboard reported the two completed review jobs.
- New private project → ProteinMPNN input → review → real execution → results.
  Job `50f9904b-4d0e-487f-a987-b5b599019376` completed; authenticated FASTA,
  JSON, CSV, and CIF exports returned 200. Duplicate restored 1CRN and chain A.
- Boltz-2 job `18eeab9b-20f1-4b0b-beb4-ca063a41d60e` completed with real
  provenance and a 57,509-byte coordinate CIF. JSON, CSV, CIF exports returned
  200. FASTA returned the expected unavailable response because this result has
  no sequence field; the result UI hides that format. Visual inspection of this
  new Boltz structure remains outstanding.
- Anonymous jobs API calls are rejected. Main authenticated project, job,
  design, tool, usage, settings, and integrations routes returned 200.
- App suite: 517 tests passed. Authentication regression suite after the final
  sign-in change: 11 tests passed. App typecheck and landing typecheck/build passed.
- Backend suites earlier in the review: 863 tests passed; subsequent focused
  jobs/targets/usage checks passed (48 tests).

## Fixes from the review

Queued cancellation completes without a worker and releases its unstarted
compute reservation. Workers skip cancelled work and guard claim races.
Duplicate/retry restores submitted input without embedding it in URLs. Project
pages query their own jobs and targets. Usage displays actual Seeds by tool;
the global count refreshes. Team tables share a complete roster query instead
of overwriting it with partial initial data.

## Remaining before a hosted beta

No Vercel deployment or infrastructure provisioning was performed. The user
requested local review first. The configured production API is unavailable;
hosted API, worker, and Redis need an agreed deployment. Fresh-account admission,
invitation and completion-email delivery, OAuth return URLs, and hosted payments
have not been validated. The current local review account is not admitted by
the production beta gate. Do not enable that gate without setting up admission.
Browser completion alerts work only while the app is open. Tool execution and scientific
output quality still require checks for each integration.

Original UI restore tag:
`backup/papercrane-ui-before-brand-refresh-2026-09-30`.
The website was checkpointed at `11610c0` before local integration.
