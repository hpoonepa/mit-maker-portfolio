# New Job Flow — Design Spec

**Date:** 2026-06-15
**App:** `papercrane/apps/app` (authenticated dashboard, port 3002)
**Status:** Approved design, pending implementation plan

## Goal

Replace the missing job-submission UX with a guided, stepped wizard at `/app/jobs/new`.
A user selects a target, picks one or more design tools (with clear explanations), sets
how many designs to run, chooses how the design budget is allocated across tools when
more than one is picked, reviews, and runs. The flow must work today against the existing
backend (single-`toolId` `jobs.submit`) and the dev-mode stubs — no backend schema change.

## Why

There is currently **no** "start a new job" page outside the onboarding wizard, and the
onboarding `first-job` step is a read-only preview with a faked `jobId` (TODO at
`(dashboard)/onboarding/first-job/page.tsx`). The route `/app/jobs/new` is already
referenced by the duplicate-job flow (`/app/jobs/[id]/duplicate` redirects to
`/app/jobs/new?cloneOf=...`) but does not exist. This spec builds it.

## Layout decision

**Stepped wizard** — one decision per screen, progress bar at top, Next/Back buttons.
Chosen over single-scroll and hybrid-with-sticky-rail. Guided, hard to get into an invalid
state.

## Steps

### Step 1 — Target
- Component: reuse existing `components/jobs/TargetSelector.tsx`, backed by `trpc.targets.list`.
- User picks a saved target, or follows a "New target" CTA (existing `/app/targets` flow).
- Empty state when the org has no targets.
- **Validation:** a target must be selected to advance.
- Carries forward: `targetId`, and the `targetPdb` value needed by `jobs.submit`
  (S3 URI or RCSB PDB id), plus any saved `hotspots` (server auto-includes saved hotspots,
  so the UI need not re-send them).

### Step 2 — Tools (multi-select)
- Component: upgrade existing `components/jobs/ToolPicker.tsx` from radio (single) to
  multi-select. Grid grouped by category (backbone, sequence, structure, composite,
  ranking), data from `trpc.tools.catalog`.
- **Mode banner at top**, plain language:
  - "Run one tool" — pick a single tool; all designs go to it.
  - "Compare several · we allocate" — pick 2+ tools; the budget splits across them.
  - The banner is explanatory, not a hard toggle: the user can simply start checking tools.
    Selecting a 2nd tool flips into compare mode automatically. Deselecting back to 1 returns
    to single mode.
- Per-tool card shows: name, lab/source, license (closed weights in crane red), tier badge.
  Tier-gated tools the org can't run are dimmed/disabled.
- **Tooltip per card:** a short plain-English "what it's good at" line. Source: a static
  description map keyed by tool slug (lives in the app; not a backend change). Falls back to
  the catalog `description` field if no curated line exists.
- **Validation:** at least one tool selected to advance.
- Carries forward: `selectedToolIds: string[]`.

### Step 3 — Designs & Allocation (adaptive)
- **Always:** a "designs" number input + live readout (cost estimate, ETA, seeds remaining
  this period). Reuse `components/jobs/SeedAllocator.tsx` and `components/jobs/CostEstimate.tsx`.
  - 1 tool selected → label "Number of designs". All designs go to that tool.
  - 2+ tools selected → label "Total designs". Split across tools per the chosen strategy.
- **Allocation block (only when 2+ tools):** choose a strategy.
  - **⚡ Auto (per topology)** — recommended default. v1 implementation: a **static per-tool
    weight prior**, normalized across the selected tools and rounded to integers summing to
    the total. **Even-split fallback** when no prior weight exists for a selected tool
    (treat its weight as the neutral/average value). Clearly labeled "v1 allocator" in the
    UI so it reads as an honest heuristic, not a learned model. Leaves a clean seam to swap
    in the real per-topology allocator later.
  - **⚖︎ Even split** — total divided evenly, remainder distributed deterministically
    (first-N tools get the +1).
  - **✎ Manual** — one slider/number per tool; values must sum to the total (live-validated;
    a "remaining: N" helper guides the user).
- Live per-tool design counts shown for every strategy.
- **Validation:** total designs ≥ tool count (each tool gets ≥1); total within seed
  quota/headroom; manual splits must sum to total.
- Carries forward: `totalDesigns: number`, `strategy: 'auto' | 'even' | 'manual'`,
  `perToolCounts: Record<toolId, number>`.

