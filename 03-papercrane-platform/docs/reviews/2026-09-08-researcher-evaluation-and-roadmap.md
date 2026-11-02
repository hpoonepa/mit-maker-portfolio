# Paper Crane: researcher evaluation and improvement roadmap

Reviewed 8 September 2026. Prepared by Codex with an independent **GPT-6 Astra** review using the perspective of a principal investigator, computational researcher, and first-time graduate student. These are evaluation lenses, not a claim of academic credentials or external peer review.

## Decision

Paper Crane has a promising research-workspace foundation. Its value is bringing tool access, execution, interpretation, collaboration, and exports into one place. The newer decision reports and explicit scientific caveats are meaningful progress.

I would not yet recommend relying on it for manuscript evidence or unattended lab-wide work. The next milestone should be a small, supported research pilot **after** the integrity and activation gates below pass. The central problem is consistency: a result's origin, execution history, limitations, and completeness are not preserved equally well across all surfaces.

The three largest investments should be:

1. **Trustworthy execution and claims:** prove the supported beta workflows, preserve honest provenance, and align the website with what is deployed.
2. **Reliable activation:** make signup, invitation, workspace creation, and return visits work without founder intervention.
3. **Auditable research records:** make results understandable, comparisons defensible, and exports complete enough for a colleague to inspect independently.

## Scope and evidence limits

- Inspected current marketing and platform source, exports, reporting, comparison, auth, onboarding, readiness declarations, status and retention code, and launch documentation. Astra independently inspected the scientific and research-workflow surfaces.
- The local marketing homepage returned HTTP 200. Its response and middleware confirmed that `/` is rewritten to `public/_landing/index.html`. Its actual text was inspected. The React homepage is a separate implementation and must not be assumed to be what visitors see.
- A local `/login` header request timed out after 15 seconds. This is one local observation, not a production outage finding.
- The browser runtime reported no available browser. Visual observations are limited to the user-provided catalog screenshot and source-level layout inspection. Current rendered desktop/mobile behavior, keyboard navigation, measured contrast, and authenticated interaction remain unverified.
- Some local files timed out during reads. The main readiness configuration was corroborated through its tests and public catalog rather than directly read. No automated test suite, live authentication flow, GPU job, or production security audit was performed in this review.
- September 4 history—successful R2 smoke, three deployed GPU apps, and a failed ProteinMPNN live invocation—is historical evidence only. It does not establish September 8 deployment health.
- No product code, deployment, account configuration, or GPU infrastructure was changed for this review.

