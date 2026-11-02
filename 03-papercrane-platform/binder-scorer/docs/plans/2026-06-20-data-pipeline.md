# Paper Crane — Data Pipeline Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax. Every step is TDD: write the FAILING test, run it, see it fail, write minimal code, run it, see it pass, commit.

**Goal:** Build the data foundation for the Paper Crane meta-scorer: a leakage-safe ETL from the public Proteinbase download, a public-real-label harvester, a feature-backfill runner, and a new-target metric-blind data-generation protocol — all producing the shared-contract `DesignRow`/`LabelRow` records that the (separate) modeling package consumes. This plan is DONE when the pipeline is correct and provenance-clean; it is **NOT** gated on any modeling/LOTO result.

**Architecture:** Three packages, run with `pytest` from the repo root `/Users/harsha/Desktop/claudeprojects/mosaic` (absolute imports, mirroring the `dynamics/` POC layout):
- `pc_contracts/` — the **ONE** shared-contract module (`DesignRow`, `LabelRow`, `TargetFeatures`, `INTERFACE_CLASSES`). Imported by both this data package and the modeling package. No business logic.
- `data/` — **this plan's deliverable**: ETL, harvest, backfill, wet-lab packaging, outcome ingest, selection/missingness diagnostics, and the offline Postgres label/flywheel DDL.
- `scorer/` — the modeling package (feature extractor, LLM prior, corrector, LOTO eval). **Out of scope here**; referenced only as the downstream consumer.

**Tech Stack:** Python 3.11, `pytest`==8.3.3 + `pytest-mock`==3.14.0 (TDD), `pandas`==2.2.2, `numpy`==1.26.4, `scikit-learn`==1.5.2, `requests`==2.32.3, `biopython`==1.83, an injected Anthropic LLM client (duck-typed, never imported at module top), Postgres DDL (raw idempotent SQL, mirrors `papercrane/benchmark/migrate/src/loaders/ddl.sql`). External GPU runner reused via dependency injection from `nebius/runner.py` (`run_validation_job`) — never imported in unit tests.

---

## Audit Patches Applied (2026-06-26)

**Verdict:** GO_WITH_FIXES from a 41-agent adversarial audit. Zero fatal flaws; 7 data-side fixes baked in below. All patches preserve TDD structure (failing test → minimal impl → commit).

| # | Patch | New Task(s) |
|---|-------|-------------|
| A | **Canonical metric key** — bare `boltz2_min_ipsae` silently no-ops diagnostics; standardize on `canonical_metric_key` = `computational__boltz2_min_ipsae` everywhere; add ban test for bare key. | Task 10 |
| B | **Assay-type field carry-through** — heterogeneous assays (Overath/Proteinbase/BindCraft) pooled; carry `assay` field through ingestion so downstream eval can run within-assay and assay-stratified ablations. | Task 12 |
| C | **Nipah license + dual panel** — Nipah is ~2/3 of public data; add `license` field per row; produce `full-11` and `commercial-clean-10` panels; add 1-hr license-diligence task for Adaptyv/Proteinbase Nipah entry. | Task 21 |
| D | **`is_real_label` hardening** — extend `SILICO_LABEL_MARKERS` with af3/alphafold/chai/esmfold/esm/rosetta/rfdiffusion/bindcraft_metric; add fail-CLOSED source `ALLOWLIST` at ingest boundary; keep allowlist outside `is_real_label` so new assay names aren't auto-dropped. | Task 15 |
| E | **Dedup canonical-source assertion** — after dedup to 5,721 sequences, assert each target is pulled from a single canonical source; log cross-source label-conflicts before dropping. | Task 20 |
| F | **`was_tested` propensity instrumentation** — labeled designs reached wet lab partly due to score selection (MNAR); emit `was_tested` indicator + computational features needed for downstream IPW-corrected headline delta. | Task 40 |
| G | **Pure-negative target handling** — targets with no positives (HSA, TNFA, GM2A, ORM2) must be excluded from ranking/LOTO folds and routed to a specificity/false-positive diagnostic set. | Task 34 |

---

**Label-integrity invariants (enforced by tests, not prose):**
1. **Real labels only.** `binds` derives **only** from the explicit experimental `binding` boolean conditioned on `expressed`. It is **never** derived from `kd.notna()` nor from the banned circular benchmark hit-rule (`ipSAE>=0.70 AND DockQ>=0.23 AND pTMEnergy<=-1.2`). Task 7 is a dedicated, named ban test.
2. **No leakage.** Every `experimental__*` column is hard-excluded from features by a **prefix-based** guard that runs **after** the JSON-explode (Task 9). A unit test FAILS if any experimental column reaches `X`.
3. **Field renames pinned at the contract boundary:** Proteinbase `binding` → `binds`, `kd` → `kd_nm` (molar→nM), `binding_strength` kept verbatim.
4. **Curated target mapping is hand-built + audited, NEVER regex-derived** (Task 3; pd-l1 `cytokine_receptor` mislabel fixed by hand → `sheet_flat`).
5. **Baseline provenance:** the retired pooled `0.806` AUC for `boltz2_min_ipsae` is recorded ONLY as a provenance artifact (Task 4 constant) and is **explicitly NOT** the LOTO bar — the bar is `min_ipSAE` recomputed **within each LOTO fold** (a modeling concern, noted in the DoD handoff, not implemented here).

---

## File Structure

```
pc_contracts/                       # SHARED CONTRACTS — imported by data/ and scorer/
  __init__.py                       # re-exports DesignRow, LabelRow, TargetFeatures, INTERFACE_CLASSES, CANONICAL_METRIC_KEY
  core.py                           # the dataclasses + TypedDict + INTERFACE_CLASSES + CANONICAL_METRIC_KEY (single source of truth)
  requirements.txt
  tests/
    __init__.py
    conftest.py
    test_contracts.py               # (1) exact-field-shape tests

data/                               # THIS PLAN — data pipeline package
  __init__.py
  requirements.txt
  targets.py                        # curated competition->target table; pd-l1 fix
  etl.py                            # parse_evaluations, flatten, build_design_row, derive_binds, build_label_row, explode, sha256;
                                    # SILICO_LABEL_MARKERS, is_real_label, INGEST_SOURCE_ALLOWLIST, assert_source_allowed (Task 15);
                                    # NIPAH_TARGET_IDS, is_nipah_target, build_dual_eval_panels (Task 21);
                                    # PURE_NEGATIVE_TARGETS, tag_pure_negative_targets, split_by_positive_coverage (Task 34)
  leakage.py                        # assert_no_leakage, build_feature_frame, assert_designs_clean, KNOWN_EXPERIMENTAL_METRICS
  missingness.py                    # NMAR diagnostic (metric-present vs metric-absent positive rate)
  labels.py                         # harvest constants (VALID_AMINO_ACIDS, ALLOWED_BINDING_STRENGTHS) + dict round-trip; assay field
  harvest_validators.py             # deterministic gates (sequence/target-id/allowed-label)
  dedup.py                          # dedup by (target_id, sequence); assert_single_source_per_target; drop_cross_source_conflicts
  label_store.py                    # master JSONL load/append
  harvest.py                        # source/license registry + LLM parse + harvest_labels orchestration
  feature_space.py                  # raw tool panel -> Proteinbase computational__* columns
  backfill.py                       # make_design_row, manifest, cost_summary, backfill_features, run_panel_via_nebius, join
  target_selection.py               # gap-filling interface-class target selection
  metric_blind.py                   # metric-blind sampling (top-k + uniform non-top; uses CANONICAL_METRIC_KEY default)
  wetlab_submission.py              # FASTA + provenance manifest packaging
  ingest_outcomes.py                # returned binding results -> REAL LabelRows -> NDJSON handoff
  selection_diagnostics.py          # was_tested-AUC + range-restriction (experimental cols banned);
                                    # PropensityRecord, emit_propensity_fields for IPW (Task 40)
  db/
    schema.sql                      # targets/designs/labels/predictions/experimental_outcomes/allocation_events
  tests/
    __init__.py
    conftest.py                     # FIXTURES_DIR + REPO_ROOT
    fixtures/
      proteinbase_sample.csv
      cao2022_sample.txt
    test_targets.py                 # (2)
    test_etl.py                     # (3)
    test_circular_label_ban.py      # (4) MUST-FIX #3
    test_leakage.py                 # (5)
    test_canonical_metric_key.py    # (6) AUDIT-A: bare key ban
    test_missingness.py             # (7) MUST-FIX #5
    test_assay_field.py             # (8) AUDIT-B: assay carry-through
    test_schema.py                  # (9)
    test_labels.py                  # (10)
    test_is_real_label.py           # (11) AUDIT-D: hardened is_real_label + ALLOWLIST
    test_harvest_validators.py      # (12)
    test_dedup.py                   # (13)
    test_dedup_source_assert.py     # (14) AUDIT-E: canonical-source assertion
    test_nipah_license.py           # (15) AUDIT-C: Nipah license + dual panel
    test_label_store.py             # (16)
    test_harvest.py                 # (17)
    test_feature_space.py           # (18)
    test_backfill.py                # (19)
    test_target_selection.py        # (20)
    test_pure_negative_targets.py   # (21) AUDIT-G: pure-negative routing
    test_metric_blind.py            # (22)
    test_wetlab_submission.py       # (23)
    test_ingest_outcomes.py         # (24)
    test_selection_diagnostics.py   # (25)
    test_was_tested_propensity.py   # (26) AUDIT-F: IPW propensity fields
```

**27 test files total** (1 in `pc_contracts/tests/`, 26 in `data/tests/`). All `pytest` commands run from `/Users/harsha/Desktop/claudeprojects/mosaic`.

---

## Phase 0: License + label audit GATE

This is a **blocking gate on PUBLICATION / external-claim usage of harvested data**, not on writing pipeline code. Pipeline code proceeds with clearly-marked placeholder license strings; data may not be published or used in a headline claim until these are resolved.