### Step 4 — Review & Run
- Read-only summary: target, the list of tools with their per-tool design counts, total
  cost estimate, total ETA.
- "Run" button submits. Shows a submitting state; on success redirects to `/app/jobs`.
- "Back" returns to Step 3 with all state intact.

## Allocation logic (pure module)

A standalone, unit-testable module (e.g. `lib/jobs/allocation.ts`):

```
allocate(strategy, totalDesigns, toolIds, weightPrior): Record<toolId, number>
```

- **even:** floor(total / n) each, distribute remainder to the first `remainder` tools by
  stable tool order.
- **auto:** look up `weightPrior[toolId]` for each tool (default = neutral weight when
  missing → degenerates to even). Normalize weights, multiply by total, round with a
  largest-remainder method so the parts sum exactly to total and every tool gets ≥1.
- **manual:** identity over user-provided counts (validated to sum to total, each ≥1).

`weightPrior` is a static map in the app (per tool slug). Tools absent from the map use the
neutral weight, which makes auto identical to even — the honest fallback.

## Submission mechanics

- Total designs are split into `perToolCounts` (Step 3 result).
- For each selected tool, generate a `seeds[]` array of length = that tool's count
  (deterministic `1..n` for v1) and issue **one `jobs.submit` call per tool** in parallel
  (`Promise.all`).
- `jobs.submit` input per call:
  ```
  {
    toolId,
    request: {
      targetPdb,           // from selected target
      seeds,               // length = perToolCounts[toolId]
      numDesigns,          // = perToolCounts[toolId]
      // hotspots omitted — server auto-includes saved target hotspots
      // constraints/toolParams omitted in v1
    },
    idempotencyKey         // per (tool, submission) to make Run retry-safe
  }
  ```
- One tool selected = exactly one call (no allocation involved).
- On all-success → redirect to `/app/jobs` (jobs appear via existing list + realtime).
- On partial failure (some tool calls fail) → surface which tools failed via toast/banner;
  successful jobs still proceed. Do not silently drop failures.
- No backend/schema change: the existing single-`toolId` contract, tier allowlist, seed
  quota, GPU-spend cap, concurrency limits, and dev-mode short-circuit all apply per call.

## Components

| Component | New / reuse | Notes |
|---|---|---|
| `jobs/new/page.tsx` | new | Route + wizard orchestration, query-state, submit |
| `JobWizard` shell (stepper + Next/Back/validation) | new | Small; no shared stepper exists today (onboarding uses its own `StepContainer`) |
| `TargetSelector` | reuse | Step 1 |
| `ToolPicker` | reuse, upgrade to multi-select | Step 2; keep single-select behavior available |
| `SeedAllocator` + `CostEstimate` | reuse | Step 3 numbers/cost/ETA |
| Allocation strategy control | new | Step 3 strategy picker + manual sliders |
| `lib/jobs/allocation.ts` | new | Pure split logic |
| tool "good at" description map | new | Static, app-side |

UI primitives from `packages/ui` (Button, Card, Radio, Input, Badge, Tooltip, Banner,
Toast, Spinner). Origami theme tokens (crane / paper / ink, Fraunces / Instrument Sans /
JetBrains Mono, `fold` shadows, `fade-up` animation).

## Error handling

- Step-level validation blocks Next with inline messaging (no silent disabled buttons
  without explanation).
- Quota/cap exceeded → inline warning in Step 3 (reuse `SeedAllocator` headroom alerts) and
  a blocked Run with a clear reason.
- Submit failures → toast/banner naming the failed tool(s); partial success preserved.
- Tier-gated tool selection prevented at the card level (disabled + reason on hover).

## Testing

- **Vitest (unit):** `allocate()` — even remainder distribution, auto normalization +
  largest-remainder rounding summing exactly to total, every tool ≥1, missing-prior →
  even-split fallback, manual sum validation.
- **Vitest (unit):** step-validation predicates (can-advance per step).
- **Playwright (smoke):** happy path — open `/app/jobs/new`, pick a target, select 2 tools,
  accept Auto split, Run, land on `/app/jobs`. Plus the single-tool path (no allocation
  block shown).

## Out of scope (v1)

- Real per-topology learned allocator (seam left; static prior for now).
- User-selectable GPU/compute backend (`gpuBackend` stays server-determined).
- Combined multi-tool single-job backend contract (we submit N jobs instead).
- Constraints/`toolParams` editing in the wizard.
- Batch grouping/ID for the N submitted jobs (jobs land individually in the list).