Research criteria draw on the importance of reusable metadata and workflows in the [FAIR Guiding Principles](https://www.nature.com/articles/sdata201618), and on publishing data, model and code details in [Reproducibility standards for machine learning in the life sciences](https://www.nature.com/articles/s41592-021-01256-7). The specific product priorities and proposed targets below are our judgments, not requirements imposed by those papers.

## What is good—and worth preserving

| Existing strength | Why a researcher cares | Evidence |
|---|---|---|
| Purpose and input filters | Users can start with the task and available data instead of memorizing model names. | Supplied screenshot; `apps/app/components/tools/CatalogGrid.tsx` |
| Distinctive paper/editorial visual identity | The supplied screen has a coherent hierarchy and restrained palette. This is a useful base, although full accessibility remains untested. | Supplied screenshot; `apps/app/components/tools/CatalogCard.tsx:42` |
| Example run with cost and availability feedback | Reduces the effort required to learn the product and makes compute spending visible. | `apps/app/components/jobs/ExampleRunCard.tsx:83` |
| Explicit queued/preparing/running states | Researchers need to know whether a long job is progressing and when partial results exist. | `apps/app/components/jobs/JobWaitScreen.tsx:164` |
| Existing execution metadata | Tool version, adapter version, image digest and target checksum provide a foundation for auditability. | `packages/db/prisma/schema.prisma:203`; job detail `apps/app/app/(dashboard)/app/jobs/[id]/page.tsx:454` |
| New decision report | Includes execution versions, provenance, methodology, caveats and JSON/CSV downloads. This is substantially better than a bare score table. | `packages/trpc/src/reporting/candidateDecisionReport.ts:15`; `apps/app/components/jobs/CandidateDecisionReport.tsx:133` |
| Scientific restraint in important places | The score panel says it uses computational evidence and that its evaluation is unresolved. The benchmark withholds results pending reproducible execution. | `apps/app/components/designs/MetaScorePanel.tsx:130`; `apps/web/app/benchmark/page.tsx:37` |
| Collaboration and durable onboarding foundations | Snapshots, comments, tags, invitations and persisted progress address real lab workflows. | `packages/db/prisma/schema.prisma:163`; `packages/trpc/src/routers/onboarding.ts:170` |

These features merit consolidation and validation. Replacing the visual system or starting another catalog expansion would not address the largest adoption barriers.

## Where professors and researchers will lose trust

### 1. Missing provenance is treated as real output — critical

`normaliseProvenance` substitutes `real` when provenance is missing. The decision-report builder does the same. A legacy or incomplete record can therefore lose the warning intended to distinguish examples from verified execution.

Evidence: `apps/app/components/designs/ProvenanceBadge.tsx:18`; `packages/trpc/src/reporting/candidateDecisionReport.ts:112`.

**Required outcome:** unknown origin stays visibly unverified in every view and download. Record origin and execution verification separately: a real model invocation is not experimental validation. Historical rows require evidence before promotion. Comparison and export paths must preserve these labels.

### 2. Bulk export can silently omit files — critical

The Export Center requests a maximum of 500 designs without paginating, skips non-success responses, concatenates different formats into a text file, and reports the original design count as completed.

Evidence: `apps/app/components/exports/ExportPanel.tsx:55`, `:97`, `:103`, `:112`.

**Required outcome:** export all selected records or state the limit explicitly; keep each file independently usable; include a manifest of requested, exported and failed items; never report success when files were omitted. A 501-record test and an injected download failure must produce honest counts. Remove user-visible implementation TODOs at line 174.

### 3. Downloads do not consistently preserve the research record — critical for research adoption

The single-design export query omits provenance and execution versions. Requested PDB and CIF downloads share a branch that streams identical stored bytes without conversion. The newer decision-report JSON preserves more context, but still does not constitute a complete archive of inputs, submitted parameters, weight references and artifact hashes.

Evidence: `apps/app/app/api/designs/[id]/export/[format]/route.ts:119`, `:186`, `:235`; `packages/trpc/src/reporting/candidateDecisionReport.ts:18`.

**Required outcome:** format labels, extensions and bytes agree; unsupported formats are refused clearly. A research archive includes inputs and hashes, actual parameters, tool/adapter/runtime/weight identifiers, seeds, outputs, metric definitions, provenance, citations, selection history and a short methods summary. A colleague can understand what ran without the original account.

### 4. Readiness labels lack accessible execution evidence — critical before wider beta

Checked-in tests declare 12 GA tools and 39 beta-runnable tools, with one unavailable catalog entry. These are release declarations, not current successful executions. The catalog card does not include readiness in its display model. The example card also appends a fixed “verified” label.

Evidence: `packages/trpc/tests/toolReadiness.test.ts:13`; `apps/app/components/tools/CatalogCard.tsx:21`; `apps/app/components/jobs/ExampleRunCard.tsx:89`.

**Required outcome:** one readiness record feeds marketing, catalog, picker, API and examples. Distinguish catalog entry, experimental integration, recently verified supported use, and temporarily unavailable. Verification includes environment, exact release, supported input case, date and successful artifact retrieval. Do not infer scientific accuracy from an execution badge.

### 5. The visible homepage and other site surfaces tell different stories — high

The actual homepage says “Distribution should land,” promises automatic runner selection, shows every main lane as available, and presents a 2.5% versus 13.25% comparison without a visible citation in the extracted text. The benchmark page separately withholds Paper Crane results pending reproducibility. These may refer to different evidence, but the relationship is not explained.

The homepage advertises Pro at $200 per seat with unlimited campaigns; the pricing route's structured data describes $299 per lab with a design quota. This establishes a metadata/landing mismatch, not what Stripe currently charges. The unused React hero still describes twelve tools while its roster describes 52.

Evidence: `apps/web/middleware.ts:64`; `apps/web/public/_landing/index.html`; `apps/web/app/pricing/page.tsx:28`; `apps/web/components/hero/HeroCopy.tsx:58`; `apps/web/components/sections/Hero.tsx:133`.

**Required outcome:** establish one deployed homepage source and one source for plan entitlements. Make the first screen state who the product serves, the concrete task it supports, and what is available in beta. Any percentage or performance comparison must identify source, cohort, outcome, conditions and whether it is external literature or a Paper Crane result. Remove or qualify claims without that support. Do not present an illustrative CLI transcript as a measured live result.

### 6. Scientific interpretation varies across views — high

The meta-score panel contains useful limitations, but the decision report prominently labels a lead candidate and displays a score and confidence category. Its confidence is derived from metric coverage; this must not read like a calibrated likelihood of biological success. Some metric descriptions use stronger language than the computational-only framing supports.

Evidence: `apps/app/components/designs/MetaScorePanel.tsx:130`; `apps/app/components/jobs/CandidateDecisionReport.tsx:179`; `packages/trpc/src/reporting/candidateDecisionReport.ts:114`; `apps/app/components/designs/MetricInterpretation.tsx:127`.

**Required outcome:** distinguish observed measurements, model confidence, heuristic ranking and evidence coverage. Give every metric a definition, unit/range, scope, missing/not-applicable behavior and source. Make the caveats survive exports and screenshots. Have a domain reviewer check the specific language and applicability; a generic disclaimer is insufficient.

### 7. Comparison and related-job views can remove necessary context — high

Comparison highlights the best numeric value but its data model lacks provenance, input identity and execution versions. Its metric alias handling differs from other surfaces. RelatedJobs can include recent organization jobs when project information is missing.

Evidence: `apps/app/components/designs/CompareView.tsx:4`, `:35`, `:100`; `apps/app/components/jobs/RelatedJobs.tsx:68`.

**Required outcome:** compare only with visible input/method context, label incompatible comparisons, preserve missing values, and use one metric dictionary. Store explicit parent/project relationships; absent lineage must not be guessed.

### 8. Activation code has improved, but live completion remains unproven — critical for beta

OAuth availability checks now prevent offering a known-disabled Google flow. Invitation claiming uses the authenticated identity and durable admission state. Onboarding completion waits for persistence. These are real improvements. They do not verify deployed provider settings, real email receipt, redirects, database migrations or fresh-account access.

There is a concrete configuration trap: the launch checklist says `NEXT_PUBLIC_BETA_GATE=on`, while the callback and layout check for the exact string `true`.

Evidence: `apps/app/components/auth/OAuthButtons.tsx:55`; `packages/trpc/src/routers/beta.ts:306`; `apps/app/app/(dashboard)/onboarding/done/page.tsx:37`; `docs/BETA-LAUNCH-CHECKLIST.md:117`; `apps/app/app/auth/callback/route.ts:55`.

**Required outcome:** validate a deployed fresh-account matrix covering each advertised sign-in method, email delivery, expired/reused links, denied consent, valid/expired/exhausted invites, returning users, workspace recovery and session expiry. Gate admission on server APIs as well as pages. Use a single validated configuration parser; test the launch instructions themselves.

### 9. Operational and retention promises need evidence — high

The status page has no live worker check. The inspected retention routine marks jobs purged and explicitly leaves artifact sweeping to future work. This does not prove that storage lifecycle rules are absent, but it does mean this code alone cannot substantiate deletion guarantees. Published retention periods also make timely export essential for researchers.

Evidence: `apps/web/app/status/page.tsx:53`; `apps/worker/src/retention.ts:7`; `apps/web/app/privacy/page.tsx:58`.

**Required outcome:** monitor the actual user path through queue, worker and artifact retrieval. Establish retry/cancellation behavior and cost accounting. Verify actual storage lifecycle and backup behavior against the policy, show expiry dates and archive reminders, and test restoration and deletion on dedicated test records. No claim of security certification follows from source inspection.

## Researcher-centered product design

**For a PI:** make a project review answer “What ran, what did it cost, what can we conclude, and can my student reproduce the record?” Put methods, ownership, provenance, budget and archive status close to the result.

**For a computational researcher:** preserve exact configuration and versions; support consistent metric tables, filtering, documented APIs and complete downloads. Make parameter changes and reruns explicit in project history.

**For a new graduate student:** offer “Explore an example” before account or GPU setup, then a supported task with clear inputs, cost and expected output. Distinguish a precomputed demonstration from a live run. Validate the experience with real users rather than assuming a preset is understandable.

**For the catalog UI:** keep purpose/input filters, add visible availability and known limitations, and default to an approachable supported set with access to the complete catalog. Put task, accepted input, output and cost ahead of GPU details. Offer a compact table for experienced users; retain cards for discovery. Avoid multiplying filters until user tests justify them.

**For results:** use a concise summary followed by evidence, limitations, comparison and export. Show the reason behind each recommendation and leave room for researcher notes and dissent. Tables, downloadable data and textual explanations must remain useful without the 3D viewer.

**For visual usability:** preserve the paper identity, increase very small labels used for essential information, reduce excessive vertical space before useful content, and ensure keyboard focus and non-color status labels. Validate 200% zoom, reduced motion, narrow screens, long names, empty/error states and screen-reader navigation in a connected browser. These are proposed checks, not measured failures.

Suggested homepage message: “Run supported protein research tools, inspect the evidence, and export a reproducible research record.” Primary action: explore a clearly labeled example. Secondary action: request beta access. Follow with one supported workflow, dated availability, an example report, data handling, understandable pricing and contact/support expectations.

## Delivery roadmap

Estimates are planning ranges, not delivery promises. Assume two engineers with part-time product/design and scientific review. Unknown deployment configuration and existing unfinished changes can extend them. Complete release gates rather than launching because a calendar date arrives.

| Phase | Suggested window | Main work | Suggested owner | Exit condition |
|---|---|---|---|---|
| 0. Establish current truth | 1–2 working days | Map served routes and deployment versions; inventory tool evidence and auth settings; reconcile pricing and readiness claims; triage pending migrations and read failures. | Engineering lead + product | A dated evidence register identifies implemented, tested, deployed and unknown states separately. |
| 1. Earn beta trust | Next 1–2 weeks | Correct provenance defaults; unify beta configuration; complete fresh-account activation; qualify a small supported tool set; fix basic export omission/format bugs; reconcile served homepage claims. | Backend + frontend | All critical gates below pass in the beta environment. |
| 2. Complete the research record | Following 2–3 weeks | Deliver archive manifest and valid files; unify metric definitions and provenance; add comparison context and explicit lineage; improve retention visibility. | Backend + scientific reviewer | A second person audits a complete exported example without access to the original account. |
| 3. Supervised research pilot | Following 2 weeks | Recruit a small consented cohort; observe activation and task completion; improve unclear UI, errors and documentation; measure support demand and costs. | Product + engineering + researcher | Researchers complete the supported task and archive independently; critical issues are closed. |
| 4. Broader adoption | Following 3–6 weeks, evidence-dependent | Expand integrations based on demand; improve collaboration/permissions; publish independently reproduced examples; strengthen retention and operating procedures. | Engineering lead + scientific reviewer | Added scope passes the same evidence gates and operating costs remain sustainable. |

Phase 1 can prepare deployment fixes and activation in parallel. Phase 2 depends on stable provenance and execution records. Phase 3 depends on usable archives, not only successful job submission. A compute-provider migration is a separate decision informed by measured cold/warm start, completion rate, cost per completed job and operator effort; GPU ownership alone does not settle it.

## Concrete first backlog

| Order | Deliverable | Acceptance criteria |
|---|---|---|
| 1 | Route and claim inventory | Actual `/`, catalog, pricing, docs and app entry routes mapped; static/React ownership explicit; unsupported claims flagged; one reviewed entitlement definition. |
| 2 | Provenance correction | Missing origin never becomes verified; fixture/unverified/real origin survives list, detail, comparison, reports and downloads; historical records handled explicitly. |
| 3 | Activation qualification | Every advertised login flow passes on fresh accounts in the target environment; invite replay does not consume capacity; incomplete onboarding resumes; direct API admission is checked. |
| 4 | Supported-release evidence | Each promoted tool has a dated execution record, correct persisted artifact and supported-input scope; errors and retries have clear user outcomes. |
| 5 | Honest basic exports | All selected records accounted for, including more than 500; format parsers accept returned files; simulated missing files are shown as failures. |
| 6 | Reproducibility archive | Input/output hashes, actual configuration, versions, seeds, method citations, metric definitions and provenance travel together; a reviewer reconstructs execution context. |
| 7 | Unified result interpretation | One metric dictionary; confidence/coverage terms defined; experimental scorer labels visible wherever rankings appear. |
| 8 | Comparison and lineage | Input identity and method versions visible; mismatches flagged; unrelated organization jobs cannot be called siblings. |
| 9 | Operations and data lifecycle | Queue/worker/artifact checks, honest cancellation and partial states, expiry notice, archive recovery and deletion verification documented. |
| 10 | Observed usability improvements | Five representative people attempt the same supported task; record failure points and complete the highest-impact fixes before expanding scope. |

## Release gates and pilot measurements

These are proposed internal acceptance targets, not achieved results or industry standards.

- **Integrity gate:** zero silent export omissions; zero missing-origin records presented as verified; every advertised download format parses; every promoted integration has dated execution evidence.
- **Activation gate:** every supported auth scenario passes the matrix, including negative cases. Proposed initial target: at least 9 of 10 invited participants reach their workspace unaided. Treat this small sample as a discovery signal, not a population reliability estimate.
- **Workflow gate:** selected supported tools complete at least 19 of 20 representative valid test jobs, with every failure explained and accounted for. Include both cold and warm starts; report sample size and failure classes rather than making a blanket reliability claim.
- **Research handoff gate:** a second reviewer identifies input, method/version, parameters, outputs, limitations and completeness using only the archive. Exact numerical rerun equivalence may require documented tolerances and runtime conditions.
- **Usability gate:** five representative participants attempt discovery, setup, result interpretation and export. Record completion, confusion and help requests. Include at least one keyboard-only and one narrow-screen walkthrough.
- **Operational gate:** show estimated versus actual costs, supported cancellation behavior, expiry dates and a support contact. Record time to acknowledge and resolve beta incidents.

Track a weekly funnel from invitation → authenticated workspace → supported job → inspected result → complete archive → later return. Segment failures by stage and workflow. Measure queue delay, execution duration, artifact retrieval, retry rate, export completeness, support requests and cost per completed job. Use aggregate events and IDs; keep raw research inputs out of routine analytics.

## Later work and deliberate deferrals

After pilot evidence supports expansion, add integrations requested repeatedly by active users, richer project review and ownership transfer, versioned shareable reports, and documented interoperability with existing research workflows. Each integration needs a maintainer, license/source metadata, supported input contract and regression evidence.

Defer another large catalog expansion, a major visual rebrand, additional sign-in providers, a provider migration, enterprise promises, and more elaborate automated recommendations until the existing supported journey is reliable. Keep the current benchmark release gate; an independently reviewed, reproducible example will be more persuasive than a larger unqualified tool count.

The desired next demonstration is simple: a new researcher enters successfully, runs a supported task, understands what the output does and does not establish, exports a complete record, and hands it to a colleague who can audit it. That is the adoption test for the next release.