- [ ] **P0 license gate — Proteinbase.** Confirm the redistribution/usage license of `https://storage.proteinbase.com/proteinbase_all_data_28_01_2026.csv`. Record the decision (allowed / restricted / pending) in the source-license registry (`data/harvest.py` `SOURCE_LICENSES` is for harvest sources; Proteinbase license is stamped in `data/etl.py` as `PROTEINBASE_LICENSE`, currently `"proteinbase-public-download:LICENSE-GATE-PENDING"`). **Acceptance:** no `LabelRow` from Proteinbase is published/exported externally while the license string still contains `LICENSE-GATE-PENDING`.
- [ ] **P0 license gate — harvest sources.** For each of `cao-2022, adaptyv, ppb-affinity, skempi-2.0, sabdab`, confirm the real license; the registry strings in `data/harvest.py` are PLACEHOLDERS (`CC-BY-4.0`) until confirmed. The registry's job in code is provenance integrity (only registered sources may enter the table; license is stamped deterministically, never LLM-supplied). **Acceptance:** unregistered sources hard-raise (tested, Task 23).
- [ ] **Nipah license diligence (AUDIT-C, ~1 hr).** Nipah virus G / Proteinbase is ~two-thirds of the public labeled dataset. Pull the exact LICENSE attached to the Adaptyv Nipah entry and the Proteinbase bulk download. Record in `PROTEINBASE_LICENSE` (in `data/etl.py`) and `SOURCE_LICENSES["adaptyv"]` (in `data/harvest.py`) whether the license resolves to ODbL or CC-BY. **Key legal note:** ODbL and CC-BY both permit commercial model *training* (share-alike attaches only to redistributing the derived *database*, not to shipping model weights or scores). If the license is confirmed CC-BY/ODbL, remove the `LICENSE-GATE-PENDING` marker. If unclear, escalate — do NOT proceed with a commercial claim. **Acceptance:** the license string no longer contains `LICENSE-GATE-PENDING` for Nipah data, OR the escalation is logged and all external claims exclude Nipah rows. Task 21 (dual panel) produces a `commercial-clean-10` panel that excludes Nipah as a fallback regardless.
- [ ] **Curated-target audit (MUST-FIX #6).** The competition→target mapping in `data/targets.py` is **hand-built and audited**, never regex-derived from raw evaluations JSON. Specifically audit and fix the `papercrane/benchmark/targets/pd-l1.yaml` `cytokine_receptor` mislabel: PD-L1 / CD274 is an Ig-superfamily immune-checkpoint LIGAND with a flat beta-sheet epitope → `interface_class = "sheet_flat"`; `il-7ra` is the genuine cytokine receptor (helical). **Acceptance:** Task 3 test `test_pd_l1_class_bug_is_fixed` passes, and every curated `interface_class` is in the four-value enum.
- [ ] **Baseline provenance note (MUST-FIX #1).** Record `PROTEINBASE_POOLED_AUC_RETIRED = 0.806` (Task 4) as a single-feature **pooled** ROC-AUC of `computational__boltz2_min_ipsae` on `df_denovo` — a **retired provenance artifact**. It is **NOT** the bar the per-target prior must beat. The real bar is `min_ipSAE` **recomputed within each LOTO fold** (a modeling concern, owned by `scorer/`, not implemented here). **Acceptance:** the constant's docstring states this explicitly; no code in `data/` uses `0.806` as a threshold.

---

## Task 1 — Shared-contract package `pc_contracts`

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/__init__.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/core.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/requirements.txt`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/tests/__init__.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/tests/conftest.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/tests/test_contracts.py`

- [ ] Create `pc_contracts/requirements.txt`:
```
pytest==8.3.3
pytest-mock==3.14.0
```
- [ ] Create `pc_contracts/tests/__init__.py` (empty) and `pc_contracts/tests/conftest.py`:
```python
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
```
- [ ] Write the FAILING test `pc_contracts/tests/test_contracts.py`:
```python
from __future__ import annotations

from dataclasses import fields

from pc_contracts.core import (
    INTERFACE_CLASSES,
    VALID_INTERFACE_CLASSES,
    DesignRow,
    LabelRow,
    TargetFeatures,
)


def test_designrow_has_exact_contract_fields():
    names = {f.name for f in fields(DesignRow)}
    assert names == {
        "design_id", "target_id", "tool", "tool_version", "config_hash",
        "seed", "sequence", "metrics", "metric_blocks_present",
        "cost_usd", "wallclock_sec",
    }


def test_labelrow_has_exact_contract_fields():
    names = {f.name for f in fields(LabelRow)}
    assert names == {
        "design_id", "target_id", "sequence", "binds", "binding_strength",
        "kd_nm", "expressed", "source", "license", "provenance",
        "metric_blind_sampled",
    }


def test_interface_classes_are_exactly_the_four():
    assert INTERFACE_CLASSES == ("helical", "sheet_flat", "mixed", "ligand_present")
    assert VALID_INTERFACE_CLASSES == {"helical", "sheet_flat", "mixed", "ligand_present"}


def test_target_features_is_a_typeddict_with_interface_class_key():
    tf: TargetFeatures = {"target_id": "pd-l1", "interface_class": "sheet_flat"}
    assert tf["interface_class"] == "sheet_flat"
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'pc_contracts'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest pc_contracts/tests/test_contracts.py -v
```
- [ ] Minimal implementation `pc_contracts/core.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TypedDict

# The four-value interface taxonomy (design §7). SINGLE SOURCE OF TRUTH —
# data/ and scorer/ both import these names from here.
INTERFACE_CLASSES: Tuple[str, str, str, str] = (
    "helical", "sheet_flat", "mixed", "ligand_present",
)
VALID_INTERFACE_CLASSES = frozenset(INTERFACE_CLASSES)


@dataclass(frozen=True)
class DesignRow:
    design_id: str
    target_id: str
    tool: str
    tool_version: str
    config_hash: str
    seed: int
    sequence: str
    metrics: Dict[str, float]
    metric_blocks_present: Dict[str, bool]
    cost_usd: float
    wallclock_sec: float


@dataclass(frozen=True)
class LabelRow:
    design_id: str
    target_id: str
    sequence: str
    binds: Optional[bool]
    binding_strength: Optional[str]
    kd_nm: Optional[float]
    expressed: Optional[bool]
    source: str
    license: str
    provenance: str
    metric_blind_sampled: bool


class TargetFeatures(TypedDict, total=False):
    target_id: str
    pdb_id: str
    chain: str
    hotspots: Optional[List[int]]
    log_length: float
    disorder_fraction: float
    frac_helix: float
    frac_strand: float
    frac_loop: float
    epitope_planarity_rmsd: Optional[float]
    pocket_volume: Optional[float]
    druggability: Optional[float]
    epitope_hydrophobicity: Optional[float]
    epitope_net_charge: Optional[float]
    frac_polar: float
    interface_class: str
```
- [ ] Minimal implementation `pc_contracts/__init__.py`:
```python
from pc_contracts.core import (  # noqa: F401
    INTERFACE_CLASSES,
    VALID_INTERFACE_CLASSES,
    DesignRow,
    LabelRow,
    TargetFeatures,
)
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest pc_contracts/tests/test_contracts.py -v
```
- [ ] Commit:
```
git add pc_contracts/__init__.py pc_contracts/core.py pc_contracts/requirements.txt pc_contracts/tests/__init__.py pc_contracts/tests/conftest.py pc_contracts/tests/test_contracts.py
git commit -m "pc_contracts: shared DesignRow/LabelRow/TargetFeatures + INTERFACE_CLASSES single source

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 2 — `data/` package scaffold

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/__init__.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/requirements.txt`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/__init__.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/conftest.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/fixtures/.gitkeep`

- [ ] Create `data/__init__.py` (empty), `data/tests/__init__.py` (empty), `data/tests/fixtures/.gitkeep` (empty).
- [ ] Create `data/requirements.txt`:
```
biopython==1.83
numpy==1.26.4
pandas==2.2.2
requests==2.32.3
scikit-learn==1.5.2
pytest==8.3.3
pytest-mock==3.14.0
```
- [ ] Create `data/tests/conftest.py`:
```python
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
```
- [ ] Verify the contract dependency is importable:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && python -c "from pc_contracts.core import DesignRow, LabelRow, TargetFeatures, INTERFACE_CLASSES; print('ok')"
```
Expected output: `ok`
- [ ] Commit:
```
git add data/__init__.py data/requirements.txt data/tests/__init__.py data/tests/conftest.py data/tests/fixtures/.gitkeep
git commit -m "data: scaffold data-pipeline package mirroring dynamics layout

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 3 — Curated competition→target mapping (pd-l1 class fix, hand-built)

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/targets.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_targets.py`

- [ ] Write the FAILING test `data/tests/test_targets.py`:
```python
from __future__ import annotations

from data.targets import (
    CURATED_TARGETS,
    VALID_INTERFACE_CLASSES,
    get_curated_target,
    resolve_target_id,
)


def test_resolve_is_explicit_alias_lookup_case_insensitive():
    assert resolve_target_id("PD-L1") == "pd-l1"
    assert resolve_target_id("cd274") == "pd-l1"
    assert resolve_target_id("RBD") == "sars-cov2-rbd"
    assert resolve_target_id("CD127") == "il-7ra"


def test_unknown_target_maps_to_unknown_not_a_derived_key():
    assert resolve_target_id("something-unmapped") == "unknown"
    assert resolve_target_id(None) == "unknown"
    assert resolve_target_id("") == "unknown"


def test_pd_l1_class_bug_is_fixed():
    pdl1 = get_curated_target("pd-l1")
    # papercrane/benchmark/targets/pd-l1.yaml mislabels this 'cytokine_receptor'.
    assert pdl1.interface_class != "cytokine_receptor"
    assert pdl1.interface_class == "sheet_flat"
    assert pdl1.pdb_id == "5O45"
    assert pdl1.uniprot == "Q9NZQ7"


def test_every_curated_interface_class_is_in_the_four_value_enum():
    for t in CURATED_TARGETS:
        assert t.interface_class in VALID_INTERFACE_CLASSES
    assert VALID_INTERFACE_CLASSES == {
        "helical", "sheet_flat", "mixed", "ligand_present",
    }
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.targets'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_targets.py -v
```
- [ ] Minimal implementation `data/targets.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from pc_contracts.core import VALID_INTERFACE_CLASSES  # single source of truth


@dataclass(frozen=True)
class CuratedTarget:
    target_id: str
    pdb_id: str
    chain: str
    uniprot: str
    interface_class: str
    aliases: Tuple[str, ...]


# HAND-BUILT, AUDITED mapping. Keys are hand-listed aliases — NEVER regex-derived
# from raw evaluations JSON (MUST-FIX #6). pd-l1 is corrected here: PD-L1 / CD274
# is an Ig-superfamily immune-checkpoint LIGAND with a flat beta-sheet epitope,
# so its interface_class is 'sheet_flat'. It is NOT 'cytokine_receptor' (the
# label in papercrane/benchmark/targets/pd-l1.yaml is biologically wrong);
# il-7ra is the genuine cytokine receptor (helical bundle).
CURATED_TARGETS: Tuple[CuratedTarget, ...] = (
    CuratedTarget("pd-l1", "5O45", "A", "Q9NZQ7", "sheet_flat",
                  ("pd-l1", "pdl1", "cd274", "b7-h1", "pd l1")),
    CuratedTarget("sars-cov2-rbd", "6M0J", "E", "P0DTC2", "sheet_flat",
                  ("sars-cov2-rbd", "rbd", "spike-rbd", "sars-cov-2 rbd")),
    CuratedTarget("il-7ra", "3UP1", "A", "P16871", "helical",
                  ("il-7ra", "il7ra", "il-7 receptor", "cd127")),
)

_ALIAS_INDEX = {
    alias: t.target_id for t in CURATED_TARGETS for alias in t.aliases
}


def resolve_target_id(raw_target: Optional[str]) -> str:
    if not raw_target:
        return "unknown"
    return _ALIAS_INDEX.get(str(raw_target).strip().lower(), "unknown")


def get_curated_target(target_id: str) -> Optional[CuratedTarget]:
    for t in CURATED_TARGETS:
        if t.target_id == target_id:
            return t
    return None
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_targets.py -v
```
- [ ] Commit:
```
git add data/targets.py data/tests/test_targets.py
git commit -m "data: hand-built curated target table; fix pd-l1 cytokine_receptor mislabel

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 4 — `parse_evaluations` + `flatten_proteinbase` (JSON-explode ETL)

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_etl.py`

- [ ] Write the FAILING test `data/tests/test_etl.py`:
```python
from __future__ import annotations

import pandas as pd

from data.etl import (
    PROTEINBASE_POOLED_AUC_RETIRED,
    flatten_proteinbase,
    parse_evaluations,
)


def test_retired_pooled_auc_is_provenance_only_not_a_threshold():
    # MUST-FIX #1: 0.806 is a RETIRED pooled artifact, NOT the LOTO bar.
    assert PROTEINBASE_POOLED_AUC_RETIRED == 0.806


def test_parse_evaluations_flattens_type_double_underscore_metric():
    raw = (
        '[{"type":"experimental","metric":"kd","value":"8.99e-09"},'
        '{"type":"computational","metric":"boltz2_min_ipsae","value":"0.82",'
        '"target":"PD-L1"}]'
    )
    out = parse_evaluations(raw)
    assert out["experimental__kd"] == 8.99e-09
    assert out["computational__boltz2_min_ipsae"] == 0.82
    assert out["target_from_eval"] == "PD-L1"


def test_parse_evaluations_handles_empty_and_malformed():
    assert parse_evaluations("[]")["target_from_eval"] is None
    assert parse_evaluations("not json")["target_from_eval"] is None
    assert parse_evaluations(None)["target_from_eval"] is None


def test_parse_evaluations_keeps_non_numeric_value_as_string():
    out = parse_evaluations(
        '[{"type":"experimental","metric":"binding_strength","value":"Strong"}]'
    )
    assert out["experimental__binding_strength"] == "Strong"


def test_flatten_proteinbase_expands_columns():
    df = pd.DataFrame(
        {
            "id": ["d1"],
            "designMethod": ["RFdiffusion"],
            "sequence": ["MKAALEW"],
            "evaluations": [
                '[{"type":"computational","metric":"boltz2_min_ipsae",'
                '"value":"0.82","target":"PD-L1"}]'
            ],
        }
    )
    flat = flatten_proteinbase(df)
    assert "computational__boltz2_min_ipsae" in flat.columns
    assert "target_from_eval" in flat.columns
    assert "evaluations" not in flat.columns
    assert flat.loc[0, "target_from_eval"] == "PD-L1"
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.etl'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py -v
```
- [ ] Minimal implementation `data/etl.py` (start the file):
```python
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pc_contracts.core import DesignRow, LabelRow
from data.targets import resolve_target_id

# RETIRED PROVENANCE ARTIFACT (MUST-FIX #1). This is the single-feature POOLED
# ROC-AUC of computational__boltz2_min_ipsae on df_denovo from the original
# `Proteinbase Analysis.ipynb`. It is NOT cross-validated, its per-target AUC is
# NaN, and it is EXPLICITLY NOT the bar the per-target prior must beat. The LOTO
# bar is min_ipSAE recomputed WITHIN EACH FOLD (owned by scorer/, not here).
PROTEINBASE_POOLED_AUC_RETIRED = 0.806

_TARGET_KEYS = ("target", "target_name", "targetName")
_NULL_STRINGS = {"", "none", "n/a", "na"}


def _coerce_value(value: Any) -> Any:
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in _NULL_STRINGS:
        return s
    try:
        return float(s)
    except ValueError:
        return s


def parse_evaluations(eval_str: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    target: Optional[str] = None
    try:
        entries = json.loads(eval_str) if eval_str else []
    except (json.JSONDecodeError, TypeError):
        entries = []
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        etype = str(entry.get("type", "")).strip().lower().replace(" ", "_")
        metric = str(entry.get("metric", "")).strip().lower().replace(" ", "_")
        if etype and metric:
            out[f"{etype}__{metric}"] = _coerce_value(entry.get("value"))
        if target is None:
            for key in _TARGET_KEYS:
                if entry.get(key):
                    target = str(entry[key]).strip()
                    break
    out["target_from_eval"] = target
    return out


def flatten_proteinbase(df: pd.DataFrame) -> pd.DataFrame:
    parsed = pd.json_normalize(df["evaluations"].apply(parse_evaluations))
    base = df.drop(columns=["evaluations"]).reset_index(drop=True)
    return pd.concat([base, parsed.reset_index(drop=True)], axis=1)
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_etl.py
git commit -m "data: parse_evaluations + flatten_proteinbase JSON-explode; retired-AUC provenance constant

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 5 — `build_design_row` (computational-only metrics + metric_blocks_present)

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_etl.py`

- [ ] Add the FAILING tests to `data/tests/test_etl.py`:
```python
from data.etl import build_design_row


def _rec_with_experimental():
    return {
        "id": "d1",
        "designMethod": "RFdiffusion",
        "sequence": "MKAALEW",
        "computational__boltz2_min_ipsae": 0.82,
        "computational__esmfold_plddt": 88.0,
        "experimental__kd": 8.99e-09,
        "experimental__binding": 1.0,
        "target_from_eval": "PD-L1",
    }


def test_build_design_row_excludes_experimental_from_metrics():
    d = build_design_row(_rec_with_experimental(), target_id="pd-l1")
    assert all(not k.startswith("experimental__") for k in d.metrics)
    assert d.metrics["computational__boltz2_min_ipsae"] == 0.82
    assert d.design_id == "d1"
    assert d.target_id == "pd-l1"
    assert d.tool == "RFdiffusion"
    assert d.seed == -1


def test_build_design_row_metric_blocks_present():
    d = build_design_row(_rec_with_experimental(), target_id="pd-l1")
    assert d.metric_blocks_present["boltz2"] is True
    assert d.metric_blocks_present["esmfold"] is True
    assert d.metric_blocks_present["proteinmpnn"] is False


def test_build_design_row_config_hash_is_deterministic():
    rec = _rec_with_experimental()
    assert build_design_row(rec, "pd-l1").config_hash == build_design_row(rec, "pd-l1").config_hash
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'build_design_row'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py::test_build_design_row_excludes_experimental_from_metrics -v
```
- [ ] Add to `data/etl.py`:
```python
_COMP_PREFIX = "computational__"
_EXPERIMENTAL_PREFIX = "experimental__"

# Representative real metric column per panel block (grounding column names;
# note the misspelling 'complimentarity' is intentional / load-bearing).
METRIC_BLOCKS: Dict[str, str] = {
    "boltz2": "computational__boltz2_min_ipsae",
    "esmfold": "computational__esmfold_plddt",
    "proteinmpnn": "computational__proteinmpnn_score",
    "shape_complementarity": "computational__shape_complimentarity_boltz2_binder_ss",
    "physchem": "computational__isoelectric_point",
    "ted": "computational__ted_confidence",
}


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def build_design_row(rec: Dict[str, Any], target_id: str) -> DesignRow:
    metrics: Dict[str, float] = {}
    for key, value in rec.items():
        if key.startswith(_COMP_PREFIX):
            num = _as_float(value)
            metrics[key] = num if num is not None else float("nan")
    blocks = {
        block: _is_present(rec.get(col)) for block, col in METRIC_BLOCKS.items()
    }
    method = str(rec.get("designMethod") or "unknown")
    sequence = str(rec.get("sequence") or "")
    config_hash = hashlib.sha256(f"{method}|{sequence}".encode()).hexdigest()[:16]
    return DesignRow(
        design_id=str(rec["id"]),
        target_id=target_id,
        tool=method,
        tool_version="unknown",
        config_hash=config_hash,
        seed=-1,
        sequence=sequence,
        metrics=metrics,
        metric_blocks_present=blocks,
        cost_usd=0.0,
        wallclock_sec=0.0,
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_etl.py
git commit -m "data: build_design_row keeps computational-only metrics + block presence

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 6 — `derive_binds` + `build_label_row` (explicit binding bool; field renames; KD molar→nM)

This is the headline-label-integrity step. `binds` derives from the explicit `experimental__binding` boolean conditioned on `experimental__expressed`, **NOT** from `experimental__kd.notna()`. Field renames are pinned: `binding`→`binds`, `kd`→`kd_nm` (molar→nM), `binding_strength` kept.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_etl.py`

- [ ] Add the FAILING tests to `data/tests/test_etl.py`:
```python
from data.etl import build_label_row, derive_binds


def test_derive_binds_uses_explicit_boolean_not_kd():
    # Expressed + binding flag true -> binder.
    assert derive_binds(binding_val=1.0, expressed_val=1.0) is True
    # Expressed but binding flag false -> honest negative.
    assert derive_binds(binding_val=0.0, expressed_val=1.0) is False
    # Not expressed -> binding undeterminable.
    assert derive_binds(binding_val=0.0, expressed_val=0.0) is None
    # No data -> None (NOT coerced to a binder via KD).
    assert derive_binds(binding_val=None, expressed_val=None) is None


def test_build_label_row_field_renames_and_kd_molar_to_nm():
    rec = {
        "id": "d1",
        "sequence": "MKAALEW",
        "experimental__kd": 8.99e-09,        # molar in raw CSV
        "experimental__binding": 1.0,
        "experimental__expressed": 1.0,
        "experimental__binding_strength": "Strong",
    }
    lr = build_label_row(rec, target_id="pd-l1")
    assert lr.binds is True                  # 'binding' -> 'binds'
    assert lr.expressed is True
    assert lr.kd_nm == 8.99e-09 * 1e9        # 'kd' (molar) -> 'kd_nm'
    assert lr.binding_strength == "Strong"   # kept verbatim
    assert lr.source == "proteinbase"
    assert lr.metric_blind_sampled is False
    assert "proteinbase" in lr.license.lower()
    assert "row_id=d1" in lr.provenance


def test_build_label_row_no_kd_does_not_force_binder():
    rec = {"id": "d2", "sequence": "GGS",
           "experimental__binding": 0.0, "experimental__expressed": 1.0}
    lr = build_label_row(rec, target_id="pd-l1")
    assert lr.binds is False
    assert lr.kd_nm is None
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'build_label_row'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py::test_derive_binds_uses_explicit_boolean_not_kd -v
```
- [ ] Add to `data/etl.py`:
```python
PROTEINBASE_SOURCE = "proteinbase"
PROTEINBASE_LICENSE = "proteinbase-public-download:LICENSE-GATE-PENDING"
PROTEINBASE_CSV_NAME = "proteinbase_all_data_28_01_2026.csv"


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip().lower()
    if s in {"1", "1.0", "true", "yes"}:
        return True
    if s in {"0", "0.0", "false", "no"}:
        return False
    return None


def derive_binds(binding_val: Any, expressed_val: Any) -> Optional[bool]:
    """Explicit binding boolean conditioned on expression.

    NEVER uses experimental__kd.notna() (circular, banned), and NEVER uses any
    in-silico hit-rule (ipSAE/DockQ/pTMEnergy). See test_circular_label_ban.py.
    """
    binding = _to_bool(binding_val)
    expressed = _to_bool(expressed_val)
    if binding is True:
        return True  # measured binding implies it expressed
    if expressed is True and binding is False:
        return False  # honest negative: expressed, tested, did not bind
    return None  # undeterminable


def build_label_row(rec: Dict[str, Any], target_id: str) -> LabelRow:
    kd_molar = _as_float(rec.get("experimental__kd"))
    kd_nm = kd_molar * 1e9 if _is_present(kd_molar) else None
    strength = rec.get("experimental__binding_strength")
    strength = strength if isinstance(strength, str) and strength.strip() else None
    return LabelRow(
        design_id=str(rec["id"]),
        target_id=target_id,
        sequence=str(rec.get("sequence") or ""),
        binds=derive_binds(rec.get("experimental__binding"),
                           rec.get("experimental__expressed")),
        binding_strength=strength,
        kd_nm=kd_nm,
        expressed=_to_bool(rec.get("experimental__expressed")),
        source=PROTEINBASE_SOURCE,
        license=PROTEINBASE_LICENSE,
        provenance=f"{PROTEINBASE_CSV_NAME}:row_id={rec['id']}",
        metric_blind_sampled=False,
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_etl.py
git commit -m "data: derive_binds from explicit binding bool (binding->binds, kd->kd_nm molar->nM)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 7 — CIRCULAR-LABEL BAN test (named, explicit)

A dedicated test asserting **no** code path derives `binds` from `kd.notna()` nor from the banned benchmark hit-rule (`ipSAE>=0.70 AND DockQ>=0.23 AND pTMEnergy<=-1.2`). Combines behavioral assertions with a static source-scan of `derive_binds`.

**Files:**
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_circular_label_ban.py`

- [ ] Write the FAILING test `data/tests/test_circular_label_ban.py`:
```python
from __future__ import annotations

import inspect

from data.etl import build_label_row, derive_binds

# Tokens that would indicate a circular / in-silico-derived label.
_BANNED_TOKENS = (
    "kd", "notna", "dockq", "ptm", "ipsae", "ptmenergy",
    "0.70", "0.23", "1.2",
)


def test_kd_presence_alone_never_forces_a_binder():
    # Measurable KD present, but expressed-and-not-bound -> honest negative.
    rec = {
        "id": "x", "sequence": "MKAALEW",
        "experimental__kd": 1e-9,          # great affinity number...
        "experimental__binding": 0.0,      # ...but the assay says it did NOT bind
        "experimental__expressed": 1.0,
    }
    assert build_label_row(rec, "pd-l1").binds is False


def test_strong_computational_metrics_never_force_a_binder():
    # Excellent in-silico metrics, NO experimental binding readout -> None.
    rec = {
        "id": "y", "sequence": "MKAALEW",
        "computational__boltz2_min_ipsae": 0.95,
        "computational__boltz2_pdockq": 0.9,
        "computational__boltz2_lis": 0.99,
        # no experimental__binding, no experimental__expressed
    }
    assert build_label_row(rec, "pd-l1").binds is None


def test_kd_present_but_unexpressed_is_undeterminable_not_binder():
    rec = {"id": "z", "sequence": "MKAALEW",
           "experimental__kd": 5e-9, "experimental__expressed": 0.0}
    assert build_label_row(rec, "pd-l1").binds is None


def test_derive_binds_source_references_no_circular_signal():
    src = inspect.getsource(derive_binds).lower()
    for token in _BANNED_TOKENS:
        assert token not in src, f"derive_binds references banned label signal: {token!r}"
```
- [ ] Run it — expect **PASS** (all dependencies exist from Task 6; this is the ban guard asserting the invariant):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_circular_label_ban.py -v
```
- [ ] Commit:
```
git add data/tests/test_circular_label_ban.py
git commit -m "data: circular-label ban test (binds never from kd.notna nor in-silico hit-rule)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 8 — `explode_proteinbase` + frozen sha256-versioned table

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/fixtures/proteinbase_sample.csv`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_etl.py`

- [ ] Create the integration fixture `data/tests/fixtures/proteinbase_sample.csv` (raw 6-column shape; CSV-escaped JSON in `evaluations`):
```
id,name,sequence,author,designMethod,evaluations
d1,Binder1,MKAALEW,alice,RFdiffusion,"[{""type"":""experimental"",""metric"":""kd"",""value"":""8.99e-09""},{""type"":""experimental"",""metric"":""binding"",""value"":""1.0""},{""type"":""experimental"",""metric"":""expressed"",""value"":""1.0""},{""type"":""computational"",""metric"":""boltz2_min_ipsae"",""value"":""0.82"",""target"":""PD-L1""}]"
d2,Binder2,GGSWLKE,bob,BindCraft,"[{""type"":""experimental"",""metric"":""expressed"",""value"":""1.0""},{""type"":""experimental"",""metric"":""binding"",""value"":""0.0""},{""type"":""computational"",""metric"":""boltz2_min_ipsae"",""value"":""0.41"",""target"":""PD-L1""}]"
d3,Binder3,AAACCC,carol,RFdiffusion,[]
```
- [ ] Add the FAILING test to `data/tests/test_etl.py`:
```python
from data.etl import explode_proteinbase
from data.tests.conftest import FIXTURES_DIR


def test_explode_proteinbase_end_to_end():
    designs, labels, sha = explode_proteinbase(
        str(FIXTURES_DIR / "proteinbase_sample.csv")
    )
    assert len(designs) == 3
    assert len(labels) == 3
    by_id = {d.design_id: d for d in designs}
    assert by_id["d1"].target_id == "pd-l1"
    assert by_id["d1"].metrics["computational__boltz2_min_ipsae"] == 0.82
    lab = {l.design_id: l for l in labels}
    assert lab["d1"].binds is True
    assert lab["d2"].binds is False
    assert lab["d3"].binds is None
    assert lab["d3"].target_id == "unknown"
    assert len(sha) == 64  # sha256 hexdigest


def test_explode_sha256_is_stable_and_reproducible():
    path = str(FIXTURES_DIR / "proteinbase_sample.csv")
    _, _, sha_a = explode_proteinbase(path)
    _, _, sha_b = explode_proteinbase(path)
    assert sha_a == sha_b  # frozen / reproducible version id
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'explode_proteinbase'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py::test_explode_proteinbase_end_to_end -v
```
- [ ] Add to `data/etl.py`:
```python
def load_proteinbase_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"id": str})


def compute_table_sha256(
    designs: List[DesignRow], labels: List[LabelRow]
) -> str:
    payload = {
        "designs": sorted((asdict(d) for d in designs),
                          key=lambda r: r["design_id"]),
        "labels": sorted((asdict(l) for l in labels),
                         key=lambda r: r["design_id"]),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def explode_proteinbase(
    csv_path: str,
) -> Tuple[List[DesignRow], List[LabelRow], str]:
    flat = flatten_proteinbase(load_proteinbase_csv(csv_path))
    designs: List[DesignRow] = []
    labels: List[LabelRow] = []
    for rec in flat.to_dict(orient="records"):
        target_id = resolve_target_id(rec.get("target_from_eval"))
        designs.append(build_design_row(rec, target_id))
        labels.append(build_label_row(rec, target_id))
    return designs, labels, compute_table_sha256(designs, labels)
```
- [ ] Run it — expect **PASS** (full file):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_etl.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_etl.py data/tests/fixtures/proteinbase_sample.csv
git commit -m "data: explode_proteinbase to DesignRow/LabelRow + frozen sha256 table version

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 9 — Leakage guard (guards the explode + the feature frame; pins known experimental columns)

The leakage guard runs **after** the JSON-explode and bans **all** `experimental__*` columns by prefix (so unknown/hyphenated variants are caught too). MUST-FIX #4: pin the label-bearing experimental column set the ETL consumes — `binding, expressed, expression_yield, kd, koff, kon` — while the prefix guard remains the hard gate.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/leakage.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_leakage.py`

- [ ] Write the FAILING test `data/tests/test_leakage.py`:
```python
from __future__ import annotations

import pandas as pd
import pytest

from pc_contracts.core import DesignRow
from data.etl import explode_proteinbase, flatten_proteinbase, load_proteinbase_csv
from data.leakage import (
    KNOWN_EXPERIMENTAL_METRICS,
    LeakageError,
    assert_designs_clean,
    assert_no_leakage,
    build_feature_frame,
)
from data.tests.conftest import FIXTURES_DIR


def test_known_experimental_metrics_pinned():
    assert KNOWN_EXPERIMENTAL_METRICS == (
        "binding", "expressed", "expression_yield", "kd", "koff", "kon",
    )


def test_each_known_experimental_column_is_guarded():
    for m in KNOWN_EXPERIMENTAL_METRICS:
        with pytest.raises(LeakageError):
            assert_no_leakage([f"experimental__{m}"])


def test_guard_catches_hyphenated_expression_yield_variant():
    # parse_evaluations preserves hyphens -> experimental__expression-yield;
    # the prefix guard still catches it.
    with pytest.raises(LeakageError):
        assert_no_leakage(["experimental__expression-yield"])


def test_build_feature_frame_excludes_experimental_columns():
    df = pd.DataFrame(
        {
            "computational__boltz2_min_ipsae": [0.82, 0.41],
            "computational__esmfold_plddt": [88.0, 70.0],
            "experimental__kd": [8.99e-09, None],
            "experimental__binding": [1.0, 0.0],
        }
    )
    x, feature_cols = build_feature_frame(df)
    assert feature_cols == [
        "computational__boltz2_min_ipsae",
        "computational__esmfold_plddt",
    ]
    assert all(not c.startswith("experimental__") for c in x.columns)


def test_assert_no_leakage_raises_on_experimental_column():
    with pytest.raises(LeakageError):
        assert_no_leakage(["computational__boltz2_min_ipsae", "experimental__kd"])


def test_assert_designs_clean_fails_if_experimental_leaks_into_metrics():
    tainted = DesignRow(
        design_id="x", target_id="pd-l1", tool="t", tool_version="v",
        config_hash="h", seed=-1, sequence="MK",
        metrics={"computational__boltz2_min_ipsae": 0.8,
                 "experimental__kd": 1e-9},  # <-- leak
        metric_blocks_present={}, cost_usd=0.0, wallclock_sec=0.0,
    )
    with pytest.raises(LeakageError):
        assert_designs_clean([tainted])


def test_explode_then_feature_frame_drops_all_experimental():
    flat = flatten_proteinbase(
        load_proteinbase_csv(str(FIXTURES_DIR / "proteinbase_sample.csv"))
    )
    x, cols = build_feature_frame(flat)
    assert all(c.startswith("computational__") for c in cols)
    assert not any(c.startswith("experimental__") for c in x.columns)


def test_real_etl_output_is_leakage_clean():
    designs, _, _ = explode_proteinbase(
        str(FIXTURES_DIR / "proteinbase_sample.csv")
    )
    assert_designs_clean(designs)  # must not raise
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.leakage'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_leakage.py -v
```
- [ ] Minimal implementation `data/leakage.py`:
```python
from __future__ import annotations

from typing import Iterable, List, Tuple

import pandas as pd

from pc_contracts.core import DesignRow

EXPERIMENTAL_PREFIX = "experimental__"
FEATURE_PREFIX = "computational__"

# The label-bearing experimental columns the ETL explicitly consumes (MUST-FIX
# #4). The original notebook flattens to 11 experimental__* columns total; these
# six carry binding/expression labels. The guard below is PREFIX-BASED, so it
# bans ALL experimental__* columns (known or not), including hyphen variants
# like experimental__expression-yield.
KNOWN_EXPERIMENTAL_METRICS = (
    "binding", "expressed", "expression_yield", "kd", "koff", "kon",
)


class LeakageError(AssertionError):
    """Raised when an experimental__* column reaches the feature space."""


def assert_no_leakage(columns: Iterable[str]) -> None:
    leaked = [c for c in columns if c.startswith(EXPERIMENTAL_PREFIX)]
    if leaked:
        raise LeakageError(f"experimental columns leaked into features: {leaked}")


def build_feature_frame(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    feature_cols = [c for c in df.columns if c.startswith(FEATURE_PREFIX)]
    assert_no_leakage(feature_cols)
    return df[feature_cols].copy(), feature_cols


def assert_designs_clean(designs: Iterable[DesignRow]) -> None:
    for d in designs:
        bad = [k for k in d.metrics if k.startswith(EXPERIMENTAL_PREFIX)]
        if bad:
            raise LeakageError(
                f"design {d.design_id} metrics contain experimental keys: {bad}"
            )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_leakage.py -v
```
- [ ] Commit:
```
git add data/leakage.py data/tests/test_leakage.py
git commit -m "data: prefix-based leakage guard after explode; pin 6 known experimental columns

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 10 — Canonical metric key enforcement (AUDIT-A, MUST-FIX)

The canonical stored key for the primary ipSAE metric is **`computational__boltz2_min_ipsae`** (the `computational__` prefix + the Proteinbase column name). Two bugs exist in the draft plan: (1) protocol modules (Tasks 29/32/33) pass the bare `boltz2_min_ipsae` as `score_metric` default, causing `.get()` on real `DesignRow.metrics` dicts to silently return `None` → scores collapse to `-inf` → metric-blind sampling and all selection-bias diagnostics silently no-op. (2) There is no test asserting the bare key is forbidden. This task adds a dedicated ban test and updates the `canonical_metric_key` constant in `pc_contracts`.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/core.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_canonical_metric_key.py`

- [ ] Write the FAILING test `data/tests/test_canonical_metric_key.py`:
```python
from __future__ import annotations

import pytest

from pc_contracts.core import CANONICAL_METRIC_KEY


def test_canonical_metric_key_is_the_full_prefixed_name():
    # The single source of truth for the primary ipSAE column name.
    assert CANONICAL_METRIC_KEY == "computational__boltz2_min_ipsae"


def test_canonical_metric_key_starts_with_computational_prefix():
    assert CANONICAL_METRIC_KEY.startswith("computational__")


def test_bare_key_is_not_canonical():
    # The bare 'boltz2_min_ipsae' (without the computational__ prefix) must
    # never appear as a stored key.  If this test fails, a protocol module is
    # using the wrong key and diagnostics will silently no-op on real DesignRows.
    bare = "boltz2_min_ipsae"
    assert bare != CANONICAL_METRIC_KEY, (
        f"Bare key {bare!r} must not be used as a metric key; "
        f"use CANONICAL_METRIC_KEY={CANONICAL_METRIC_KEY!r}"
    )


def test_design_row_metrics_use_canonical_key():
    from pc_contracts.core import DesignRow
    row = DesignRow(
        design_id="d1", target_id="t1", tool="boltz2", tool_version="1",
        config_hash="h", seed=0, sequence="MKA",
        metrics={CANONICAL_METRIC_KEY: 0.82},
        metric_blocks_present={"boltz2": True},
        cost_usd=0.0, wallclock_sec=0.0,
    )
    assert CANONICAL_METRIC_KEY in row.metrics
    assert "boltz2_min_ipsae" not in row.metrics  # bare key must NOT be present


def test_metric_blind_sample_uses_canonical_key():
    """Smoke: metric_blind_sample with canonical key does NOT silently return -inf."""
    from data.metric_blind import metric_blind_sample
    designs = [
        {"design_id": f"d{i}", "target_id": "T1", "sequence": "M" * 11,
         "metrics": {CANONICAL_METRIC_KEY: float(i)}}
        for i in range(20)
    ]
    plan = metric_blind_sample(designs, score_metric=CANONICAL_METRIC_KEY,
                               n_top=5, n_random=5, seed=0)
    # If the wrong key were used, top_ids would be arbitrary (all scores -inf)
    top_scores = [i for i in range(20) if f"d{i}" in plan.top_ids]
    assert min(top_scores) >= 15, "top_ids should be the highest-scoring designs"
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'CANONICAL_METRIC_KEY'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_canonical_metric_key.py -v
```
- [ ] Add to `pc_contracts/core.py` (after `VALID_INTERFACE_CLASSES`):
```python
# CANONICAL_METRIC_KEY: the single source of truth for the primary docking/ipSAE
# metric column name.  ALL protocol modules (metric_blind, selection_diagnostics,
# was_tested diagnostics) MUST default to this key.  The bare 'boltz2_min_ipsae'
# is FORBIDDEN as a stored metric key — it silently no-ops .get() on real DesignRows.
CANONICAL_METRIC_KEY: str = "computational__boltz2_min_ipsae"
```
- [ ] Add `CANONICAL_METRIC_KEY` to `pc_contracts/__init__.py` re-exports.
- [ ] Update `data/metric_blind.py` `metric_blind_sample` default: change `score_metric: str = "boltz2_min_ipsae"` → `score_metric: str = CANONICAL_METRIC_KEY` (import from `pc_contracts.core`).
- [ ] Update `data/selection_diagnostics.py` `was_tested_auc` and `range_restriction` defaults similarly.
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_canonical_metric_key.py -v
```
- [ ] Commit:
```
git add pc_contracts/core.py pc_contracts/__init__.py data/metric_blind.py data/selection_diagnostics.py data/tests/test_canonical_metric_key.py
git commit -m "pc_contracts: add CANONICAL_METRIC_KEY; update protocol defaults to prevent silent no-op

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 11 — Missingness / NMAR diagnostic (MUST-FIX #5)

Compare positive-rate in metric-present vs metric-absent labeled rows; flag divergence (Not-Missing-At-Random) so training can be restricted where they diverge.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/missingness.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_missingness.py`

- [ ] Write the FAILING test `data/tests/test_missingness.py`:
```python
from __future__ import annotations

import math

import pytest

from pc_contracts.core import DesignRow, LabelRow
from data.missingness import MissingnessDiagnostic, missingness_diagnostic


def _design(did: str, score) -> DesignRow:
    metrics = {} if score is None else {"computational__boltz2_min_ipsae": score}
    return DesignRow(
        design_id=did, target_id="pd-l1", tool="t", tool_version="v",
        config_hash="h", seed=-1, sequence="MK", metrics=metrics,
        metric_blocks_present={}, cost_usd=0.0, wallclock_sec=0.0,
    )


def _label(did: str, binds) -> LabelRow:
    return LabelRow(
        design_id=did, target_id="pd-l1", sequence="MK", binds=binds,
        binding_strength=None, kd_nm=None, expressed=True,
        source="proteinbase", license="x", provenance="p",
        metric_blind_sampled=False,
    )


def test_flags_nmar_when_present_rows_are_mostly_binders():
    # metric-present rows: 4/4 binders; metric-absent rows: 0/4 binders.
    designs = [_design(f"p{i}", 0.8) for i in range(4)] + [_design(f"a{i}", None) for i in range(4)]
    labels = [_label(f"p{i}", True) for i in range(4)] + [_label(f"a{i}", False) for i in range(4)]
    diag = missingness_diagnostic(designs, labels, "computational__boltz2_min_ipsae")
    assert isinstance(diag, MissingnessDiagnostic)
    assert diag.n_present == 4 and diag.n_absent == 4
    assert diag.pos_rate_present == 1.0 and diag.pos_rate_absent == 0.0
    assert math.isclose(diag.divergence, 1.0)
    assert diag.nmar_flagged is True


def test_balanced_missingness_is_not_flagged():
    designs = [_design(f"p{i}", 0.8) for i in range(4)] + [_design(f"a{i}", None) for i in range(4)]
    labels = (
        [_label("p0", True), _label("p1", True), _label("p2", False), _label("p3", False)]
        + [_label("a0", True), _label("a1", True), _label("a2", False), _label("a3", False)]
    )
    diag = missingness_diagnostic(designs, labels, "computational__boltz2_min_ipsae")
    assert diag.pos_rate_present == 0.5 and diag.pos_rate_absent == 0.5
    assert diag.nmar_flagged is False


def test_unlabeled_rows_are_ignored():
    designs = [_design("p0", 0.8), _design("a0", None)]
    labels = [_label("p0", None), _label("a0", None)]  # both unlabeled
    diag = missingness_diagnostic(designs, labels, "computational__boltz2_min_ipsae")
    assert diag.n_present == 0 and diag.n_absent == 0


def test_rejects_experimental_metric():
    with pytest.raises(ValueError):
        missingness_diagnostic([_design("p0", 0.8)], [_label("p0", True)], "experimental__kd")
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.missingness'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_missingness.py -v
```
- [ ] Minimal implementation `data/missingness.py`:
```python
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from pc_contracts.core import DesignRow, LabelRow

EXPERIMENTAL_PREFIX = "experimental__"


@dataclass(frozen=True)
class MissingnessDiagnostic:
    metric: str
    n_present: int
    n_absent: int
    pos_rate_present: float
    pos_rate_absent: float
    divergence: float
    nmar_flagged: bool


def _is_present(value) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def missingness_diagnostic(
    designs: Sequence[DesignRow],
    labels: Sequence[LabelRow],
    metric: str,
    divergence_threshold: float = 0.15,
) -> MissingnessDiagnostic:
    """Compare binder-rate among labeled rows where `metric` IS present vs ABSENT.

    A large divergence => the metric is missing-not-at-random; downstream
    training should be restricted to the metric-present stratum.
    """
    if metric.startswith(EXPERIMENTAL_PREFIX):
        raise ValueError(f"missingness must use a computational metric, got {metric!r}")
    binds_by_id = {l.design_id: l.binds for l in labels}
    present_pos = present_tot = absent_pos = absent_tot = 0
    for d in designs:
        binds = binds_by_id.get(d.design_id)
        if binds is None:
            continue  # only rows with a REAL label count
        if _is_present(d.metrics.get(metric)):
            present_tot += 1
            present_pos += 1 if binds else 0
        else:
            absent_tot += 1
            absent_pos += 1 if binds else 0
    pos_present = present_pos / present_tot if present_tot else 0.0
    pos_absent = absent_pos / absent_tot if absent_tot else 0.0
    divergence = abs(pos_present - pos_absent)
    return MissingnessDiagnostic(
        metric=metric,
        n_present=present_tot,
        n_absent=absent_tot,
        pos_rate_present=pos_present,
        pos_rate_absent=pos_absent,
        divergence=divergence,
        nmar_flagged=(present_tot > 0 and absent_tot > 0 and divergence >= divergence_threshold),
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_missingness.py -v
```
- [ ] Commit:
```
git add data/missingness.py data/tests/test_missingness.py
git commit -m "data: NMAR missingness diagnostic (present vs absent positive-rate divergence)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 12 — Assay-type field carry-through (AUDIT-B)

Labels from Overath, Proteinbase, and BindCraft come from heterogeneous assay types (SPR, ELISA, flow-cytometry, selection-based negatives). Pooling without an `assay` tag makes the "you pooled apples and oranges" challenge unanswerable. This task carries an `assay` field through ingestion into `LabelRow` and the final labeled table, enabling within-assay metrics and assay-stratified ablations downstream.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/pc_contracts/core.py` (`LabelRow` gains `assay: Optional[str]`)
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py` (`build_label_row` passes `assay`)
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest.py` (`parse_llm_label_response` reads `assay`)
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_assay_field.py`

- [ ] Write the FAILING test `data/tests/test_assay_field.py`:
```python
from __future__ import annotations

from dataclasses import fields

from pc_contracts.core import LabelRow


def test_label_row_has_assay_field():
    names = {f.name for f in fields(LabelRow)}
    assert "assay" in names, (
        "LabelRow must carry an 'assay' field so downstream eval can "
        "stratify metrics within-assay and answer the apples-vs-oranges challenge"
    )


def test_label_row_assay_defaults_to_none_when_unknown():
    row = LabelRow(
        design_id="d1", target_id="t1", sequence="MKAA",
        binds=True, binding_strength="strong", kd_nm=8.99,
        expressed=True, source="proteinbase", license="x",
        provenance="p", metric_blind_sampled=False,
        assay=None,
    )
    assert row.assay is None


def test_build_label_row_carries_assay_from_proteinbase_row():
    from data.etl import build_label_row
    rec = {
        "id": "d1", "sequence": "MKAALEW",
        "experimental__binding": 1.0,
        "experimental__expressed": 1.0,
        "experimental__assay": "SPR",
    }
    lr = build_label_row(rec, target_id="pd-l1")
    assert lr.assay == "SPR"


def test_build_label_row_assay_is_none_when_absent():
    from data.etl import build_label_row
    rec = {"id": "d2", "sequence": "GGS",
           "experimental__binding": 0.0, "experimental__expressed": 1.0}
    lr = build_label_row(rec, target_id="pd-l1")
    assert lr.assay is None


def test_label_row_to_dict_includes_assay():
    from data.labels import label_row_to_dict
    row = LabelRow(
        design_id="d1", target_id="t1", sequence="MKAA",
        binds=True, binding_strength=None, kd_nm=None,
        expressed=True, source="adaptyv", license="CC-BY-4.0",
        provenance="p", metric_blind_sampled=False,
        assay="flow_cytometry",
    )
    d = label_row_to_dict(row)
    assert d["assay"] == "flow_cytometry"


def test_harvest_parse_carries_assay_from_llm_response():
    import json
    from data.harvest import parse_llm_label_response
    payload = json.dumps({"labels": [{
        "design_id": "x", "target_id": "6M0J",
        "sequence": "MKTAYIAKQRQI", "binds": True,
        "binding_strength": "strong", "kd_nm": 9.0,
        "expressed": True, "provenance": "cao-2022:x",
        "assay": "SPR",
    }]})
    rows = parse_llm_label_response(payload, source="cao-2022")
    assert rows[0].assay == "SPR"
```
- [ ] Run it — expect **FAIL** (`LabelRow has no field 'assay'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_assay_field.py -v
```
- [ ] Add `assay: Optional[str] = None` field to `LabelRow` in `pc_contracts/core.py` (after `metric_blind_sampled`).
- [ ] Update `data/etl.py` `build_label_row` to read `rec.get("experimental__assay")` and pass it as `assay=...`.
- [ ] Update `data/harvest.py` `parse_llm_label_response` to read `entry.get("assay")` and pass it to `LabelRow`.
- [ ] Update `data/labels.py` `label_row_from_dict` to read `d.get("assay")`.
- [ ] Update `pc_contracts/tests/test_contracts.py` `test_labelrow_has_exact_contract_fields` to include `"assay"` in the expected field set.
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_assay_field.py pc_contracts/tests/test_contracts.py -v
```
- [ ] Commit:
```
git add pc_contracts/core.py data/etl.py data/harvest.py data/labels.py pc_contracts/tests/test_contracts.py data/tests/test_assay_field.py
git commit -m "data: carry assay-type field through LabelRow ingestion for within-assay stratification

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 13 — Postgres schema (offline ground-truth label/flywheel store)

Research/offline store (raw idempotent DDL, mirroring `papercrane/benchmark/migrate/src/loaders/ddl.sql` — NOT the tenant-scoped Prisma app DB). Real wet-lab outcomes land in `experimental_outcomes`; `designs`/`predictions` carry computational data only (structural leakage guard).

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/db/schema.sql`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_schema.py`

- [ ] Write the FAILING test `data/tests/test_schema.py`:
```python
from __future__ import annotations

import re

from data.tests.conftest import REPO_ROOT

SCHEMA = REPO_ROOT / "data" / "db" / "schema.sql"

REQUIRED_TABLES = {
    "targets", "designs", "labels", "predictions",
    "experimental_outcomes", "allocation_events",
}


def _parse_tables(sql: str) -> dict:
    tables = {}
    for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", sql, re.S
    ):
        name, body = m.group(1), m.group(2)
        cols = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(
                ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CONSTRAINT", "CHECK")
            ):
                continue
            cols.append(line.split()[0])
        tables[name] = cols
    return tables


def test_all_required_tables_present():
    tables = _parse_tables(SCHEMA.read_text())
    assert REQUIRED_TABLES.issubset(set(tables))


def test_schema_is_idempotent():
    sql = SCHEMA.read_text()
    assert sql.count("CREATE TABLE ") == sql.count("CREATE TABLE IF NOT EXISTS ")


def test_designs_and_predictions_carry_no_experimental_columns():
    tables = _parse_tables(SCHEMA.read_text())
    for table in ("designs", "predictions"):
        assert all(
            not c.startswith("experimental") for c in tables[table]
        ), f"{table} must not contain experimental columns"


def test_experimental_outcomes_holds_real_label_provenance():
    cols = _parse_tables(SCHEMA.read_text())["experimental_outcomes"]
    for required in ("binds", "kd_nm", "source", "license",
                     "provenance", "metric_blind_sampled"):
        assert required in cols
```
- [ ] Run it — expect **FAIL** (`FileNotFoundError: .../data/db/schema.sql`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_schema.py -v
```
- [ ] Minimal implementation `data/db/schema.sql`:
```sql
-- Paper Crane data pipeline: master label / flywheel store (research/offline).
-- Idempotent raw DDL, mirrors papercrane/benchmark/migrate/src/loaders/ddl.sql
-- style. LEAKAGE RULE: designs.metrics holds COMPUTATIONAL metrics only; every
-- experimental readout lives in labels / experimental_outcomes.

CREATE TABLE IF NOT EXISTS targets (
    target_id        TEXT PRIMARY KEY,
    pdb_id           TEXT NOT NULL,
    chain            TEXT NOT NULL,
    uniprot          TEXT,
    interface_class  TEXT NOT NULL CHECK (interface_class IN
                       ('helical','sheet_flat','mixed','ligand_present')),
    source           TEXT NOT NULL,
    license          TEXT NOT NULL,
    provenance       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS designs (
    design_id              TEXT PRIMARY KEY,
    target_id              TEXT NOT NULL REFERENCES targets(target_id),
    tool                   TEXT NOT NULL,
    tool_version           TEXT NOT NULL,
    config_hash            TEXT NOT NULL,
    seed                   INTEGER NOT NULL,
    sequence               TEXT NOT NULL,
    metrics                JSONB NOT NULL DEFAULT '{}',
    metric_blocks_present  JSONB NOT NULL DEFAULT '{}',
    cost_usd               DOUBLE PRECISION NOT NULL DEFAULT 0,
    wallclock_sec          DOUBLE PRECISION NOT NULL DEFAULT 0,
    table_sha256           TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS designs_metrics_gin_idx ON designs USING GIN (metrics);
CREATE INDEX IF NOT EXISTS designs_target_idx ON designs (target_id);

CREATE TABLE IF NOT EXISTS labels (
    design_id            TEXT PRIMARY KEY REFERENCES designs(design_id) ON DELETE CASCADE,
    target_id            TEXT NOT NULL REFERENCES targets(target_id),
    sequence             TEXT NOT NULL,
    binds                BOOLEAN,
    binding_strength     TEXT,
    kd_nm                DOUBLE PRECISION,
    expressed            BOOLEAN,
    source               TEXT NOT NULL,
    license              TEXT NOT NULL,
    provenance           TEXT NOT NULL,
    metric_blind_sampled BOOLEAN NOT NULL DEFAULT FALSE,
    table_sha256         TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS labels_target_idx ON labels (target_id);

CREATE TABLE IF NOT EXISTS predictions (
    id            BIGSERIAL PRIMARY KEY,
    design_id     TEXT NOT NULL REFERENCES designs(design_id) ON DELETE CASCADE,
    target_id     TEXT NOT NULL REFERENCES targets(target_id),
    scorer_version TEXT NOT NULL,
    prior_source  TEXT NOT NULL CHECK (prior_source IN
                    ('llm','corrector','global_default')),
    score         DOUBLE PRECISION NOT NULL,
    rank          INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (design_id, scorer_version)
);
CREATE INDEX IF NOT EXISTS predictions_target_idx ON predictions (target_id);

CREATE TABLE IF NOT EXISTS experimental_outcomes (
    id                   BIGSERIAL PRIMARY KEY,
    design_id            TEXT NOT NULL REFERENCES designs(design_id) ON DELETE CASCADE,
    target_id            TEXT NOT NULL REFERENCES targets(target_id),
    assay                TEXT NOT NULL,
    binds                BOOLEAN,
    kd_nm                DOUBLE PRECISION,
    readout              JSONB NOT NULL DEFAULT '{}',
    source               TEXT NOT NULL,
    license              TEXT NOT NULL,
    provenance           TEXT NOT NULL,
    metric_blind_sampled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS experimental_outcomes_target_idx ON experimental_outcomes (target_id);

CREATE TABLE IF NOT EXISTS allocation_events (
    id                  BIGSERIAL PRIMARY KEY,
    target_id           TEXT NOT NULL REFERENCES targets(target_id),
    budget              INTEGER NOT NULL,
    selected_design_ids JSONB NOT NULL DEFAULT '[]',
    policy              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS allocation_events_target_idx ON allocation_events (target_id);
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_schema.py -v
```
- [ ] Commit:
```
git add data/db/schema.sql data/tests/test_schema.py
git commit -m "data: offline Postgres schema (targets/designs/labels/predictions/outcomes/allocations)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 14 — Harvest: `LabelRow` constants + dict round-trip

`LabelRow` itself lives in `pc_contracts`. `data/labels.py` adds the harvest-side constants and the JSONL dict round-trip helpers.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/labels.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_labels.py`

- [ ] Write the FAILING test `data/tests/test_labels.py`:
```python
from __future__ import annotations

from pc_contracts.core import LabelRow
from data.labels import (
    ALLOWED_BINDING_STRENGTHS,
    VALID_AMINO_ACIDS,
    label_row_from_dict,
    label_row_to_dict,
)


def test_valid_amino_acids_is_the_20_canonical():
    assert VALID_AMINO_ACIDS == set("ACDEFGHIKLMNPQRSTVWY")
    assert len(VALID_AMINO_ACIDS) == 20


def test_allowed_binding_strengths_are_lowercased_canonical():
    assert ALLOWED_BINDING_STRENGTHS == {"strong", "medium", "weak", "none"}


def test_label_row_to_dict_emits_all_contract_keys():
    row = LabelRow(
        design_id="d1", target_id="6M0J", sequence="MKTAYIAKQR",
        binds=True, binding_strength="strong", kd_nm=8.99, expressed=True,
        source="cao-2022", license="CC-BY-4.0", provenance="cao-2022:row_1",
        metric_blind_sampled=False,
    )
    d = label_row_to_dict(row)
    assert set(d.keys()) == {
        "design_id", "target_id", "sequence", "binds", "binding_strength",
        "kd_nm", "expressed", "source", "license", "provenance",
        "metric_blind_sampled",
    }
    assert d["binds"] is True


def test_label_row_round_trips_through_dict():
    row = LabelRow(
        design_id="d1", target_id="P12345", sequence="ACDEFGHIKL",
        binds=None, binding_strength=None, kd_nm=None, expressed=None,
        source="sabdab", license="CC-BY-4.0", provenance="sabdab:7xyz",
        metric_blind_sampled=True,
    )
    assert label_row_from_dict(label_row_to_dict(row)) == row


def test_label_row_from_dict_defaults_metric_blind_sampled_false():
    d = {
        "design_id": "d1", "target_id": "6M0J", "sequence": "MKTAYIAKQR",
        "binds": True, "binding_strength": "strong", "kd_nm": 8.99,
        "expressed": True, "source": "cao-2022", "license": "CC-BY-4.0",
        "provenance": "cao-2022:row_1",
    }
    assert label_row_from_dict(d).metric_blind_sampled is False
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.labels'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_labels.py -v
```
- [ ] Minimal implementation `data/labels.py`:
```python
from __future__ import annotations

from dataclasses import asdict

from pc_contracts.core import LabelRow

VALID_AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")
ALLOWED_BINDING_STRENGTHS = {"strong", "medium", "weak", "none"}


def label_row_to_dict(row: LabelRow) -> dict:
    return asdict(row)


def label_row_from_dict(d: dict) -> LabelRow:
    return LabelRow(
        design_id=d["design_id"],
        target_id=d["target_id"],
        sequence=d["sequence"],
        binds=d.get("binds"),
        binding_strength=d.get("binding_strength"),
        kd_nm=d.get("kd_nm"),
        expressed=d.get("expressed"),
        source=d["source"],
        license=d["license"],
        provenance=d["provenance"],
        metric_blind_sampled=bool(d.get("metric_blind_sampled", False)),
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_labels.py -v
```
- [ ] Commit:
```
git add data/labels.py data/tests/test_labels.py
git commit -m "data: harvest constants + LabelRow dict round-trip for JSONL persistence

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 15 — `is_real_label` hardening + ingest source ALLOWLIST (AUDIT-D)

Two hardening steps: (a) extend `SILICO_LABEL_MARKERS` with additional in-silico provenance tokens that may appear in future datasets; (b) add a fail-CLOSED source `ALLOWLIST` at the ingest boundary so any new source string forces a deliberate human decision rather than silently passing through.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py` (add `SILICO_LABEL_MARKERS`, `is_real_label`, `INGEST_SOURCE_ALLOWLIST`, `assert_source_allowed`)
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_is_real_label.py`

- [ ] Write the FAILING test `data/tests/test_is_real_label.py`:
```python
from __future__ import annotations

import pytest

from data.etl import (
    INGEST_SOURCE_ALLOWLIST,
    SILICO_LABEL_MARKERS,
    assert_source_allowed,
    is_real_label,
)


def test_silico_markers_include_original_and_extended_tokens():
    required = {
        # original markers
        "in_silico", "computational", "predicted",
        # AUDIT-D extensions
        "af3", "alphafold", "chai", "esmfold", "esm",
        "rosetta", "rfdiffusion", "bindcraft_metric",
    }
    for token in required:
        assert token in SILICO_LABEL_MARKERS, (
            f"SILICO_LABEL_MARKERS missing token {token!r} — "
            "in-silico labels from this provenance will silently pass as real"
        )


def test_is_real_label_accepts_explicit_binding_boolean():
    rec = {"experimental__binding": 1.0, "experimental__expressed": 1.0,
           "provenance": "proteinbase_all_data_28_01_2026.csv:row_id=d1"}
    assert is_real_label(rec) is True


def test_is_real_label_rejects_in_silico_provenance_tokens():
    for token in ("alphafold", "esmfold", "chai", "rfdiffusion", "bindcraft_metric"):
        rec = {"experimental__binding": 1.0, "experimental__expressed": 1.0,
               "provenance": f"predicted_by_{token}:row_id=x"}
        assert is_real_label(rec) is False, (
            f"is_real_label should reject provenance containing {token!r}"
        )


def test_is_real_label_rejects_missing_binding_field():
    rec = {"experimental__expressed": 1.0,
           "provenance": "proteinbase:row_id=d1"}
    assert is_real_label(rec) is False


def test_ingest_source_allowlist_contains_exactly_known_sources():
    assert INGEST_SOURCE_ALLOWLIST == {"overath", "bindcraft", "proteinbase"}


def test_assert_source_allowed_passes_for_known_sources():
    for src in ("overath", "bindcraft", "proteinbase"):
        assert_source_allowed(src)  # must not raise


def test_assert_source_allowed_raises_for_unknown_source():
    with pytest.raises(ValueError, match="not in INGEST_SOURCE_ALLOWLIST"):
        assert_source_allowed("new_mystery_source")


def test_assert_source_allowed_is_outside_is_real_label():
    # The allowlist check is at the INGEST BOUNDARY only, not inside is_real_label.
    # New assay names should not be auto-dropped by is_real_label — they need a
    # deliberate human decision at the boundary.
    rec = {"experimental__binding": 1.0, "experimental__expressed": 1.0,
           "provenance": "new_assay_type:row_id=x"}
    # is_real_label doesn't check source allowlist — it checks provenance markers
    result = is_real_label(rec)
    assert isinstance(result, bool)  # returns a bool, doesn't raise
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'SILICO_LABEL_MARKERS'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_is_real_label.py -v
```
- [ ] Add to `data/etl.py`:
```python
# In-silico provenance tokens (AUDIT-D: extended set). A LabelRow whose provenance
# string contains any of these tokens is NOT a real wet-lab label and must be
# rejected at ingestion. Keep fail-CLOSED: add tokens freely; never remove them.
SILICO_LABEL_MARKERS: frozenset[str] = frozenset({
    # original
    "in_silico", "computational", "predicted",
    # AUDIT-D extensions: additional in-silico provenance tokens
    "af3", "alphafold", "chai", "esmfold", "esm",
    "rosetta", "rfdiffusion", "bindcraft_metric",
})

# Fail-CLOSED source allowlist at the ingest boundary.
# Any source string not in this set must HARD-RAISE to force a deliberate
# human decision.  Do NOT put this check inside is_real_label — new assay
# names should not be auto-dropped; they need explicit registration here.
INGEST_SOURCE_ALLOWLIST: frozenset[str] = frozenset({
    "overath", "bindcraft", "proteinbase",
})


def is_real_label(rec: Dict[str, Any]) -> bool:
    """Return True iff this record carries a real wet-lab binding readout.

    Checks: (1) explicit experimental__binding field present; (2) provenance
    string does not contain any known in-silico marker token.
    """
    binding = rec.get("experimental__binding")
    if binding is None:
        return False
    provenance = str(rec.get("provenance", "")).lower()
    if any(token in provenance for token in SILICO_LABEL_MARKERS):
        return False
    return True


def assert_source_allowed(source: str) -> None:
    """Fail-CLOSED ingest-boundary guard.

    Raises ValueError if source is not in INGEST_SOURCE_ALLOWLIST, forcing a
    deliberate human decision before a new source can enter the labeled table.
    This is NOT called inside is_real_label so legitimate new assay names are
    not auto-dropped — they are instead escalated here.
    """
    if source.strip().lower() not in INGEST_SOURCE_ALLOWLIST:
        raise ValueError(
            f"source {source!r} is not in INGEST_SOURCE_ALLOWLIST "
            f"({sorted(INGEST_SOURCE_ALLOWLIST)}). "
            "Add it explicitly after verifying provenance and license."
        )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_is_real_label.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_is_real_label.py
git commit -m "data: harden is_real_label SILICO_LABEL_MARKERS + fail-CLOSED INGEST_SOURCE_ALLOWLIST

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 16 — Harvest: sequence-sanity validator

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest_validators.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_harvest_validators.py`

- [ ] Write the FAILING test `data/tests/test_harvest_validators.py`:
```python
from __future__ import annotations

from data.harvest_validators import (
    MAX_SEQ_LEN,
    MIN_SEQ_LEN,
    is_valid_sequence,
)


def test_accepts_clean_uppercase_sequence():
    assert is_valid_sequence("MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ") is True


def test_rejects_non_amino_acid_characters():
    assert is_valid_sequence("MKTAYIAKQX1Z") is False  # X, 1, Z not canonical


def test_rejects_empty_and_whitespace():
    assert is_valid_sequence("") is False
    assert is_valid_sequence("   ") is False


def test_rejects_too_short_and_too_long():
    assert is_valid_sequence("A" * (MIN_SEQ_LEN - 1)) is False
    assert is_valid_sequence("A" * (MAX_SEQ_LEN + 1)) is False


def test_accepts_lowercase_by_uppercasing():
    assert is_valid_sequence("mktayiakqr") is True


def test_rejects_non_string():
    assert is_valid_sequence(None) is False
    assert is_valid_sequence(123) is False
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.harvest_validators'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Minimal implementation `data/harvest_validators.py`:
```python
from __future__ import annotations

from data.labels import VALID_AMINO_ACIDS

MIN_SEQ_LEN = 10
MAX_SEQ_LEN = 1000


def is_valid_sequence(seq: object) -> bool:
    if not isinstance(seq, str):
        return False
    cleaned = seq.strip().upper()
    if not (MIN_SEQ_LEN <= len(cleaned) <= MAX_SEQ_LEN):
        return False
    return all(ch in VALID_AMINO_ACIDS for ch in cleaned)
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Commit:
```
git add data/harvest_validators.py data/tests/test_harvest_validators.py
git commit -m "data: sequence-sanity validator for harvested labels

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 17 — Harvest: target-id resolves to a real PDB / UniProt id

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest_validators.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_harvest_validators.py`

- [ ] Append the FAILING test to `data/tests/test_harvest_validators.py`:
```python
from data.harvest_validators import resolves_to_pdb_or_uniprot, target_id_resolves


def test_accepts_valid_pdb_id():
    assert resolves_to_pdb_or_uniprot("6M0J") is True   # SARS-CoV-2 RBD/ACE2
    assert resolves_to_pdb_or_uniprot("5O45") is True   # PD-L1
    assert resolves_to_pdb_or_uniprot("3up1") is True   # lowercase tolerated


def test_accepts_valid_uniprot_accession():
    assert resolves_to_pdb_or_uniprot("P12345") is True
    assert resolves_to_pdb_or_uniprot("Q9BYF1") is True  # ACE2
    assert resolves_to_pdb_or_uniprot("A0A0B4J2D5") is True


def test_rejects_free_text_and_malformed_ids():
    assert resolves_to_pdb_or_uniprot("Nipah virus G") is False
    assert resolves_to_pdb_or_uniprot("PD-L1") is False
    assert resolves_to_pdb_or_uniprot("0XYZ") is False  # PDB first char must be 1-9
    assert resolves_to_pdb_or_uniprot("") is False


def test_target_id_resolves_uses_injected_resolver_when_given():
    seen = {}

    def fake_resolver(tid: str) -> bool:
        seen["called_with"] = tid
        return True

    assert target_id_resolves("Nipah virus G", resolver=fake_resolver) is True
    assert seen["called_with"] == "Nipah virus G"


def test_target_id_resolves_falls_back_to_offline_regex():
    assert target_id_resolves("6M0J") is True
    assert target_id_resolves("not-an-id") is False
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'resolves_to_pdb_or_uniprot'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Add to `data/harvest_validators.py`:
```python
import re
from typing import Callable, Optional

_PDB_RE = re.compile(r"^[1-9][A-Za-z0-9]{3}$")
_UNIPROT_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)


def resolves_to_pdb_or_uniprot(target_id: object) -> bool:
    if not isinstance(target_id, str):
        return False
    tid = target_id.strip()
    if _PDB_RE.match(tid):
        return True
    return bool(_UNIPROT_RE.match(tid.upper())) and tid == tid.upper()


def target_id_resolves(
    target_id: str,
    resolver: Optional[Callable[[str], bool]] = None,
) -> bool:
    if resolver is not None:
        return bool(resolver(target_id))
    return resolves_to_pdb_or_uniprot(target_id)
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Commit:
```
git add data/harvest_validators.py data/tests/test_harvest_validators.py
git commit -m "data: target-id PDB/UniProt resolution gate (injectable resolver)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 18 — Harvest: allowed-label-set validator + full-row aggregator

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest_validators.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_harvest_validators.py`

- [ ] Append the FAILING test to `data/tests/test_harvest_validators.py`:
```python
from data.harvest_validators import is_allowed_label, validate_label_row
from pc_contracts.core import LabelRow


def _row(**kw) -> LabelRow:
    base = dict(
        design_id="d1", target_id="6M0J", sequence="MKTAYIAKQRQI",
        binds=True, binding_strength="strong", kd_nm=8.99, expressed=True,
        source="cao-2022", license="CC-BY-4.0", provenance="cao-2022:row_1",
        metric_blind_sampled=False,
    )
    base.update(kw)
    return LabelRow(**base)


def test_allows_canonical_labels():
    assert is_allowed_label(_row()) is True
    assert is_allowed_label(_row(binds=None, binding_strength=None, kd_nm=None)) is True


def test_rejects_unknown_binding_strength():
    assert is_allowed_label(_row(binding_strength="super-tight")) is False


def test_rejects_non_positive_kd():
    assert is_allowed_label(_row(kd_nm=0.0)) is False
    assert is_allowed_label(_row(kd_nm=-3.0)) is False


def test_rejects_contradictory_nonbinder_with_strength():
    assert is_allowed_label(_row(binds=False, binding_strength="strong")) is False


def test_validate_label_row_collects_all_errors():
    bad = _row(sequence="XX1", target_id="not-an-id", binding_strength="super")
    errors = validate_label_row(bad)
    assert any("sequence" in e for e in errors)
    assert any("target_id" in e for e in errors)
    assert any("label" in e for e in errors)


def test_validate_label_row_clean_returns_empty():
    assert validate_label_row(_row()) == []
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'is_allowed_label'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Add to `data/harvest_validators.py`:
```python
from typing import List

from data.labels import ALLOWED_BINDING_STRENGTHS
from pc_contracts.core import LabelRow

_POSITIVE_STRENGTHS = {"strong", "medium", "weak"}


def is_allowed_label(row: LabelRow) -> bool:
    if row.binds not in (True, False, None):
        return False
    if row.expressed not in (True, False, None):
        return False
    if row.binding_strength is not None:
        if str(row.binding_strength).lower() not in ALLOWED_BINDING_STRENGTHS:
            return False
    if row.kd_nm is not None:
        if not isinstance(row.kd_nm, (int, float)) or float(row.kd_nm) <= 0:
            return False
    if row.binds is False and str(row.binding_strength).lower() in _POSITIVE_STRENGTHS:
        return False
    return True


def validate_label_row(
    row: LabelRow,
    resolver=None,
) -> List[str]:
    errors: List[str] = []
    if not is_valid_sequence(row.sequence):
        errors.append(f"sequence failed sanity check: {row.sequence!r}")
    if not target_id_resolves(row.target_id, resolver=resolver):
        errors.append(f"target_id does not resolve to PDB/UniProt: {row.target_id!r}")
    if not is_allowed_label(row):
        errors.append("label values outside allowed set")
    return errors
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest_validators.py -v
```
- [ ] Commit:
```
git add data/harvest_validators.py data/tests/test_harvest_validators.py
git commit -m "data: allowed-label gate + validate_label_row aggregator

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 19 — Harvest: dedup against existing rows

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/dedup.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_dedup.py`

- [ ] Write the FAILING test `data/tests/test_dedup.py`:
```python
from __future__ import annotations

from data.dedup import dedup_label_rows, label_row_key
from pc_contracts.core import LabelRow


def _row(target_id: str, sequence: str, design_id: str = "d") -> LabelRow:
    return LabelRow(
        design_id=design_id, target_id=target_id, sequence=sequence,
        binds=True, binding_strength="strong", kd_nm=1.0, expressed=True,
        source="cao-2022", license="CC-BY-4.0", provenance="cao-2022:x",
        metric_blind_sampled=False,
    )


def test_key_is_target_plus_normalized_sequence():
    assert label_row_key(_row("6M0J", " mktayiakqr ")) == ("6M0J", "MKTAYIAKQR")


def test_key_collides_for_same_target_and_sequence_case_insensitive():
    assert label_row_key(_row("6M0J", "MKTAYIAKQR")) == label_row_key(
        _row("6M0J", "mktayiakqr", design_id="other")
    )


def test_dedup_drops_rows_already_in_existing():
    existing = [_row("6M0J", "MKTAYIAKQR")]
    new = [
        _row("6M0J", "MKTAYIAKQR", design_id="dup"),      # dropped
        _row("5O45", "ACDEFGHIKL", design_id="keep"),     # kept
    ]
    out = dedup_label_rows(new, existing)
    assert [r.design_id for r in out] == ["keep"]


def test_dedup_drops_intra_batch_duplicates_keeping_first():
    new = [
        _row("6M0J", "MKTAYIAKQR", design_id="first"),
        _row("6M0J", "mktayiakqr", design_id="second"),  # same key -> dropped
    ]
    out = dedup_label_rows(new, [])
    assert [r.design_id for r in out] == ["first"]


def test_dedup_handles_empty_existing():
    new = [_row("6M0J", "MKTAYIAKQR")]
    assert len(dedup_label_rows(new, [])) == 1
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.dedup'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_dedup.py -v
```
- [ ] Minimal implementation `data/dedup.py`:
```python
from __future__ import annotations

from typing import List, Sequence, Tuple

from pc_contracts.core import LabelRow


def label_row_key(row: LabelRow) -> Tuple[str, str]:
    return (row.target_id, row.sequence.strip().upper())


def dedup_label_rows(
    new_rows: Sequence[LabelRow],
    existing_rows: Sequence[LabelRow],
) -> List[LabelRow]:
    seen = {label_row_key(r) for r in existing_rows}
    out: List[LabelRow] = []
    for row in new_rows:
        key = label_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_dedup.py -v
```
- [ ] Commit:
```
git add data/dedup.py data/tests/test_dedup.py
git commit -m "data: dedup harvested labels by (target_id, sequence)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 20 — Dedup canonical-source assertion (AUDIT-E)

After deduplication to 5,721 sequences, assert that each target is served by a single canonical source. Double-counting a target's designs across Overath + Proteinbase + BindCraft inflates the per-target N and can produce conflicting labels for the same sequence. Cross-source label conflicts are logged before dropping (rather than silently overwriting).

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/dedup.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_dedup_source_assert.py`

- [ ] Write the FAILING test `data/tests/test_dedup_source_assert.py`:
```python
from __future__ import annotations

import logging

import pytest

from data.dedup import (
    assert_single_source_per_target,
    drop_cross_source_conflicts,
)
from pc_contracts.core import LabelRow


def _row(target_id: str, sequence: str, source: str, binds: bool) -> LabelRow:
    return LabelRow(
        design_id=f"{target_id}-{sequence}-{source}", target_id=target_id,
        sequence=sequence, binds=binds, binding_strength=None, kd_nm=None,
        expressed=True, source=source, license="CC-BY-4.0",
        provenance=f"{source}:x", metric_blind_sampled=False,
    )


def test_single_source_per_target_passes_when_clean():
    rows = [
        _row("nipah", "MKTAYIAKQR", "proteinbase", True),
        _row("nipah", "ACDEFGHIKL", "proteinbase", False),
        _row("pd-l1", "GGSWLKEFMN", "overath", True),
    ]
    assert_single_source_per_target(rows)  # must not raise


def test_single_source_per_target_raises_on_cross_source():
    rows = [
        _row("nipah", "MKTAYIAKQR", "proteinbase", True),
        _row("nipah", "ACDEFGHIKL", "bindcraft", False),
    ]
    with pytest.raises(AssertionError, match="nipah"):
        assert_single_source_per_target(rows)


def test_drop_cross_source_conflicts_logs_and_drops(caplog):
    rows = [
        _row("nipah", "MKTAYIAKQR", "proteinbase", True),
        _row("nipah", "MKTAYIAKQR", "bindcraft", False),  # same seq, different source+label
        _row("nipah", "ACDEFGHIKL", "proteinbase", False),  # no conflict
    ]
    with caplog.at_level(logging.WARNING):
        kept = drop_cross_source_conflicts(rows)
    # The conflicting sequence should be logged and dropped
    assert any("cross-source conflict" in msg.lower() or "conflict" in msg.lower()
               for msg in caplog.messages)
    # Only the non-conflicting row survives
    assert len(kept) == 1
    assert kept[0].sequence == "ACDEFGHIKL"


def test_drop_cross_source_conflicts_keeps_all_when_no_conflicts():
    rows = [
        _row("nipah", "MKTAYIAKQR", "proteinbase", True),
        _row("nipah", "ACDEFGHIKL", "proteinbase", False),
    ]
    kept = drop_cross_source_conflicts(rows)
    assert len(kept) == 2
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'assert_single_source_per_target'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_dedup_source_assert.py -v
```
- [ ] Add to `data/dedup.py`:
```python
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def assert_single_source_per_target(rows: Sequence[LabelRow]) -> None:
    """Assert each target is served by at most one canonical source.

    Raises AssertionError naming the offending target(s) if any target has
    designs from multiple sources.  Call this after the main dedup step.
    """
    target_sources: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        target_sources[row.target_id].add(row.source)
    multi = {t: srcs for t, srcs in target_sources.items() if len(srcs) > 1}
    if multi:
        lines = [f"  {t}: {sorted(srcs)}" for t, srcs in sorted(multi.items())]
        raise AssertionError(
            "Cross-source target contamination detected (AUDIT-E). "
            "Each target must have a single canonical source. Offenders:\n"
            + "\n".join(lines)
        )


def drop_cross_source_conflicts(rows: Sequence[LabelRow]) -> List[LabelRow]:
    """Drop sequences that appear in more than one source for the same target.

    Logs a WARNING for every dropped conflict (for audit trail).  Use this
    before assert_single_source_per_target when merging multi-source tables.
    """
    # key = (target_id, normalized_sequence)
    sources_by_key: dict[Tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        key = label_row_key(row)
        sources_by_key[key].add(row.source)

    conflict_keys = {k for k, srcs in sources_by_key.items() if len(srcs) > 1}
    kept: List[LabelRow] = []
    for row in rows:
        key = label_row_key(row)
        if key in conflict_keys:
            logger.warning(
                "Cross-source conflict: dropping target=%s seq=%s sources=%s",
                key[0], key[1], sorted(sources_by_key[key]),
            )
        else:
            kept.append(row)
    return kept
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_dedup_source_assert.py -v
```
- [ ] Commit:
```
git add data/dedup.py data/tests/test_dedup_source_assert.py
git commit -m "data: assert single canonical source per target + log+drop cross-source conflicts

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 21 — Nipah license + dual panel (AUDIT-C)

Nipah is ~two-thirds of the public labeled data and its license is unclear (possible copyleft/commercial-use risk). This task: (a) tags each training row with a `license` field (already in `LabelRow` from Task 1; this task wires the Nipah-specific value); (b) produces TWO downstream evaluation panels so results can be validated in both; (c) adds a `nipah_excluded` flag to the labeled-table builder so the `commercial-clean-10` panel is reproducible.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py` (add `NIPAH_TARGET_IDS` constant + `is_nipah_target`)
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_nipah_license.py`

- [ ] Write the FAILING test `data/tests/test_nipah_license.py`:
```python
from __future__ import annotations

import pytest

from data.etl import (
    NIPAH_TARGET_IDS,
    build_dual_eval_panels,
    is_nipah_target,
)
from pc_contracts.core import LabelRow


def _row(target_id: str, binds: bool = True) -> LabelRow:
    return LabelRow(
        design_id=f"{target_id}-x", target_id=target_id, sequence="MKTAYIAKQR",
        binds=binds, binding_strength=None, kd_nm=None, expressed=True,
        source="proteinbase", license="proteinbase-public-download:LICENSE-GATE-PENDING",
        provenance="p", metric_blind_sampled=False,
    )


def test_nipah_target_ids_are_defined():
    assert isinstance(NIPAH_TARGET_IDS, frozenset)
    assert len(NIPAH_TARGET_IDS) >= 1
    # The Adaptyv/Proteinbase Nipah entry is keyed by a specific target id;
    # update this set if the curated mapping changes.
    assert any("nipah" in tid.lower() for tid in NIPAH_TARGET_IDS)


def test_is_nipah_target_returns_true_for_nipah_rows():
    for tid in NIPAH_TARGET_IDS:
        assert is_nipah_target(tid) is True


def test_is_nipah_target_returns_false_for_non_nipah():
    assert is_nipah_target("pd-l1") is False
    assert is_nipah_target("sars-cov2-rbd") is False


def test_build_dual_eval_panels_produces_full_and_commercial_clean():
    rows = [_row("nipah"), _row("pd-l1"), _row("il-7ra"), _row("sars-cov2-rbd")]
    panels = build_dual_eval_panels(rows)
    assert "full" in panels and "commercial_clean" in panels
    full_targets = {r.target_id for r in panels["full"]}
    clean_targets = {r.target_id for r in panels["commercial_clean"]}
    # full panel includes Nipah
    assert any("nipah" in t.lower() for t in full_targets)
    # commercial-clean panel excludes Nipah
    assert not any("nipah" in t.lower() for t in clean_targets)
    # non-Nipah targets are in both
    assert "pd-l1" in full_targets and "pd-l1" in clean_targets


def test_dual_panels_log_nipah_exclusion_reason(caplog):
    import logging
    rows = [_row("nipah"), _row("pd-l1")]
    with caplog.at_level(logging.INFO):
        build_dual_eval_panels(rows)
    assert any("nipah" in msg.lower() or "commercial_clean" in msg.lower()
               for msg in caplog.messages)
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'NIPAH_TARGET_IDS'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_nipah_license.py -v
```
- [ ] Add to `data/etl.py`:
```python
import logging as _logging

_nipah_log = _logging.getLogger(__name__)

# Nipah virus G-protein target ids as they appear in the curated target mapping.
# Update if the curated target id changes.  These rows are excluded from the
# 'commercial_clean' eval panel pending license confirmation (AUDIT-C).
NIPAH_TARGET_IDS: frozenset[str] = frozenset({"nipah", "nipah-g", "nipah_g"})


def is_nipah_target(target_id: str) -> bool:
    return target_id.strip().lower() in NIPAH_TARGET_IDS


def build_dual_eval_panels(
    rows: List[LabelRow],
) -> Dict[str, List[LabelRow]]:
    """Return full-11 and commercial-clean-10 eval panels.

    full: all labeled rows (includes Nipah; valid for internal validation).
    commercial_clean: excludes Nipah rows (safe for commercial claims until
        license is confirmed — see Phase 0 Nipah diligence task and AUDIT-C).
    """
    full = list(rows)
    clean = [r for r in rows if not is_nipah_target(r.target_id)]
    nipah_count = len(full) - len(clean)
    _nipah_log.info(
        "build_dual_eval_panels: full=%d rows, commercial_clean=%d rows "
        "(%d Nipah rows excluded from commercial_clean panel pending license confirmation)",
        len(full), len(clean), nipah_count,
    )
    return {"full": full, "commercial_clean": clean}
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_nipah_license.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_nipah_license.py
git commit -m "data: NIPAH_TARGET_IDS + dual eval panels (full-11 vs commercial-clean-10)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 22 — Harvest: master label table JSONL load / append

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/label_store.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_label_store.py`

- [ ] Write the FAILING test `data/tests/test_label_store.py`:
```python
from __future__ import annotations

from data.label_store import append_label_rows, load_label_table
from pc_contracts.core import LabelRow


def _row(design_id: str) -> LabelRow:
    return LabelRow(
        design_id=design_id, target_id="6M0J", sequence="MKTAYIAKQR",
        binds=True, binding_strength="strong", kd_nm=8.99, expressed=True,
        source="cao-2022", license="CC-BY-4.0", provenance="cao-2022:row_1",
        metric_blind_sampled=False,
    )


def test_load_missing_file_returns_empty(tmp_path):
    assert load_label_table(str(tmp_path / "nope.jsonl")) == []


def test_append_then_load_round_trips(tmp_path):
    path = str(tmp_path / "labels_master.jsonl")
    append_label_rows(path, [_row("a"), _row("b")])
    loaded = load_label_table(path)
    assert [r.design_id for r in loaded] == ["a", "b"]
    assert loaded[0] == _row("a")


def test_append_is_additive_not_truncating(tmp_path):
    path = str(tmp_path / "labels_master.jsonl")
    append_label_rows(path, [_row("a")])
    append_label_rows(path, [_row("b")])
    assert [r.design_id for r in load_label_table(path)] == ["a", "b"]


def test_append_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "labels.jsonl")
    append_label_rows(path, [_row("a")])
    assert [r.design_id for r in load_label_table(path)] == ["a"]


def test_one_json_object_per_line(tmp_path):
    path = str(tmp_path / "labels.jsonl")
    append_label_rows(path, [_row("a"), _row("b")])
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    assert len(lines) == 2
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.label_store'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_label_store.py -v
```
- [ ] Minimal implementation `data/label_store.py`:
```python
from __future__ import annotations

import json
import os
from typing import List, Sequence

from pc_contracts.core import LabelRow
from data.labels import label_row_from_dict, label_row_to_dict


def load_label_table(path: str) -> List[LabelRow]:
    if not os.path.exists(path):
        return []
    rows: List[LabelRow] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(label_row_from_dict(json.loads(line)))
    return rows


def append_label_rows(path: str, rows: Sequence[LabelRow]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(label_row_to_dict(row)) + "\n")
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_label_store.py -v
```
- [ ] Commit:
```
git add data/label_store.py data/tests/test_label_store.py
git commit -m "data: JSONL master label table load/append

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 23 — Harvest: source/license registry + parse LLM extraction response

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest.py`
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/fixtures/cao2022_sample.txt`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_harvest.py`

- [ ] Create the raw-input fixture `data/tests/fixtures/cao2022_sample.txt`:
```text
Cao et al. 2022, Table S3 (excerpt).
Design EHEE_0001 against SARS-CoV-2 RBD (PDB 6M0J), KD = 8.99 nM, expressed, binder.
Design HHH_0042 against PD-L1 (PDB 5O45), no measurable binding, expressed.
```
- [ ] Write the FAILING test `data/tests/test_harvest.py`:
```python
from __future__ import annotations

import json

import pytest

from data.harvest import (
    SOURCE_LICENSES,
    parse_llm_label_response,
)


def _llm_payload() -> str:
    return json.dumps({
        "labels": [
            {
                "design_id": "EHEE_0001", "target_id": "6M0J",
                "sequence": "MKTAYIAKQRQI", "binds": True,
                "binding_strength": "strong", "kd_nm": 8.99,
                "expressed": True, "provenance": "cao-2022:table_s3:EHEE_0001",
            },
            {
                "design_id": "HHH_0042", "target_id": "5O45",
                "sequence": "ACDEFGHIKLMN", "binds": False,
                "binding_strength": "none", "kd_nm": None,
                "expressed": True, "provenance": "cao-2022:table_s3:HHH_0042",
            },
        ]
    })


def test_source_license_registry_covers_all_five_sources():
    assert set(SOURCE_LICENSES) == {
        "cao-2022", "adaptyv", "ppb-affinity", "skempi-2.0", "sabdab"
    }


def test_parse_attaches_source_and_registry_license():
    rows = parse_llm_label_response(_llm_payload(), source="cao-2022")
    assert len(rows) == 2
    assert rows[0].source == "cao-2022"
    assert rows[0].license == SOURCE_LICENSES["cao-2022"]
    assert rows[0].target_id == "6M0J"
    assert rows[1].binds is False


def test_parse_defaults_metric_blind_sampled_false_for_public_data():
    rows = parse_llm_label_response(_llm_payload(), source="cao-2022")
    assert all(r.metric_blind_sampled is False for r in rows)


def test_parse_rejects_unregistered_source_as_p0_license_gate():
    with pytest.raises(ValueError, match="license"):
        parse_llm_label_response(_llm_payload(), source="random-blog")


def test_parse_raises_on_malformed_json():
    with pytest.raises(ValueError):
        parse_llm_label_response("not json", source="cao-2022")
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.harvest'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest.py -v
```
- [ ] Minimal implementation `data/harvest.py`:
```python
from __future__ import annotations

import json
from typing import List

from pc_contracts.core import LabelRow

# License strings are PLACEHOLDERS pending the P0 license-gate confirmation
# (Phase 0). The registry's job here is provenance integrity: only labels from a
# registered source may enter the master table, and the license is stamped
# deterministically (NEVER LLM-supplied).
SOURCE_LICENSES = {
    "cao-2022": "CC-BY-4.0",
    "adaptyv": "CC-BY-4.0",
    "ppb-affinity": "CC-BY-4.0",
    "skempi-2.0": "CC-BY-4.0",
    "sabdab": "CC-BY-4.0",
}


def parse_llm_label_response(raw_json: str, source: str) -> List[LabelRow]:
    src = source.strip().lower()
    if src not in SOURCE_LICENSES:
        raise ValueError(
            f"source {source!r} is not registered; license is unknown "
            f"(P0 license gate). Registered: {sorted(SOURCE_LICENSES)}"
        )
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc

    license_str = SOURCE_LICENSES[src]
    rows: List[LabelRow] = []
    for entry in parsed.get("labels", []):
        rows.append(LabelRow(
            design_id=entry["design_id"],
            target_id=entry["target_id"],
            sequence=entry["sequence"],
            binds=entry.get("binds"),
            binding_strength=entry.get("binding_strength"),
            kd_nm=entry.get("kd_nm"),
            expressed=entry.get("expressed"),
            source=src,
            license=license_str,
            provenance=entry.get("provenance", f"{src}:unknown"),
            metric_blind_sampled=bool(entry.get("metric_blind_sampled", False)),
        ))
    return rows
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest.py -v
```
- [ ] Commit:
```
git add data/harvest.py data/tests/test_harvest.py data/tests/fixtures/cao2022_sample.txt
git commit -m "data: source/license registry + LLM response parser (deterministic license stamp)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 24 — Harvest: `harvest_labels` orchestration (LLM proposes, validators gate, dedup)

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/harvest.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_harvest.py`

- [ ] Append the FAILING test to `data/tests/test_harvest.py`:
```python
from data.harvest import HarvestResult, harvest_labels
from pc_contracts.core import LabelRow


class _FakeLLM:
    """Stand-in for the injected LLM client; returns a fixed JSON string."""

    def __init__(self, response: str):
        self._response = response
        self.last_prompt = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response


def _existing(design_id: str = "dup") -> LabelRow:
    return LabelRow(
        design_id=design_id, target_id="6M0J", sequence="MKTAYIAKQRQI",
        binds=True, binding_strength="strong", kd_nm=8.99, expressed=True,
        source="cao-2022", license="CC-BY-4.0", provenance="cao-2022:prev",
        metric_blind_sampled=False,
    )


def test_harvest_accepts_valid_rows_and_prompts_with_raw_text():
    llm = _FakeLLM(_llm_payload())
    result = harvest_labels(
        raw_text="Cao Table S3 excerpt", source="cao-2022", llm_client=llm,
    )
    assert isinstance(result, HarvestResult)
    assert result.n_proposed == 2
    assert {r.design_id for r in result.accepted} == {"EHEE_0001", "HHH_0042"}
    assert result.rejected == []
    assert "Cao Table S3 excerpt" in llm.last_prompt


def test_harvest_rejects_rows_failing_validators():
    bad = json.dumps({"labels": [
        {"design_id": "x", "target_id": "Nipah virus G",  # unresolvable id
         "sequence": "XX1", "binds": True, "binding_strength": "strong",
         "kd_nm": 1.0, "expressed": True, "provenance": "cao-2022:x"},
    ]})
    result = harvest_labels(raw_text="t", source="cao-2022", llm_client=_FakeLLM(bad))
    assert result.accepted == []
    assert len(result.rejected) == 1
    assert any("target_id" in e for e in result.rejected[0]["errors"])
    assert any("sequence" in e for e in result.rejected[0]["errors"])


def test_harvest_dedups_against_existing_rows():
    llm = _FakeLLM(_llm_payload())
    result = harvest_labels(
        raw_text="t", source="cao-2022", llm_client=llm,
        existing_rows=[_existing()],  # collides with EHEE_0001 (6M0J/MKTAYIAKQRQI)
    )
    assert {r.design_id for r in result.accepted} == {"HHH_0042"}


def test_harvest_passes_resolver_through_to_validator():
    seen = {}

    def resolver(tid: str) -> bool:
        seen.setdefault("ids", []).append(tid)
        return True

    result = harvest_labels(
        raw_text="t", source="cao-2022", llm_client=_FakeLLM(_llm_payload()),
        resolver=resolver,
    )
    assert len(result.accepted) == 2
    assert "6M0J" in seen["ids"]
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'harvest_labels'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest.py -v
```
- [ ] Add to `data/harvest.py`:
```python
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from data.dedup import dedup_label_rows
from data.harvest_validators import validate_label_row

_EXTRACTION_INSTRUCTIONS = (
    "You are extracting REAL wet-lab binder labels into structured JSON. "
    "Return ONLY a JSON object: {\"labels\": [ {design_id, target_id, "
    "sequence, binds, binding_strength, kd_nm, expressed, provenance} ]}. "
    "target_id MUST be a real PDB id or UniProt accession. binding_strength "
    "in {strong, medium, weak, none}. kd_nm in nanomolar or null. Do not "
    "invent values; use null when unknown. Cite the row in provenance."
)


@dataclass
class HarvestResult:
    accepted: List[LabelRow] = field(default_factory=list)
    rejected: List[dict] = field(default_factory=list)
    n_proposed: int = 0


def _build_extraction_prompt(raw_text: str, source: str) -> str:
    return (
        f"{_EXTRACTION_INSTRUCTIONS}\n\n"
        f"SOURCE: {source}\n\n"
        f"RAW RECORDS:\n{raw_text}\n"
    )


def harvest_labels(
    raw_text: str,
    source: str,
    llm_client,
    resolver: Optional[Callable[[str], bool]] = None,
    existing_rows: Optional[Sequence[LabelRow]] = None,
) -> HarvestResult:
    prompt = _build_extraction_prompt(raw_text, source)
    raw_response = llm_client.complete(prompt)
    proposed = parse_llm_label_response(raw_response, source=source)

    result = HarvestResult(n_proposed=len(proposed))
    passed: List[LabelRow] = []
    for row in proposed:
        errors = validate_label_row(row, resolver=resolver)
        if errors:
            result.rejected.append({"design_id": row.design_id, "errors": errors})
        else:
            passed.append(row)

    result.accepted = dedup_label_rows(passed, existing_rows or [])
    return result
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_harvest.py -v
```
- [ ] Commit:
```
git add data/harvest.py data/tests/test_harvest.py
git commit -m "data: harvest_labels orchestration (LLM proposes, validators gate, dedup)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 25 — Backfill: map a raw tool panel into OUR Proteinbase feature space

The panel produces tool-native keys (`min_ipsae`, `iptm`, ...); they MUST land on the exact Proteinbase `computational__*` column names (incl. the misspelled `shape_complimentarity_boltz2_binder_ss`). Unmapped/None keys dropped; absent columns become NaN. Leakage guard: output may ONLY contain `computational__*` keys.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/feature_space.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_feature_space.py`

- [ ] Write the FAILING test `data/tests/test_feature_space.py`:
```python
from __future__ import annotations

import math

from data.feature_space import FEATURE_SPACE_COLUMNS, to_feature_space


def test_to_feature_space_renames_to_proteinbase_columns():
    panel = {
        "min_ipsae": 0.81,
        "ipsae": 0.79,
        "iptm": 0.62,
        "shape_complementarity": 0.55,
    }
    out = to_feature_space(panel)
    assert out["computational__boltz2_min_ipsae"] == 0.81
    assert out["computational__boltz2_ipsae"] == 0.79
    assert out["computational__boltz2_iptm"] == 0.62
    # exact misspelling from Proteinbase ground truth must be preserved
    assert out["computational__shape_complimentarity_boltz2_binder_ss"] == 0.55


def test_to_feature_space_fills_absent_columns_with_nan():
    out = to_feature_space({"min_ipsae": 0.81})
    assert math.isnan(out["computational__boltz2_lis"])
    assert set(out.keys()) == set(FEATURE_SPACE_COLUMNS)


def test_to_feature_space_drops_unmapped_and_none_and_blocks_leakage():
    out = to_feature_space({"min_ipsae": 0.81, "garbage_key": 1.0, "iptm": None})
    assert "garbage_key" not in out
    assert math.isnan(out["computational__boltz2_iptm"])  # None -> NaN, not stored
    assert all(c.startswith("computational__") for c in out)
    assert not any(c.startswith("experimental__") for c in out)
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.feature_space'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_feature_space.py -v
```
- [ ] Minimal implementation `data/feature_space.py`:
```python
from __future__ import annotations

from typing import Dict

# Tool-native panel key -> exact Proteinbase computational__* column.
# Column names are the ground-truth names from `Proteinbase Analysis.ipynb`
# (the misspelling 'complimentarity' is intentional / load-bearing).
PANEL_TO_FEATURE: Dict[str, str] = {
    "min_ipsae": "computational__boltz2_min_ipsae",
    "ipsae": "computational__boltz2_ipsae",
    "iptm": "computational__boltz2_iptm",
    "ptm": "computational__boltz2_ptm",
    "plddt": "computational__boltz2_plddt",
    "complex_plddt": "computational__boltz2_complex_plddt",
    "complex_iplddt": "computational__boltz2_complex_iplddt",
    "complex_pde": "computational__boltz2_complex_pde",
    "lis": "computational__boltz2_lis",
    "pdockq": "computational__boltz2_pdockq",
    "pdockq2": "computational__boltz2_pdockq2",
    "shape_complementarity": "computational__shape_complimentarity_boltz2_binder_ss",
    "esmfold_plddt": "computational__esmfold_plddt",
    "proteinmpnn_score": "computational__proteinmpnn_score",
}

FEATURE_SPACE_COLUMNS = tuple(PANEL_TO_FEATURE.values())


def to_feature_space(panel: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {col: float("nan") for col in FEATURE_SPACE_COLUMNS}
    for key, value in panel.items():
        col = PANEL_TO_FEATURE.get(key)
        if col is None or value is None:
            continue
        out[col] = float(value)
    return out
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_feature_space.py -v
```
- [ ] Commit:
```
git add data/feature_space.py data/tests/test_feature_space.py
git commit -m "data: map raw tool panel to Proteinbase feature-space columns (leakage-clean)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 26 — Backfill: record which tool blocks produced metrics

`metric_blocks_present` is `dict[str,bool]`. A block is present iff at least one of its panel keys is non-None — lets the corrector distinguish "metric is genuinely NaN" from "this whole tool never ran on this harvested seq."

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/feature_space.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_feature_space.py`

- [ ] Add the FAILING test to `data/tests/test_feature_space.py`:
```python
from data.feature_space import blocks_present


def test_blocks_present_flags_only_blocks_with_values():
    panel = {"min_ipsae": 0.81, "iptm": 0.62, "esmfold_plddt": None}
    present = blocks_present(panel)
    assert present["boltz2"] is True
    assert present["esmfold"] is False     # only None -> block absent
    assert present["proteinmpnn"] is False  # key missing entirely -> absent


def test_blocks_present_all_blocks_keyed():
    present = blocks_present({})
    assert set(present.keys()) == {"boltz2", "esmfold", "proteinmpnn"}
    assert all(v is False for v in present.values())
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'blocks_present'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_feature_space.py::test_blocks_present_flags_only_blocks_with_values -v
```
- [ ] Append to `data/feature_space.py`:
```python
# Which panel keys belong to which sequence-scoring tool block. Only the
# structure_prediction (boltz2) + embedding/scoring tools score an existing
# sequence; generative tools are excluded by design (grounding).
BLOCK_METRICS: Dict[str, tuple] = {
    "boltz2": (
        "min_ipsae", "ipsae", "iptm", "ptm", "plddt", "complex_plddt",
        "complex_iplddt", "complex_pde", "lis", "pdockq", "pdockq2",
        "shape_complementarity",
    ),
    "esmfold": ("esmfold_plddt",),
    "proteinmpnn": ("proteinmpnn_score",),
}


def blocks_present(panel: Dict[str, float]) -> Dict[str, bool]:
    return {
        block: any(panel.get(k) is not None for k in keys)
        for block, keys in BLOCK_METRICS.items()
    }
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_feature_space.py -v
```
- [ ] Commit:
```
git add data/feature_space.py data/tests/test_feature_space.py
git commit -m "data: derive metric_blocks_present from raw tool panel

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 27 — Backfill: build a `DesignRow` from a `LabelRow` + feature-space metrics

Reuses the label's `design_id`/`target_id`/`sequence` so the design and its real wet-lab label share an id (the join key). Harvested designs have no design seed → `seed=0`.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Write the FAILING test `data/tests/test_backfill.py`:
```python
from __future__ import annotations

import math

from pc_contracts.core import DesignRow, LabelRow
from data.backfill import make_design_row


def _label(design_id="d1", target_id="t1", seq="MKV"):
    return LabelRow(
        design_id=design_id, target_id=target_id, sequence=seq,
        binds=True, binding_strength="Strong", kd_nm=8.99, expressed=True,
        source="Cao2022", license="CC-BY-4.0", provenance="cao2022:tableS3",
        metric_blind_sampled=False,
    )


def test_make_design_row_carries_ids_and_feature_metrics():
    metrics = {"computational__boltz2_min_ipsae": 0.81, "computational__boltz2_lis": float("nan")}
    blocks = {"boltz2": True, "esmfold": False, "proteinmpnn": False}
    row = make_design_row(
        _label(), metrics, blocks,
        tool="boltz2", tool_version="1", config_hash="cfg-abc",
        cost_usd=0.42, wallclock_sec=120.0,
    )
    assert isinstance(row, DesignRow)
    assert row.design_id == "d1"
    assert row.target_id == "t1"
    assert row.sequence == "MKV"
    assert row.tool == "boltz2"
    assert row.tool_version == "1"
    assert row.config_hash == "cfg-abc"
    assert row.seed == 0
    assert row.metrics["computational__boltz2_min_ipsae"] == 0.81
    assert math.isnan(row.metrics["computational__boltz2_lis"])
    assert row.metric_blocks_present["boltz2"] is True
    assert row.cost_usd == 0.42
    assert row.wallclock_sec == 120.0
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.backfill'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py::test_make_design_row_carries_ids_and_feature_metrics -v
```
- [ ] Minimal implementation `data/backfill.py`:
```python
from __future__ import annotations

from typing import Dict

from pc_contracts.core import DesignRow, LabelRow


def make_design_row(
    label: LabelRow,
    metrics: Dict[str, float],
    metric_blocks_present: Dict[str, bool],
    *,
    tool: str,
    tool_version: str,
    config_hash: str,
    cost_usd: float,
    wallclock_sec: float,
    seed: int = 0,
) -> DesignRow:
    return DesignRow(
        design_id=label.design_id,
        target_id=label.target_id,
        tool=tool,
        tool_version=tool_version,
        config_hash=config_hash,
        seed=seed,
        sequence=label.sequence,
        metrics=metrics,
        metric_blocks_present=metric_blocks_present,
        cost_usd=cost_usd,
        wallclock_sec=wallclock_sec,
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: build DesignRow from LabelRow + feature-space metrics

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 28 — Backfill: JSONL manifest (persist, reload, select pending) for resume + idempotency

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Add the FAILING test to `data/tests/test_backfill.py`:
```python
from data.backfill import (
    append_manifest,
    completed_ids,
    load_manifest,
    select_pending,
)


def test_manifest_roundtrip_preserves_design_and_nan(tmp_path):
    path = str(tmp_path / "manifest.jsonl")
    row = make_design_row(
        _label("d1"), {"computational__boltz2_lis": float("nan")},
        {"boltz2": True, "esmfold": False, "proteinmpnn": False},
        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.1, wallclock_sec=10.0,
    )
    append_manifest(path, row)
    loaded = load_manifest(path)
    assert set(loaded.keys()) == {"d1"}
    assert math.isnan(loaded["d1"].metrics["computational__boltz2_lis"])
    assert loaded["d1"].cost_usd == 0.1


def test_load_manifest_missing_file_is_empty(tmp_path):
    assert load_manifest(str(tmp_path / "nope.jsonl")) == {}


def test_select_pending_skips_completed(tmp_path):
    path = str(tmp_path / "m.jsonl")
    done_row = make_design_row(
        _label("d1"), {}, {"boltz2": True, "esmfold": False, "proteinmpnn": False},
        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.0, wallclock_sec=0.0,
    )
    append_manifest(path, done_row)
    manifest = load_manifest(path)
    pending = select_pending([_label("d1"), _label("d2"), _label("d3")], completed_ids(manifest))
    assert [l.design_id for l in pending] == ["d2", "d3"]
```
- [ ] Run it — expect **FAIL** (`ImportError` on manifest helpers):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest "data/tests/test_backfill.py::test_manifest_roundtrip_preserves_design_and_nan" -v
```
- [ ] Append to `data/backfill.py`:
```python
import json
import os
from dataclasses import asdict
from typing import List, Set


def append_manifest(path: str, row: DesignRow) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # allow_nan=True so genuinely-missing metrics survive the roundtrip as NaN.
    line = json.dumps(asdict(row), allow_nan=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_manifest(path: str) -> Dict[str, DesignRow]:
    if not os.path.exists(path):
        return {}
    rows: Dict[str, DesignRow] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = DesignRow(**json.loads(line))
            rows[row.design_id] = row
    return rows


def completed_ids(manifest: Dict[str, DesignRow]) -> Set[str]:
    return set(manifest.keys())


def select_pending(labels: List[LabelRow], done: Set[str]) -> List[LabelRow]:
    return [label for label in labels if label.design_id not in done]
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: JSONL manifest persistence + pending-label selection for resume

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 29 — Backfill: cost/compute summary

Honors the "cost-logged" requirement: total spend and wallclock are auditable after any run.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Add the FAILING test to `data/tests/test_backfill.py`:
```python
from data.backfill import cost_summary


def test_cost_summary_aggregates_spend_and_time():
    rows = [
        make_design_row(_label("d1"), {}, {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.40, wallclock_sec=100.0),
        make_design_row(_label("d2"), {}, {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.60, wallclock_sec=50.0),
    ]
    summary = cost_summary(rows)
    assert summary == {"n_designs": 2, "total_cost_usd": 1.0, "total_wallclock_sec": 150.0}


def test_cost_summary_empty():
    assert cost_summary([]) == {"n_designs": 0, "total_cost_usd": 0.0, "total_wallclock_sec": 0.0}
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'cost_summary'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -k cost_summary -v
```
- [ ] Append to `data/backfill.py`:
```python
def cost_summary(rows: List[DesignRow]) -> Dict[str, float]:
    return {
        "n_designs": len(rows),
        "total_cost_usd": float(sum(r.cost_usd for r in rows)),
        "total_wallcl
```python
def cost_summary(rows: List[DesignRow]) -> Dict[str, float]:
    return {
        "n_designs": len(rows),
        "total_cost_usd": float(sum(r.cost_usd for r in rows)),
        "total_wallclock_sec": float(sum(r.wallclock_sec for r in rows)),
    }
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: cost/wallclock summary over backfilled designs

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 30 — Backfill: `backfill_features` orchestrator (idempotent + resumable + cost-logged)

Injected `run_panel_fn(label) -> PanelResult` decouples orchestration from the actual GPU runner (tested with a fake). Each completed design is appended to the manifest immediately, so a crash mid-run loses nothing and a re-run skips finished ids and re-spends nothing.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Add the FAILING test to `data/tests/test_backfill.py`:
```python
from data.backfill import PanelResult, backfill_features


def test_backfill_features_runs_pending_and_is_idempotent(tmp_path):
    path = str(tmp_path / "m.jsonl")
    labels = [_label("d1", seq="MKV"), _label("d2", seq="AAA")]
    calls = []

    def fake_panel(label):
        calls.append(label.design_id)
        return PanelResult(
            raw_metrics={"min_ipsae": 0.81, "iptm": 0.62},
            cost_usd=0.5, wallclock_sec=90.0,
        )

    rows = backfill_features(labels, path, fake_panel,
                             tool="boltz2", tool_version="1", config_hash="cfg")
    assert sorted(r.design_id for r in rows) == ["d1", "d2"]
    r1 = next(r for r in rows if r.design_id == "d1")
    assert r1.metrics["computational__boltz2_min_ipsae"] == 0.81
    assert r1.metric_blocks_present["boltz2"] is True
    assert r1.cost_usd == 0.5

    # second run: everything already in manifest -> NO new panel calls (idempotent)
    calls.clear()
    rows2 = backfill_features(labels, path, fake_panel,
                              tool="boltz2", tool_version="1", config_hash="cfg")
    assert calls == []
    assert sorted(r.design_id for r in rows2) == ["d1", "d2"]


def test_backfill_features_resumes_after_partial(tmp_path):
    path = str(tmp_path / "m.jsonl")
    labels = [_label("d1"), _label("d2")]
    # simulate a crash: d1 already persisted
    append_manifest(path, make_design_row(
        _label("d1"), {"computational__boltz2_min_ipsae": 0.7},
        {"boltz2": True, "esmfold": False, "proteinmpnn": False},
        tool="boltz2", tool_version="1", config_hash="cfg", cost_usd=0.5, wallclock_sec=90.0))
    seen = []

    def fake_panel(label):
        seen.append(label.design_id)
        return PanelResult(raw_metrics={"min_ipsae": 0.9}, cost_usd=0.5, wallclock_sec=90.0)

    backfill_features(labels, path, fake_panel,
                      tool="boltz2", tool_version="1", config_hash="cfg")
    assert seen == ["d2"]  # only the unfinished label ran
```
- [ ] Run it — expect **FAIL** (`ImportError: PanelResult, backfill_features`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -k backfill_features -v
```
- [ ] Append to `data/backfill.py`:
```python
from dataclasses import dataclass
from typing import Callable

from data.feature_space import blocks_present, to_feature_space


@dataclass
class PanelResult:
    raw_metrics: Dict[str, float]
    cost_usd: float
    wallclock_sec: float


def backfill_features(
    labels: List[LabelRow],
    manifest_path: str,
    run_panel_fn: Callable[[LabelRow], PanelResult],
    *,
    tool: str,
    tool_version: str,
    config_hash: str,
) -> List[DesignRow]:
    manifest = load_manifest(manifest_path)
    rows = list(manifest.values())
    for label in select_pending(labels, completed_ids(manifest)):
        panel = run_panel_fn(label)
        row = make_design_row(
            label,
            to_feature_space(panel.raw_metrics),
            blocks_present(panel.raw_metrics),
            tool=tool,
            tool_version=tool_version,
            config_hash=config_hash,
            cost_usd=panel.cost_usd,
            wallclock_sec=panel.wallclock_sec,
        )
        append_manifest(manifest_path, row)  # persist before continuing -> resumable
        rows.append(row)
    return rows
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: idempotent resumable cost-logged backfill orchestrator

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 31 — Backfill: Nebius/Vast runner wrapper `run_panel_via_nebius` (mocked)

Concrete `run_panel_fn` that drives the metric panel on a remote H100 by reusing `run_validation_job` from `nebius/runner.py` (grounding: detached docker run + poll `_RUN_DONE` + SCP). The runner is passed in (duck-typed), so the unit test mocks it — no SSH, no paramiko import, mirroring `dynamics/`'s fixture+mock policy for Linux-only infra.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Add the FAILING test to `data/tests/test_backfill.py`:
```python
from data.backfill import run_panel_via_nebius


def test_run_panel_via_nebius_extracts_metrics_and_cost(mocker):
    runner = mocker.Mock()
    runner.run_validation_job.return_value = {
        "metrics": {"min_ipsae": 0.81, "iptm": 0.62, "plddt": 88.0},
        "cost_usd": 0.37,
        "wallclock_sec": 142.0,
    }
    result = run_panel_via_nebius(_label("d1", seq="MKV"), runner, target_cif_path="5G51.cif")
    assert isinstance(result, PanelResult)
    assert result.raw_metrics["min_ipsae"] == 0.81
    assert result.cost_usd == 0.37
    assert result.wallclock_sec == 142.0
    runner.run_validation_job.assert_called_once()
    _, kwargs = runner.run_validation_job.call_args
    assert kwargs["sequence"] == "MKV"
    assert kwargs["target_cif"] == "5G51.cif"


def test_run_panel_via_nebius_defaults_missing_cost_to_zero(mocker):
    runner = mocker.Mock()
    runner.run_validation_job.return_value = {"metrics": {"min_ipsae": 0.5}}
    result = run_panel_via_nebius(_label("d1"), runner, target_cif_path="t.cif")
    assert result.cost_usd == 0.0
    assert result.raw_metrics["min_ipsae"] == 0.5
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'run_panel_via_nebius'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -k run_panel_via_nebius -v
```
- [ ] Append to `data/backfill.py`:
```python
import time
from typing import Any


def run_panel_via_nebius(label: LabelRow, runner: Any, target_cif_path: str) -> PanelResult:
    """Drive the sequence-scoring panel on a remote VM.

    `runner` is a duck-typed nebius.runner.Runner exposing run_validation_job(
    seed, sequence, target_cif) -> dict (grounding). Injected, not imported, so
    unit tests stay off the network.
    """
    t0 = time.monotonic()
    result = runner.run_validation_job(
        seed=0, sequence=label.sequence, target_cif=target_cif_path
    )
    return PanelResult(
        raw_metrics=dict(result.get("metrics", {})),
        cost_usd=float(result.get("cost_usd", 0.0)),
        wallclock_sec=float(result.get("wallclock_sec", time.monotonic() - t0)),
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: nebius/vast run_panel_via_nebius wrapper over run_validation_job

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 32 — Backfill: join backfilled `DesignRow`s back to their `LabelRow`s

Final backfill deliverable: design+label pairs on the shared `design_id`, ready for `run_loto_eval` / `train_corrector`. Designs whose label is absent are dropped (never silently merged).

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/backfill.py`
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_backfill.py`

- [ ] Add the FAILING test to `data/tests/test_backfill.py`:
```python
from data.backfill import join_designs_to_labels


def test_join_designs_to_labels_pairs_on_design_id():
    labels = [_label("d1"), _label("d2")]
    rows = [
        make_design_row(_label("d1"), {"computational__boltz2_min_ipsae": 0.81},
                        {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.1, wallclock_sec=1.0),
        make_design_row(_label("d2"), {"computational__boltz2_min_ipsae": 0.40},
                        {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.1, wallclock_sec=1.0),
    ]
    joined = join_designs_to_labels(rows, labels)
    assert len(joined) == 2
    pair = next(j for j in joined if j["design"].design_id == "d1")
    assert pair["label"].binds is True
    assert pair["design"].metrics["computational__boltz2_min_ipsae"] == 0.81


def test_join_drops_designs_without_matching_label():
    labels = [_label("d1")]
    rows = [
        make_design_row(_label("d1"), {}, {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.0, wallclock_sec=0.0),
        make_design_row(_label("orphan"), {}, {"boltz2": True, "esmfold": False, "proteinmpnn": False},
                        tool="boltz2", tool_version="1", config_hash="c", cost_usd=0.0, wallclock_sec=0.0),
    ]
    joined = join_designs_to_labels(rows, labels)
    assert [j["design"].design_id for j in joined] == ["d1"]
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'join_designs_to_labels'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_backfill.py -k join -v
```
- [ ] Append to `data/backfill.py`:
```python
def join_designs_to_labels(
    rows: List[DesignRow], labels: List[LabelRow]
) -> List[Dict[str, object]]:
    by_id = {label.design_id: label for label in labels}
    joined: List[Dict[str, object]] = []
    for row in rows:
        label = by_id.get(row.design_id)
        if label is None:
            continue  # design without a real label cannot enter the eval set
        joined.append({"design": row, "label": label})
    return joined
```
- [ ] Run the whole backfill suite — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_feature_space.py data/tests/test_backfill.py -v
```
- [ ] Commit:
```
git add data/backfill.py data/tests/test_backfill.py
git commit -m "data: join backfilled DesignRows to LabelRows on design_id

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 33 — Protocol: gap-filling target selection (fill under-represented interface classes)

The protocol modules (Tasks 33–39) operate on **dict-shaped** design/target records read from external files (CSV/NDJSON), conforming to the contract field names. `INTERFACE_CLASSES` is re-exported from `pc_contracts` (single source of truth).

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/target_selection.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_target_selection.py`

- [ ] Write the FAILING test `data/tests/test_target_selection.py`:
```python
from __future__ import annotations

from data.target_selection import (
    INTERFACE_CLASSES,
    TargetGap,
    compute_class_gaps,
    select_gap_filling_targets,
)


def _tf(target_id: str, interface_class: str) -> dict:
    return {"target_id": target_id, "interface_class": interface_class}


def test_interface_classes_are_the_four_design_classes():
    assert INTERFACE_CLASSES == ("helical", "sheet_flat", "mixed", "ligand_present")


def test_compute_class_gaps_counts_existing_and_unmet_need():
    existing = [_tf(f"h{i}", "helical") for i in range(4)]
    gaps = {g.interface_class: g for g in compute_class_gaps(existing, min_per_class=3)}
    assert isinstance(gaps["helical"], TargetGap)
    assert gaps["helical"].n_existing == 4 and gaps["helical"].n_needed == 0
    assert gaps["sheet_flat"].n_needed == 3
    assert gaps["mixed"].n_needed == 3
    assert gaps["ligand_present"].n_needed == 3


def test_compute_class_gaps_rejects_unknown_class():
    import pytest
    with pytest.raises(ValueError):
        compute_class_gaps([_tf("x", "alpha_beta")], min_per_class=3)


def test_select_fills_gaps_and_skips_satisfied_classes():
    existing = [_tf(f"h{i}", "helical") for i in range(4)]  # helical already satisfied
    candidates = (
        [_tf(f"sf{i}", "sheet_flat") for i in range(5)]
        + [_tf(f"mx{i}", "mixed") for i in range(2)]
        + [_tf(f"lg{i}", "ligand_present") for i in range(4)]
        + [_tf(f"h{i}", "helical") for i in range(9, 12)]
    )
    selected = select_gap_filling_targets(existing, candidates, min_per_class=3)
    by_class = {}
    for t in selected:
        by_class.setdefault(t["interface_class"], []).append(t)
    assert "helical" not in by_class                       # no need -> none picked
    assert len(by_class["sheet_flat"]) == 3                # capped at need
    assert len(by_class["mixed"]) == 2                     # only 2 available
    assert len(by_class["ligand_present"]) == 3
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.target_selection'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_target_selection.py -v
```
- [ ] Minimal implementation `data/target_selection.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pc_contracts.core import INTERFACE_CLASSES  # single source of truth

if TYPE_CHECKING:
    from pc_contracts.core import TargetFeatures


@dataclass
class TargetGap:
    interface_class: str
    n_existing: int
    n_needed: int


def compute_class_gaps(
    existing: "list[TargetFeatures]", min_per_class: int = 3
) -> "list[TargetGap]":
    counts = {c: 0 for c in INTERFACE_CLASSES}
    for tf in existing:
        ic = tf["interface_class"]
        if ic not in counts:
            raise ValueError(f"unknown interface_class: {ic!r}")
        counts[ic] += 1
    return [
        TargetGap(c, counts[c], max(0, min_per_class - counts[c]))
        for c in INTERFACE_CLASSES
    ]


def select_gap_filling_targets(
    existing: "list[TargetFeatures]",
    candidates: "list[TargetFeatures]",
    min_per_class: int = 3,
) -> "list[TargetFeatures]":
    need = {g.interface_class: g.n_needed for g in compute_class_gaps(existing, min_per_class)}
    selected: list = []
    # largest gap first so scarce classes are filled before quota is spent
    for ic in sorted(need, key=lambda c: need[c], reverse=True):
        if need[ic] <= 0:
            continue
        pool = [c for c in candidates if c["interface_class"] == ic]
        selected.extend(pool[: need[ic]])
    return selected
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_target_selection.py -v
```
- [ ] Commit:
```
git add data/target_selection.py data/tests/test_target_selection.py
git commit -m "data: gap-filling interface-class target selection for new-label campaigns

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 34 — Pure-negative target handling (AUDIT-G)

Targets with NO positives (HSA, TNFA, GM2A, ORM2 in the current dataset) must be excluded from ranking/LOTO folds — `Recall@k` is undefined (returns NaN) when there are no positives, which corrupts fold statistics. They are routed to a separate specificity / false-positive diagnostic set where they DO contribute useful signal.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/etl.py` (add `PURE_NEGATIVE_TARGETS`, `tag_pure_negative_targets`, `split_by_positive_coverage`)
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_pure_negative_targets.py`

- [ ] Write the FAILING test `data/tests/test_pure_negative_targets.py`:
```python
from __future__ import annotations

import pytest

from data.etl import (
    PURE_NEGATIVE_TARGETS,
    split_by_positive_coverage,
    tag_pure_negative_targets,
)
from pc_contracts.core import LabelRow


def _row(target_id: str, binds) -> LabelRow:
    return LabelRow(
        design_id=f"{target_id}-{binds}", target_id=target_id,
        sequence="MKTAYIAKQR", binds=binds, binding_strength=None,
        kd_nm=None, expressed=True, source="proteinbase", license="x",
        provenance="p", metric_blind_sampled=False,
    )


def test_pure_negative_targets_are_defined():
    assert isinstance(PURE_NEGATIVE_TARGETS, frozenset)
    # The four targets with no positives in the current dataset
    for tid in ("hsa", "tnfa", "gm2a", "orm2"):
        assert tid in PURE_NEGATIVE_TARGETS, (
            f"{tid!r} must be in PURE_NEGATIVE_TARGETS — it has no positives "
            "and would cause NaN Recall@k in LOTO folds"
        )


def test_tag_pure_negative_targets_adds_flag():
    rows = [_row("hsa", False), _row("pd-l1", True), _row("pd-l1", False)]
    tagged = tag_pure_negative_targets(rows)
    by_target = {r["target_id"]: r for r in tagged}
    assert by_target["hsa"]["is_pure_negative_target"] is True
    assert by_target["pd-l1"]["is_pure_negative_target"] is False


def test_split_by_positive_coverage_separates_pure_negatives():
    rows = [
        _row("hsa", False), _row("hsa", False),
        _row("pd-l1", True), _row("pd-l1", False),
        _row("tnfa", False),
    ]
    ranking_rows, diagnostic_rows = split_by_positive_coverage(rows)
    ranking_targets = {r.target_id for r in ranking_rows}
    diag_targets = {r.target_id for r in diagnostic_rows}
    assert "pd-l1" in ranking_targets
    assert "hsa" not in ranking_targets and "tnfa" not in ranking_targets
    assert "hsa" in diag_targets and "tnfa" in diag_targets


def test_split_raises_if_ranking_fold_has_no_positives():
    """A target in ranking_rows must have at least one positive."""
    rows = [_row("hsa", False), _row("hsa", False)]
    ranking_rows, diagnostic_rows = split_by_positive_coverage(rows)
    # hsa has no positives -> goes to diagnostic, ranking is empty
    assert len(ranking_rows) == 0
    assert len(diagnostic_rows) == 2


def test_split_uses_actual_label_counts_not_just_allowlist():
    """A NEW target with all negatives should also be routed to diagnostic."""
    rows = [_row("new_target_xyz", False), _row("new_target_xyz", False)]
    ranking_rows, diagnostic_rows = split_by_positive_coverage(rows)
    assert len(ranking_rows) == 0
    assert len(diagnostic_rows) == 2
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'PURE_NEGATIVE_TARGETS'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_pure_negative_targets.py -v
```
- [ ] Add to `data/etl.py`:
```python
# Targets with NO positives in the current labeled dataset (AUDIT-G).
# These must be EXCLUDED from ranking/LOTO folds because Recall@k is undefined
# (returns NaN) when there are no positives.  They are routed to a separate
# specificity / false-positive diagnostic set.
# NOTE: split_by_positive_coverage() checks ACTUAL label counts, not just this
# set, so any NEW target that ends up all-negative is also routed correctly.
PURE_NEGATIVE_TARGETS: frozenset[str] = frozenset({"hsa", "tnfa", "gm2a", "orm2"})


def tag_pure_negative_targets(
    rows: List[LabelRow],
) -> List[Dict[str, Any]]:
    """Return rows as dicts with an 'is_pure_negative_target' bool tag."""
    target_has_positive: Dict[str, bool] = {}
    for r in rows:
        if r.binds is True:
            target_has_positive[r.target_id] = True
        else:
            target_has_positive.setdefault(r.target_id, False)
    return [
        {**asdict(r), "is_pure_negative_target": not target_has_positive.get(r.target_id, False)}
        for r in rows
    ]


def split_by_positive_coverage(
    rows: List[LabelRow],
) -> Tuple[List[LabelRow], List[LabelRow]]:
    """Split labeled rows into (ranking_rows, diagnostic_rows).

    ranking_rows: targets with >=1 positive; safe for LOTO ranking/Recall@k.
    diagnostic_rows: targets with 0 positives; routed to specificity diagnostic.

    Uses ACTUAL label counts (not just PURE_NEGATIVE_TARGETS allowlist) so any
    new all-negative target is also routed correctly without manual registration.
    """
    target_has_positive: Dict[str, bool] = {}
    for r in rows:
        if r.binds is True:
            target_has_positive[r.target_id] = True
        else:
            target_has_positive.setdefault(r.target_id, False)
    ranking: List[LabelRow] = []
    diagnostic: List[LabelRow] = []
    for r in rows:
        if target_has_positive.get(r.target_id, False):
            ranking.append(r)
        else:
            diagnostic.append(r)
    return ranking, diagnostic
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_pure_negative_targets.py -v
```
- [ ] Commit:
```
git add data/etl.py data/tests/test_pure_negative_targets.py
git commit -m "data: pure-negative target routing (HSA/TNFA/GM2A/ORM2 -> specificity diagnostic set)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 35 — Protocol: metric-blind sampling (deliberately include low scorers for honest negatives)

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/metric_blind.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_metric_blind.py`

- [ ] Write the FAILING test `data/tests/test_metric_blind.py`:
```python
from __future__ import annotations

import pytest

from data.metric_blind import SamplingPlan, metric_blind_sample


def _design(i: int, score, target: str = "T1") -> dict:
    return {
        "design_id": f"d{i}",
        "target_id": target,
        "sequence": "M" + "A" * 40,
        "metrics": {"boltz2_min_ipsae": score},
    }


def test_plan_all_ids_is_top_plus_random():
    designs = [_design(i, float(i)) for i in range(30)]
    plan = metric_blind_sample(designs, n_top=12, n_random=8, seed=0)
    assert isinstance(plan, SamplingPlan)
    assert plan.target_id == "T1"
    assert plan.score_metric == "boltz2_min_ipsae"
    assert len(plan.top_ids) == 12
    assert len(plan.random_ids) == 8
    assert plan.all_ids == plan.top_ids + plan.random_ids


def test_top_are_highest_scoring_and_randoms_are_honest_negatives():
    designs = [_design(i, float(i)) for i in range(30)]  # scores 0..29
    plan = metric_blind_sample(designs, n_top=12, n_random=8, seed=0)
    by_id = {d["design_id"]: d["metrics"]["boltz2_min_ipsae"] for d in designs}
    top_scores = [by_id[i] for i in plan.top_ids]
    rand_scores = [by_id[i] for i in plan.random_ids]
    assert set(plan.top_ids).isdisjoint(plan.random_ids)
    assert min(top_scores) == 18.0                 # top-12 are 18..29
    assert max(rand_scores) < min(top_scores)


def test_deterministic_under_fixed_seed():
    designs = [_design(i, float(i)) for i in range(30)]
    a = metric_blind_sample(designs, n_top=12, n_random=8, seed=7)
    b = metric_blind_sample(designs, n_top=12, n_random=8, seed=7)
    assert a.random_ids == b.random_ids


def test_nan_scores_sort_to_bottom_not_top():
    designs = [_design(i, float(i)) for i in range(10)] + [_design(99, None)]
    plan = metric_blind_sample(designs, n_top=3, n_random=2, seed=0)
    assert "d99" not in plan.top_ids


def test_rejects_multi_target_input():
    designs = [_design(0, 1.0, "T1"), _design(1, 2.0, "T2")]
    with pytest.raises(ValueError):
        metric_blind_sample(designs, n_top=1, n_random=1)
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.metric_blind'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_metric_blind.py -v
```
- [ ] Minimal implementation `data/metric_blind.py`:
```python
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pc_contracts.core import DesignRow


@dataclass
class SamplingPlan:
    target_id: str
    score_metric: str
    top_ids: list[str]
    random_ids: list[str]

    @property
    def all_ids(self) -> list[str]:
        return list(self.top_ids) + list(self.random_ids)


def metric_blind_sample(
    designs: "list[DesignRow]",
    score_metric: str = "boltz2_min_ipsae",
    n_top: int = 12,
    n_random: int = 8,
    seed: int = 0,
) -> SamplingPlan:
    if not designs:
        raise ValueError("no designs to sample")
    targets = {d["target_id"] for d in designs}
    if len(targets) != 1:
        raise ValueError(f"metric_blind_sample expects one target, got {sorted(targets)}")
    target_id = next(iter(targets))

    def score(d: "DesignRow") -> float:
        v = d["metrics"].get(score_metric)
        return -math.inf if v is None else float(v)

    ranked = sorted(designs, key=score, reverse=True)
    top = ranked[:n_top]
    remainder = ranked[n_top:]
    rng = random.Random(seed)
    k = min(n_random, len(remainder))
    randoms = rng.sample(remainder, k)  # uniform over the NON-top pool -> includes low scorers
    return SamplingPlan(
        target_id=target_id,
        score_metric=score_metric,
        top_ids=[d["design_id"] for d in top],
        random_ids=[d["design_id"] for d in randoms],
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_metric_blind.py -v
```
- [ ] Commit:
```
git add data/metric_blind.py data/tests/test_metric_blind.py
git commit -m "data: metric-blind sampling (top-k + uniform non-top) for honest wet-lab negatives

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 36 — Protocol: wet-lab submission packaging (FASTA + manifest)

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/wetlab_submission.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_wetlab_submission.py`

- [ ] Write the FAILING test `data/tests/test_wetlab_submission.py`:
```python
from __future__ import annotations

import csv

import pytest

from data.metric_blind import SamplingPlan
from data.wetlab_submission import (
    SubmissionPackage,
    package_wetlab_submission,
    write_submission,
)


def _design(did: str, seq: str, target: str = "T1") -> dict:
    return {"design_id": did, "target_id": target, "sequence": seq, "metrics": {}}


def test_package_marks_sampled_by_and_metric_blind_flag():
    designs = [_design("d1", "MAAA"), _design("d2", "MBBB"), _design("d3", "MCCC")]
    plan = SamplingPlan("T1", "boltz2_min_ipsae", top_ids=["d1"], random_ids=["d2", "d3"])
    pkg = package_wetlab_submission(designs, plan, service="adaptyv")
    assert isinstance(pkg, SubmissionPackage)
    assert pkg.n_designs == 3
    rows = {r["design_id"]: r for r in pkg.manifest}
    assert rows["d1"]["sampled_by"] == "top"
    assert rows["d2"]["sampled_by"] == "random"
    assert all(r["metric_blind_sampled"] is True for r in pkg.manifest)
    assert pkg.fasta_text.startswith(">d1\nMAAA")


def test_rejects_unknown_service():
    plan = SamplingPlan("T1", "boltz2_min_ipsae", top_ids=["d1"], random_ids=[])
    with pytest.raises(ValueError):
        package_wetlab_submission([_design("d1", "MAAA")], plan, service="zymo")


def test_write_submission_emits_fasta_and_manifest(tmp_path):
    designs = [_design("d1", "MAAA"), _design("d2", "MBBB")]
    plan = SamplingPlan("T1", "boltz2_min_ipsae", top_ids=["d1"], random_ids=["d2"])
    pkg = package_wetlab_submission(designs, plan, service="prof_loi")
    paths = write_submission(pkg, str(tmp_path))
    assert paths["fasta"].endswith("T1_prof_loi.fasta")
    with open(paths["manifest"]) as fh:
        manifest = list(csv.DictReader(fh))
    assert {r["design_id"] for r in manifest} == {"d1", "d2"}
    assert all(r["metric_blind_sampled"] == "True" for r in manifest)
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.wetlab_submission'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_wetlab_submission.py -v
```
- [ ] Minimal implementation `data/wetlab_submission.py`:
```python
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.metric_blind import SamplingPlan
    from pc_contracts.core import DesignRow

VALID_SERVICES = ("adaptyv", "prof_loi")
MANIFEST_FIELDS = ["design_id", "target_id", "sequence", "sampled_by", "metric_blind_sampled"]


@dataclass
class SubmissionPackage:
    target_id: str
    service: str
    fasta_text: str
    manifest: list[dict]
    n_designs: int


def package_wetlab_submission(
    designs: "list[DesignRow]", plan: "SamplingPlan", service: str = "adaptyv"
) -> SubmissionPackage:
    if service not in VALID_SERVICES:
        raise ValueError(f"unknown service: {service!r}; expected one of {VALID_SERVICES}")
    by_id = {d["design_id"]: d for d in designs}
    sampled_by = {i: "top" for i in plan.top_ids}
    sampled_by.update({i: "random" for i in plan.random_ids})

    fasta_lines: list[str] = []
    manifest: list[dict] = []
    for did in plan.all_ids:
        d = by_id[did]
        fasta_lines.append(f">{did}\n{d['sequence']}")
        manifest.append(
            {
                "design_id": did,
                "target_id": d["target_id"],
                "sequence": d["sequence"],
                "sampled_by": sampled_by[did],
                "metric_blind_sampled": True,
            }
        )
    return SubmissionPackage(
        target_id=plan.target_id,
        service=service,
        fasta_text="\n".join(fasta_lines) + "\n",
        manifest=manifest,
        n_designs=len(manifest),
    )


def write_submission(pkg: SubmissionPackage, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    fasta_path = os.path.join(out_dir, f"{pkg.target_id}_{pkg.service}.fasta")
    manifest_path = os.path.join(out_dir, f"{pkg.target_id}_{pkg.service}_manifest.csv")
    with open(fasta_path, "w") as fh:
        fh.write(pkg.fasta_text)
    with open(manifest_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(pkg.manifest)
    return {"fasta": fasta_path, "manifest": manifest_path}
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_wetlab_submission.py -v
```
- [ ] Commit:
```
git add data/wetlab_submission.py data/tests/test_wetlab_submission.py
git commit -m "data: wet-lab submission packaging (FASTA + provenance manifest) for Adaptyv/prof-LOI

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 37 — Protocol: ingest returned binding results into REAL `LabelRow`s

Returned lab results become REAL labels. A design with no returned result is **dropped**, never assumed negative. `binds` derives from a measurable KD in the returned assay row (the lab's measured readout, not an in-silico shortcut), conditioned on a returned record existing.

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/ingest_outcomes.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_ingest_outcomes.py`

- [ ] Write the FAILING test `data/tests/test_ingest_outcomes.py`:
```python
from __future__ import annotations

import csv
import json

from data.ingest_outcomes import (
    ingest_binding_results,
    parse_binding_results,
    write_label_rows,
)

MANIFEST_FIELDS = ["design_id", "target_id", "sequence", "sampled_by", "metric_blind_sampled"]


def _write_manifest(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _write_results(path, rows):
    fields = ["design_id", "kd_nm", "binding_strength", "expressed"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_binds_is_true_iff_measurable_kd(tmp_path):
    manifest = tmp_path / "m.csv"
    results = tmp_path / "r.csv"
    _write_manifest(manifest, [
        {"design_id": "d1", "target_id": "T1", "sequence": "MAAA", "sampled_by": "top", "metric_blind_sampled": "True"},
        {"design_id": "d2", "target_id": "T1", "sequence": "MBBB", "sampled_by": "random", "metric_blind_sampled": "True"},
        {"design_id": "d3", "target_id": "T1", "sequence": "MCCC", "sampled_by": "random", "metric_blind_sampled": "True"},
    ])
    _write_results(results, [
        {"design_id": "d1", "kd_nm": "8.5", "binding_strength": "Strong", "expressed": "1"},
        {"design_id": "d2", "kd_nm": "none", "binding_strength": "", "expressed": "1"},  # honest negative
        # d3 never returned by lab
    ])
    labels = ingest_binding_results(
        str(results), str(manifest),
        source="adaptyv_round_2026_06", license="CC-BY-4.0", provenance="adaptyv_service",
    )
    by_id = {r["design_id"]: r for r in labels}
    assert set(by_id) == {"d1", "d2"}              # d3 (no result) dropped, not assumed negative
    assert by_id["d1"]["binds"] is True and by_id["d1"]["kd_nm"] == 8.5
    assert by_id["d2"]["binds"] is False and by_id["d2"]["kd_nm"] is None   # honest negative
    assert by_id["d1"]["expressed"] is True
    assert all(r["metric_blind_sampled"] is True for r in labels)
    assert all(r["source"] == "adaptyv_round_2026_06" for r in labels)
    assert all(r["license"] == "CC-BY-4.0" for r in labels)


def test_parse_binding_results_reads_rows(tmp_path):
    results = tmp_path / "r.csv"
    _write_results(results, [{"design_id": "d1", "kd_nm": "1.0", "binding_strength": "Weak", "expressed": "0"}])
    rows = parse_binding_results(str(results))
    assert rows[0]["design_id"] == "d1"


def test_write_label_rows_emits_ndjson(tmp_path):
    out = tmp_path / "labels.ndjson"
    labels = [{"design_id": "d1", "binds": True, "kd_nm": 8.5}]
    write_label_rows(labels, str(out))
    lines = out.read_text().strip().splitlines()
    assert json.loads(lines[0])["design_id"] == "d1"
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.ingest_outcomes'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_ingest_outcomes.py -v
```
- [ ] Minimal implementation `data/ingest_outcomes.py`:
```python
from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pc_contracts.core import LabelRow

_NULLISH = ("", "none", "n/a", "na", "null")
_TRUTHY = ("1", "true", "yes", "y", "t")


def parse_binding_results(results_path: str) -> list[dict]:
    with open(results_path) as fh:
        return list(csv.DictReader(fh))


def _to_float(value):
    if value is None or str(value).strip().lower() in _NULLISH:
        return None
    return float(value)


def _to_bool(value):
    if value is None or str(value).strip().lower() in _NULLISH:
        return None
    return str(value).strip().lower() in _TRUTHY


def ingest_binding_results(
    results_path: str,
    submission_manifest_path: str,
    source: str,
    license: str,
    provenance: str,
) -> "list[LabelRow]":
    results = {r["design_id"]: r for r in parse_binding_results(results_path)}
    labels: list = []
    with open(submission_manifest_path) as fh:
        for m in csv.DictReader(fh):
            did = m["design_id"]
            r = results.get(did)
            if r is None:
                continue  # not returned by the lab -> NOT an assumed negative
            kd_nm = _to_float(r.get("kd_nm"))
            labels.append(
                {
                    "design_id": did,
                    "target_id": m["target_id"],
                    "sequence": m["sequence"],
                    # REAL label: binder iff the lab measured a KD for this design.
                    "binds": kd_nm is not None,
                    "binding_strength": (r.get("binding_strength") or None),
                    "kd_nm": kd_nm,
                    "expressed": _to_bool(r.get("expressed")),
                    "source": source,
                    "license": license,
                    "provenance": provenance,
                    "metric_blind_sampled": _to_bool(m.get("metric_blind_sampled")) or False,
                }
            )
    return labels


def write_label_rows(labels: "list[LabelRow]", out_path: str) -> str:
    with open(out_path, "w") as fh:
        for row in labels:
            fh.write(json.dumps(row) + "\n")
    return out_path
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_ingest_outcomes.py -v
```
- [ ] Commit:
```
git add data/ingest_outcomes.py data/tests/test_ingest_outcomes.py
git commit -m "data: ingest returned wet-lab results into REAL LabelRows + NDJSON handoff

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 38 — Protocol: selection-bias diagnostics (was_tested-AUC + range-restriction)

**Files:**
- Create: `/Users/harsha/Desktop/claudeprojects/mosaic/data/selection_diagnostics.py`
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_selection_diagnostics.py`

- [ ] Write the FAILING test `data/tests/test_selection_diagnostics.py`:
```python
from __future__ import annotations

import pytest

from data.selection_diagnostics import (
    RangeRestrictionDiagnostic,
    WasTestedDiagnostic,
    range_restriction,
    was_tested_auc,
)


def _design(i: int, score: float) -> dict:
    return {
        "design_id": f"d{i}",
        "target_id": "T1",
        "sequence": "M",
        "metrics": {"boltz2_min_ipsae": score},
    }


def test_score_selected_testing_flags_bias():
    # tested set = the top scorers -> the metric perfectly predicts was_tested
    designs = [_design(i, float(i)) for i in range(20)]
    tested = {f"d{i}" for i in range(15, 20)}
    diag = was_tested_auc(designs, tested, bias_threshold=0.65)
    assert isinstance(diag, WasTestedDiagnostic)
    assert diag.n_tested == 5 and diag.n_untested == 15
    assert diag.auc > 0.9 and diag.biased is True


def test_metric_blind_testing_is_unbiased():
    designs = [_design(i, float(i)) for i in range(20)]
    tested = {"d0", "d5", "d10", "d15", "d19"}
    diag = was_tested_auc(designs, tested, bias_threshold=0.65)
    assert diag.biased is False


def test_range_restriction_detects_clustered_tested_scores():
    designs = [_design(i, float(i)) for i in range(20)]
    tested = {f"d{i}" for i in range(16, 20)}  # narrow high band
    diag = range_restriction(designs, tested, ratio_threshold=0.5)
    assert isinstance(diag, RangeRestrictionDiagnostic)
    assert diag.tested_std < diag.pool_std
    assert diag.restricted is True


def test_range_restriction_passes_for_spread_tested_scores():
    designs = [_design(i, float(i)) for i in range(20)]
    tested = {"d0", "d6", "d12", "d19"}
    diag = range_restriction(designs, tested, ratio_threshold=0.5)
    assert diag.restricted is False


def test_diagnostics_reject_experimental_columns():
    designs = [_design(0, 1.0)]
    with pytest.raises(ValueError):
        was_tested_auc(designs, {"d0"}, score_metric="experimental__kd")
    with pytest.raises(ValueError):
        range_restriction(designs, {"d0"}, score_metric="experimental__kd")


def test_was_tested_auc_requires_both_classes():
    designs = [_design(i, float(i)) for i in range(5)]
    with pytest.raises(ValueError):
        was_tested_auc(designs, set())  # nothing tested
```
- [ ] Run it — expect **FAIL** (`ModuleNotFoundError: No module named 'data.selection_diagnostics'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_selection_diagnostics.py -v
```
- [ ] Minimal implementation `data/selection_diagnostics.py`:
```python
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sklearn.metrics import roc_auc_score

if TYPE_CHECKING:
    from pc_contracts.core import DesignRow

EXPERIMENTAL_PREFIX = "experimental__"


def _guard_metric(score_metric: str) -> None:
    if score_metric.startswith(EXPERIMENTAL_PREFIX):
        raise ValueError(
            f"selection diagnostic must use a computational metric, got {score_metric!r}"
        )


def _scored(designs: "list[DesignRow]", score_metric: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for d in designs:
        v = d["metrics"].get(score_metric)
        if v is not None:
            out.append((d["design_id"], float(v)))
    return out


@dataclass
class WasTestedDiagnostic:
    score_metric: str
    auc: float
    n_tested: int
    n_untested: int
    biased: bool


def was_tested_auc(
    designs: "list[DesignRow]",
    tested_ids: set[str],
    score_metric: str = "boltz2_min_ipsae",
    bias_threshold: float = 0.65,
) -> WasTestedDiagnostic:
    """AUC of the score predicting whether a design was tested.

    High AUC => testing was score-driven (selection bias); ~0.5 => metric-blind.
    """
    _guard_metric(score_metric)
    scored = _scored(designs, score_metric)
    y = [1 if did in tested_ids else 0 for did, _ in scored]
    xs = [x for _, x in scored]
    n_tested = sum(y)
    n_untested = len(y) - n_tested
    if n_tested == 0 or n_untested == 0:
        raise ValueError("need both tested and untested designs with a non-null score")
    auc = max(roc_auc_score(y, xs), roc_auc_score(y, [-x for x in xs]))
    return WasTestedDiagnostic(score_metric, auc, n_tested, n_untested, auc >= bias_threshold)


@dataclass
class RangeRestrictionDiagnostic:
    score_metric: str
    tested_std: float
    pool_std: float
    variance_ratio: float
    restricted: bool


def range_restriction(
    designs: "list[DesignRow]",
    tested_ids: set[str],
    score_metric: str = "boltz2_min_ipsae",
    ratio_threshold: float = 0.5,
) -> RangeRestrictionDiagnostic:
    """Compare score spread of tested designs vs the full pool.

    tested_std/pool_std below ratio_threshold => the labeled set is range-restricted.
    """
    _guard_metric(score_metric)
    scored = _scored(designs, score_metric)
    pool = [x for _, x in scored]
    tested = [x for did, x in scored if did in tested_ids]
    if len(pool) < 2 or len(tested) < 2:
        raise ValueError("need >=2 scored designs in pool and tested set")
    pool_std = statistics.pstdev(pool)
    tested_std = statistics.pstdev(tested)
    ratio = tested_std / pool_std if pool_std > 0 else 0.0
    return RangeRestrictionDiagnostic(
        score_metric, tested_std, pool_std, ratio, ratio < ratio_threshold
    )
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_selection_diagnostics.py -v
```
- [ ] Commit:
```
git add data/selection_diagnostics.py data/tests/test_selection_diagnostics.py
git commit -m "data: was_tested-AUC + range-restriction selection-bias diagnostics (experimental cols banned)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 39 — Protocol: end-to-end roundtrip smoke test (select → sample → package → ingest → diagnose)

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_metric_blind.py`

- [ ] Append the FAILING integration test to `data/tests/test_metric_blind.py` (exercises the whole protocol wired together; no new source needed):
```python
def test_full_protocol_roundtrip(tmp_path):
    from data.target_selection import select_gap_filling_targets
    from data.wetlab_submission import package_wetlab_submission, write_submission
    from data.ingest_outcomes import ingest_binding_results
    from data.selection_diagnostics import was_tested_auc

    # 1. select a gap-filling target (only ligand_present missing)
    existing = [{"target_id": f"h{i}", "interface_class": "helical"} for i in range(3)] \
        + [{"target_id": f"s{i}", "interface_class": "sheet_flat"} for i in range(3)] \
        + [{"target_id": f"m{i}", "interface_class": "mixed"} for i in range(3)]
    candidates = [{"target_id": "LIG1", "interface_class": "ligand_present"}]
    picked = select_gap_filling_targets(existing, candidates, min_per_class=3)
    assert [t["target_id"] for t in picked] == ["LIG1"]

    # 2. metric-blind sample a campaign for LIG1
    designs = [_design(i, float(i), target="LIG1") for i in range(30)]
    plan = metric_blind_sample(designs, n_top=6, n_random=6, seed=1)

    # 3. package + write submission
    pkg = package_wetlab_submission(designs, plan, service="adaptyv")
    paths = write_submission(pkg, str(tmp_path))

    # 4. simulate lab returning KD only for top designs, ingest as REAL labels
    import csv
    results = tmp_path / "results.csv"
    with open(results, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["design_id", "kd_nm", "binding_strength", "expressed"])
        w.writeheader()
        for did in plan.all_ids:
            kd = "5.0" if did in plan.top_ids else "none"
            w.writerow({"design_id": did, "kd_nm": kd, "binding_strength": "", "expressed": "1"})
    labels = ingest_binding_results(
        str(results), paths["manifest"],
        source="sim", license="internal", provenance="smoke",
    )
    assert len(labels) == len(plan.all_ids)
    assert sum(1 for r in labels if r["binds"]) == len(plan.top_ids)

    # 5. diagnostic over the campaign: tested == everyone we submitted
    diag = was_tested_auc(designs, set(plan.all_ids))
    assert diag.n_tested == len(plan.all_ids)
```
- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_metric_blind.py::test_full_protocol_roundtrip -v
```
- [ ] Run the FULL suite (both packages) — expect **ALL PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest pc_contracts/tests data/tests -v
```
- [ ] Commit:
```
git add data/tests/test_metric_blind.py
git commit -m "data: end-to-end new-label protocol roundtrip (select->sample->package->ingest->diagnose)

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Task 40 — `was_tested` propensity instrumentation for downstream IPW (AUDIT-F)

Labeled designs reached the wet lab partly because they scored well computationally (selection bias / MNAR range-restriction). Without correction the headline delta (LLM prior vs baseline) is evaluated on a non-random sample of the score distribution, which overstates performance on high-scoring designs and understates it on low scorers. This task emits the fields the downstream eval harness needs to fit an inverse-propensity-weighting (IPW) corrector.

**Files:**
- Edit: `/Users/harsha/Desktop/claudeprojects/mosaic/data/selection_diagnostics.py` (add `PropensityRecord`, `emit_propensity_fields`)
- Test: `/Users/harsha/Desktop/claudeprojects/mosaic/data/tests/test_was_tested_propensity.py`

- [ ] Write the FAILING test `data/tests/test_was_tested_propensity.py`:
```python
from __future__ import annotations

from dataclasses import fields

from data.selection_diagnostics import PropensityRecord, emit_propensity_fields
from pc_contracts.core import CANONICAL_METRIC_KEY


def _design(i: int, score: float, tested: bool) -> dict:
    return {
        "design_id": f"d{i}",
        "target_id": "T1",
        "sequence": "M" * 11,
        "metrics": {CANONICAL_METRIC_KEY: score},
        "_was_tested": tested,
    }


def test_propensity_record_has_required_fields():
    field_names = {f.name for f in fields(PropensityRecord)}
    required = {"design_id", "target_id", "was_tested", "computational_score", "score_metric"}
    assert required.issubset(field_names), (
        f"PropensityRecord missing fields: {required - field_names}"
    )


def test_emit_propensity_fields_sets_was_tested_correctly():
    designs = [
        _design(0, 0.9, True),
        _design(1, 0.3, False),
        _design(2, 0.7, True),
    ]
    records = emit_propensity_fields(designs, score_metric=CANONICAL_METRIC_KEY)
    assert len(records) == 3
    by_id = {r.design_id: r for r in records}
    assert by_id["d0"].was_tested is True
    assert by_id["d1"].was_tested is False
    assert by_id["d0"].computational_score == 0.9
    assert by_id["d0"].score_metric == CANONICAL_METRIC_KEY


def test_emit_propensity_rejects_experimental_score_metric():
    import pytest
    designs = [_design(0, 0.9, True)]
    with pytest.raises(ValueError, match="computational"):
        emit_propensity_fields(designs, score_metric="experimental__kd")


def test_emit_propensity_handles_nan_score():
    import math
    designs = [_design(0, float("nan"), False)]
    records = emit_propensity_fields(designs, score_metric=CANONICAL_METRIC_KEY)
    assert math.isnan(records[0].computational_score)


def test_propensity_records_are_ipw_ready():
    """Smoke: the fields needed for sklearn LogisticRegression(IPW) are present."""
    designs = [_design(i, float(i) / 10, i % 2 == 0) for i in range(10)]
    records = emit_propensity_fields(designs, score_metric=CANONICAL_METRIC_KEY)
    # Downstream: X = [[r.computational_score] for r in records]
    #             y = [r.was_tested for r in records]
    # -> fit LogisticRegression -> propensity scores -> IPW weights
    X = [[r.computational_score] for r in records]
    y = [r.was_tested for r in records]
    assert len(X) == 10 and len(y) == 10
    assert any(y) and not all(y)  # both classes present
```
- [ ] Run it — expect **FAIL** (`ImportError: cannot import name 'PropensityRecord'`):
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_was_tested_propensity.py -v
```
- [ ] Add to `data/selection_diagnostics.py`:
```python
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class PropensityRecord:
    """Fields emitted per design for downstream IPW-corrected evaluation.

    The downstream harness uses these to fit a propensity-of-being-tested model:
        X = [[r.computational_score] for r in records]
        y = [r.was_tested for r in records]
        model = LogisticRegression().fit(X, y)
        weights = 1.0 / model.predict_proba(X)[:, 1]   # IPW weights
    These weights correct the headline delta for score-selection bias (AUDIT-F).
    """
    design_id: str
    target_id: str
    was_tested: bool
    computational_score: float
    score_metric: str


def emit_propensity_fields(
    designs: "list[dict]",
    score_metric: str = CANONICAL_METRIC_KEY,
) -> List[PropensityRecord]:
    """Emit was_tested + computational features for each design.

    Each design dict must contain a '_was_tested' bool key (set by the caller
    based on whether the design appears in the labeled set).
    Rejects experimental metric keys to prevent leakage into the propensity model.
    """
    if score_metric.startswith(EXPERIMENTAL_PREFIX):
        raise ValueError(
            f"Propensity model must use a computational metric, not {score_metric!r}. "
            "Using an experimental feature leaks the label into the propensity weights."
        )
    records: List[PropensityRecord] = []
    for d in designs:
        score = d["metrics"].get(score_metric)
        records.append(PropensityRecord(
            design_id=d["design_id"],
            target_id=d["target_id"],
            was_tested=bool(d.get("_was_tested", False)),
            computational_score=float(score) if score is not None else float("nan"),
            score_metric=score_metric,
        ))
    return records
```

Also add `CANONICAL_METRIC_KEY` import to `data/selection_diagnostics.py`:
```python
from pc_contracts.core import CANONICAL_METRIC_KEY
```
And update `was_tested_auc`/`range_restriction` default `score_metric` args to use `CANONICAL_METRIC_KEY` (consistent with Task 10).

- [ ] Run it — expect **PASS**:
```
cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest data/tests/test_was_tested_propensity.py -v
```
- [ ] Commit:
```
git add data/selection_diagnostics.py data/tests/test_was_tested_propensity.py
git commit -m "data: PropensityRecord + emit_propensity_fields for downstream IPW-corrected eval

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Definition of Done

### (a) PIPELINE-CORRECTNESS DoD — binary done-gates (achievable now)

These are the hard pass/fail gates. The data plan is **DONE** when ALL of these hold:

- [ ] **All tests green:** `cd /Users/harsha/Desktop/claudeprojects/mosaic && pytest pc_contracts/tests data/tests -v` passes (27 test files; 40 tasks).
- [ ] **Shared contract is the single source:** `DesignRow`, `LabelRow`, `TargetFeatures`, `INTERFACE_CLASSES`, `CANONICAL_METRIC_KEY` exist ONLY in `pc_contracts/core.py`; `data/` and the future `scorer/` both import them from there (Task 1, 10; `data/targets.py` and `data/target_selection.py` re-import the taxonomy, never redefine it).
- [ ] **ETL reality honored:** raw Proteinbase is the 6-column CSV with metrics/labels nested in a JSON `evaluations` list; `flatten_proteinbase` explodes it to `type__metric` columns; `explode_proteinbase` emits `DesignRow`/`LabelRow` + a reproducible sha256 version id (Tasks 4, 8).
- [ ] **Real-label integrity (circular-label ban):** `test_circular_label_ban.py` passes — `binds` is derived ONLY from the explicit experimental `binding` boolean conditioned on `expressed`; no code path uses `kd.notna()` nor the banned hit-rule (`ipSAE>=0.70 AND DockQ>=0.23 AND pTMEnergy<=-1.2`). Field renames pinned: `binding→binds`, `kd→kd_nm` (molar→nM), `binding_strength` kept (Tasks 6, 7). `is_real_label` enforces extended SILICO_LABEL_MARKERS; `INGEST_SOURCE_ALLOWLIST` is fail-CLOSED at the ingest boundary (Task 15).
- [ ] **Leakage guard after explode:** `assert_no_leakage`/`build_feature_frame`/`assert_designs_clean` FAIL if any `experimental__*` column (known or hyphenated-unknown) reaches the feature space; the 6 known label columns (`binding, expressed, expression_yield, kd, koff, kon`) are pinned and each is shown guarded (Task 9).
- [ ] **Canonical metric key enforced:** `CANONICAL_METRIC_KEY = "computational__boltz2_min_ipsae"` is the single stored name; bare `boltz2_min_ipsae` is banned; protocol defaults use `CANONICAL_METRIC_KEY`; `test_bare_key_is_not_canonical` passes (Task 10).
- [ ] **Assay field carries through:** every `LabelRow` has an `assay` field; ingestion reads it from `experimental__assay`; downstream eval can stratify within-assay (Task 12).
- [ ] **Missingness/NMAR diagnostic exists and runs:** `missingness_diagnostic` flags divergence in binder-rate between metric-present and metric-absent labeled rows so training can be restricted (Task 11).
- [ ] **Schema separation:** `data/db/schema.sql` is idempotent; `designs`/`predictions` carry NO experimental columns; real wet-lab outcomes + provenance + license + `metric_blind_sampled` live in `experimental_outcomes`/`labels` (Task 13).
- [ ] **Curated mapping is hand-built + audited:** `CURATED_TARGETS` is hand-listed (never regex-derived); the pd-l1 `cytokine_receptor` mislabel is fixed to `sheet_flat`; every curated `interface_class` is in the four-value enum (Task 3).
- [ ] **Provenance + license discipline:** every `LabelRow` carries `source`/`license`/`provenance`/`assay`; harvest sources are gated through `SOURCE_LICENSES` (unregistered sources hard-raise); the license string is stamped deterministically, never LLM-supplied (Tasks 6, 23). Nipah rows carry a separate license tag; `build_dual_eval_panels` produces `full` and `commercial_clean` panels (Task 21).
- [ ] **Dedup source integrity:** `assert_single_source_per_target` confirms no target is double-counted across Overath/Proteinbase/BindCraft; cross-source conflicts are logged and dropped before the assert (Task 20).
- [ ] **Backfill is idempotent, resumable, cost-logged:** re-running `backfill_features` over the same manifest spends zero additional GPU; a partial run resumes; `cost_summary` makes spend auditable (Tasks 28–30).
- [ ] **Pure-negative targets routed correctly:** HSA/TNFA/GM2A/ORM2 (and any NEW all-negative target) are excluded from ranking/LOTO folds and routed to the specificity diagnostic set; `split_by_positive_coverage` uses actual label counts, not just the static allowlist (Task 34).
- [ ] **Honest negatives by construction:** the new-target protocol uses metric-blind sampling (top-k + uniform non-top), drops un-returned designs instead of assuming negatives, and provides `was_tested_auc` + `range_restriction` selection-bias diagnostics (Tasks 35, 37, 38). `emit_propensity_fields` supplies the `was_tested` indicator + computational score for downstream IPW correction (Task 40).
- [ ] **File-size hygiene:** `data/etl.py`, `data/backfill.py`, `data/harvest.py` each well under 500 lines.

### (b) DATA-COVERAGE MILESTONE — cold-start-tolerant, NOT a binary blocker on "done"

This is a **milestone target**, deliberately **not** gated as a done-criterion. The pipeline is correct and shippable in a cold-start / partial-coverage state; coverage accrues over time via the flywheel.

- [ ] **Target breadth (aspirational):** ~15–30 distinct, well-powered curated targets; ≥2–3 per interface class (`helical`, `sheet_flat`, `mixed`, `ligand_present`); each ≥10 binders **and** ≥10 non-binders. `compute_class_gaps`/`select_gap_filling_targets` drive new-label campaigns toward this, but **partial coverage does not block "done."**
- [ ] **Tiered sourcing in progress:** Tier1 (Proteinbase + audited internal real wet-lab results), Tier2 (Cao 2022 / Adaptyv rounds / PPB-Affinity / SKEMPI 2.0 / SAbDab via LLM harvest), Tier3 (feature-backfill of harvested sequences), Tier4 (NEW metric-blind wet-lab labels). Logged honestly; gaps are expected and surfaced, not hidden.
- [ ] **P0 license gates resolved before publication:** Proteinbase `LICENSE-GATE-PENDING` and each harvest-source license confirmed before any external claim/export (Phase 0). Code proceeds with marked placeholders meanwhile.

### Scorer handoff — NOTE ONLY (not part of this plan's DoD)

The modeling package (`scorer/`) consumes `explode_proteinbase` output + the master JSONL label table + backfilled `{design, label}` pairs. **The headline falsification test (LLM per-target prior vs ONE global weighting under LOTO) is a `scorer/` deliverable, NOT gated here.** When it runs, the bar the per-target prior must beat is **`min_ipSAE` recomputed within each LOTO fold** (GroupKFold by curated `target_id`), with paired-bootstrap CIs on Precision@k / Recall@budget. The retired pooled `0.806` AUC (`PROTEINBASE_POOLED_AUC_RETIRED`) is recorded as provenance ONLY and is explicitly **NOT** the LOTO bar. This data plan is complete and correct independent of any LOTO outcome.

---

# ⚠️ PRE-FLIGHT FIXES — apply DURING execution (red-team punch-list)

These are internal-consistency bugs found by adversarial review of this plan. Fix each as you reach the relevant task; do not skip.

1. **[BLOCKER] Canonical metric key — RESOLVED by Task 10.** ~~One quantity currently has three names: raw `min_ipsae` (Task 31) → `computational__boltz2_min_ipsae` (feature space, Tasks 25/27) → bare `boltz2_min_ipsae` (protocol, Tasks 35/36/38/39).~~ Task 10 adds `CANONICAL_METRIC_KEY` to `pc_contracts` and updates all protocol defaults. The test `test_bare_key_is_not_canonical` enforces this going forward. Apply fix in Task 10 before implementing Tasks 35/36/38/39.
2. **[HARD-RULE VIOLATION] Task 37 label derivation.** `ingest_binding_results` sets `"binds": kd_nm is not None` — this is the explicitly BANNED `kd.notna()` rule (DoD criteria 6/7) and creates two conflicting label definitions (ETL path uses the `binding` boolean; ingest path uses KD presence). **Derive `binds` from an explicit returned `binding`/`binds` boolean column.** Rename the test off `test_binds_is_true_iff_measurable_kd`.
3. **[selection-bias trap] Task 37 must gate on `expressed`.** A returned design with `expressed=0, kd=none` is currently labeled `binds=False` (a fake "honest negative") — expression failure ≠ non-binding. **Drop non-expressing designs from label generation** rather than calling them negatives. Add an `expressed=0` test.
4. **[composition gap] Task 30↔31 seam.** `backfill_features` expects `run_panel_fn: Callable[[LabelRow], PanelResult]` but `run_panel_via_nebius` has 3 required args. **Add an explicit adapter + test:** `run_panel_fn = lambda lbl: run_panel_via_nebius(lbl, runner, cif_for(lbl))`, with per-label `target_cif` selection (Task 31 currently ignores `label.target_id`).
5. **[cost is $0] Task 31.** The nebius H100 runner emits wallclock, not dollars, so `result.get("cost_usd", 0.0)` defaults to 0 and the "cost-logged" DoD passes while logging zero spend. **Compute cost as `wallclock_sec × $/hr` in the wrapper and test it.**
6. **[TDD form] Task 29.** Ensure `cost_summary` has an explicit RED (failing-test) step before GREEN, like every other task.
7. **[casing] Rule table.** Code uses lowercase `min_ipsae`/`boltz2_min_ipsae`; DoD prose uses `min_ipSAE`/`ipSAE`/`DockQ`/`pTMEnergy`. Pin ONE casing so the Proteinbase flatten and protocol consumers agree.
