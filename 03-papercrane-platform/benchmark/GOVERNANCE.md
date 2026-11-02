# Paper Crane Benchmark — Governance

This document describes the governance structure, conflict-of-interest
policy, submission review workflow, and dispute resolution process for
the Paper Crane binder design benchmark. It is binding on all
maintainers, advisory panelists, and external submitters.

## 1. External Advisory Panel

The benchmark is overseen by an **External Advisory Panel** of three
(3) external members, rotating on staggered two-year terms.

### Composition

- **Three external members.** "External" means not employed by, not
  contracted by, and not holding equity in Paper Crane or any entity
  that produces a tool currently listed on the benchmark leaderboard.
- **Domain coverage.** The panel is constituted to cover, across its
  three seats: (a) computational structural biology, (b) experimental
  protein engineering or biochemistry, and (c) machine-learning
  methodology or statistics.
- **Term length.** Two years, staggered so that one seat rotates each
  year (with one seat rotating every other year). No panelist may
  serve two consecutive full terms, but may return after a one-term
  cooldown.

### Duties

1. Review methodology-version PRs (see §3 below).
2. Vote on new-target admissions after the 7-day public comment
   window (see `targets/README.md`).
3. Review external submissions for compliance with the
   reproducibility contract (methodology §11) and adjudicate
   reproducibility disputes.
4. Publish an annual public statement summarizing the year's
   decisions, declined submissions, and any methodology changes
   considered.

### Selection and Rotation

- Outgoing panelists nominate candidates; current panelists vote
  (simple majority) with Paper Crane maintainers holding veto only
  for declared conflicts of interest.
- Nominations and final selections are announced publicly at least
  30 days before the seat turnover.

## 2. Conflict of Interest (CoI) Policy

### Paper Crane Team Disclosures

- All Paper Crane team members who contribute to the benchmark must
  publicly disclose, in a dedicated `DISCLOSURES.md` file (to be
  added at v1.0 publication):
  - Employment, consulting, and advisory relationships with any
    entity producing a tool listed on the benchmark.
  - Equity, options, or other financial interests in such entities.
  - Grant funding from such entities.
  - Personal relationships (collaborations, co-authorship within
    the past 5 years) with maintainers of listed tools.

### Advisory Panel Disclosures

- Advisory panelists disclose the same categories upon appointment
  and annually thereafter. Disclosures are published on the
  benchmark website.

### Recusal

- A panelist or maintainer with a disclosed CoI on a specific
  submission, target proposal, or methodology change **must recuse**
  from voting on that item. Recusal is recorded publicly.
- If recusals leave fewer than two eligible panelists on an item,
  decision is deferred to the next eligible quorum or to a one-time
  ad-hoc reviewer appointed jointly by the non-conflicted
  panelist(s) and maintainers.

### Paper Crane's Own Tools

- Any future Paper Crane tool or method submitted to the benchmark
  is marked as such on the leaderboard and reviewed under a
  stricter protocol: (a) at least two external panelists (no
  recusals) must approve the submission, (b) the run manifests must
  be produced by an independent re-run commissioned by the advisory
  panel on a compute environment not controlled by Paper Crane.

## 3. Submission Review Workflow

### Tool-Result Submissions (Leaderboard Entries)

1. **Open a PR** that adds signed run manifests under
   `benchmark/manifests/<target_id>/<tool_id>/`. Do not modify the
   methodology or target files in a results PR.
2. **CoI disclosure.** The PR description must state any CoI the
   submitter has with Paper Crane or with the tool being submitted.
3. **CI checks.** The PR must pass the automated methodology-gate
   CI (`.github/workflows/benchmark-methodology-gate.yml` for
   methodology PRs; an analogous results-gate for manifest PRs, to
   be added) which validates manifest signatures, fingerprints, and
   schema conformance.
4. **Review.** At least **two Paper Crane maintainers** AND at
   least **one external advisory panelist** must approve the PR.
5. **Reproducibility spot-check.** At the panel's discretion, the
   advisory panel may commission an independent re-run of any
   submission before merging. Failure to reproduce within the
   published CI triggers the dispute process (§4).
6. **Merge and publish.** Merged manifests automatically appear on
   the leaderboard, tagged with the methodology commit hash under
   which they were scored.

### Methodology Version PRs

1. Open a PR that creates a new `methodology-vX.Y.md` (never edit
   the existing file).
2. PR must be **GPG-signed** by a Paper Crane maintainer.
3. PR must cite the specific change being made and its scientific
   or procedural justification.
4. **30-day public comment window** (announced on the benchmark
   website and any public channels).
5. **Approvals required:** at least 2 Paper Crane maintainers AND
   at least 2 external advisory panelists (out of 3), with no
   recusals counted as approvals.
6. After merge, the new methodology version is published with its
   commit hash; old versions remain immutable.

### Target Addition PRs

See [`targets/README.md`](targets/README.md). Process is similar to
methodology PRs but with a 7-day comment window instead of 30, and
requires only 1 external panelist approval (plus the usual 2
maintainers).

## 4. Dispute Resolution — Public RFC Process

Disagreements over (a) methodology interpretation, (b) submission
eligibility, (c) reproducibility failures, or (d) leaderboard ranking
are resolved by **public Request-for-Comment (RFC)**.

### Process

1. **Filing.** Any maintainer, panelist, or submitter may file an
   RFC by opening an issue labeled `rfc` in the repository. The
   issue must state the specific dispute, the proposed resolution,
   and any relevant evidence (manifests, reproduction logs, etc.).
2. **Public comment window.** RFCs are open for **30 calendar
   days** for public comment. During this window, the disputed
   submission or methodology item is labeled `under-rfc` on the
   leaderboard; it is not removed, but the label is visible.
3. **Resolution.** At the end of the window, the advisory panel
   votes (simple majority, recusals enforced). If the vote is
   1-1 with a recusal, Paper Crane maintainers are tiebreaker. If
   Paper Crane has a CoI, an ad-hoc external reviewer is appointed
   per §2.
4. **Publication.** The resolution, vote tally (with recusals
   noted), and rationale are published as a comment on the RFC
   issue and archived in `benchmark/rfcs/` (to be created at first
   RFC).
5. **Appeals.** A losing party may re-file an RFC only with
   material new evidence (e.g. a new reproduction attempt, a
   corrected manifest). Bare-disagreement re-files are closed
   without prejudice.

### Emergency Suspension

If a submission is demonstrated to violate §11 of the methodology
(e.g. fraudulent manifest signatures, fabricated inputs), a majority
of the advisory panel can **immediately suspend** the submission
from the leaderboard pending RFC. Suspension is visible on the
leaderboard and does not constitute a finding of misconduct.

## 5. Amendments to This Document

`GOVERNANCE.md` itself is amended via the same process as a
methodology version PR (§3): GPG-signed commit, 30-day public
comment, 2 maintainer + 2 panelist approvals. Amendments are not
retroactive to in-flight submissions or RFCs.
