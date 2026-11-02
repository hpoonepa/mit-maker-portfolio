"""llm_prior.py — LLM-per-target SIGNED importance prior over binder metrics.

The meta-scorer's differentiator: an LLM reads a target's structural features +
literature and outputs WHICH design metrics matter for THIS target and a SIGNED
weight for each (positive = higher is better, negative = higher is worse). Signed
weights are mandatory — the Orbion "flip direction" finding shows a feature can
help one target and hurt another (e.g. aggregation/immunogenicity).

Stdlib-only (json / urllib / math / pathlib / dataclasses), matching the style of
``literature.py``. NO third-party deps, NO SDK. Importing this module never makes
a network call; only ``AnthropicClient.complete`` / ``main`` do.

Tests drive everything through the fake ``RecordedClient`` — no live API calls.
"""

from __future__ import annotations

import csv
import json
import math
import os
import urllib.request
from dataclasses import dataclass, field

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, ".."))


# ---------------------------------------------------------------------------
# Menu — the only metric keys a weight may reference.
# ---------------------------------------------------------------------------
MENU_FEATURE_KEYS: tuple[str, ...] = (
    # Structural design metrics
    "computational__boltz2_min_ipsae",
    "computational__boltz2_iptm",
    "computational__boltz2_lis",
    "computational__actifptm",
    "computational__interface_residues",
    "computational__boltz2_complex_iplddt",
    "computational__proteinmpnn_score",
    "computational__esmfold_plddt",
    "best_ipsae",
    "shape_complementarity",
    "rmsd_binder",
    # Sequence metrics
    "seq_length",
    "isoelectric_point",
    "cysteine_fraction",
    "hydrophobic_fraction",
    "aromatic_fraction",
    "net_charge_ph7",
    # Biology menu (Orbion [seq] features — see scorer/biology_features.py)
    "bio__aggregation_propensity",
    "bio__ptm_site_density",
    "bio__phospho_site_density",
    "bio__disulfide_potential",
    "bio__disorder_fraction",
    "bio__topology_helix_frac",
    "bio__topology_strand_frac",
    "bio__topology_loop_frac",
    "bio__immunogenicity_proxy",
)

_MENU_SET = frozenset(MENU_FEATURE_KEYS)


# ---------------------------------------------------------------------------
# Prior — the per-target object the scorer consumes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Prior:
    """A literature-informed, signed, per-target importance prior."""

    weights: dict[str, float]
    failure_penalties: dict[str, dict] = field(default_factory=dict)
    epitope_residues: list[int] = field(default_factory=list)
    liabilities: list[str] = field(default_factory=list)
    proposed_features: list[dict] = field(default_factory=list)
    rationale: str = ""
    citations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation / normalization
# ---------------------------------------------------------------------------
def _validate_and_normalize(weights: dict[str, float]) -> dict[str, float]:
    """Validate a signed weight dict and L1-normalize on |w| preserving sign.

    - Every key must be in ``MENU_FEATURE_KEYS`` (else ValueError).
    - Every value must be finite (else ValueError). Negatives ARE allowed.
    - Entries with weight exactly 0.0 are dropped.
    - Divide every weight by ``sum(|w|)`` so ``sum(|w|) == 1.0`` (sign kept).
    - Empty / all-zero -> ValueError.
    """
    cleaned: dict[str, float] = {}
    for k, v in weights.items():
        if k not in _MENU_SET:
            raise ValueError(f"unknown metric key: {k}")
        fv = float(v)
        if not math.isfinite(fv):
            raise ValueError(f"non-finite weight for {k}: {v}")
        if fv == 0.0:
            continue
        cleaned[k] = fv

    total = sum(abs(w) for w in cleaned.values())
    if total == 0.0:
        raise ValueError("empty or all-zero weights")
    return {k: w / total for k, w in cleaned.items()}


def _coerce_int_list(values) -> list[int]:
    out: list[int] = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _prior_from_dict(spec: dict) -> Prior:
    """Build a validated ``Prior`` from a raw dict (LLM payload or JSON file)."""
    return Prior(
        weights=_validate_and_normalize(spec.get("weights", {}) or {}),
        failure_penalties=dict(spec.get("failure_penalties", {}) or {}),
        epitope_residues=_coerce_int_list(spec.get("epitope_residues", [])),
        liabilities=list(spec.get("liabilities", []) or []),
        proposed_features=list(spec.get("proposed_features", []) or []),
        rationale=spec.get("rationale", "") or "",
        citations=list(spec.get("citations", []) or []),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def load_priors(path: str) -> dict[str, Prior]:
    """Load ``{target: prior_spec}`` JSON into ``{target: Prior}``.

    Each ``weights`` block is validated + normalized; missing optional fields
    default to empty. Propagates ValueError on a bad weight key.
    """
    with open(path) as fh:
        raw = json.load(fh)
    return {target: _prior_from_dict(spec) for target, spec in raw.items()}


# ---------------------------------------------------------------------------
# Prompt building (pure — no I/O)
# ---------------------------------------------------------------------------
_FEATURE_FIELDS = (
    "log_length",
    "disorder_fraction",
    "frac_helix",
    "frac_strand",
    "frac_loop",
    "pocket_volume",
    "druggability",
    "epitope_hydrophobicity",
    "epitope_net_charge",
    "frac_polar",
    "interface_class",
)

_POWER_TABLE_HEADER = (
    "EMPIRICAL METRIC DISCRIMINATIVE POWER (measured within-target on held-out "
    "data — higher power = better at separating real binders from non-binders; "
    "this is GROUND TRUTH from data, trust it over intuition):"
)

_INSTRUCTIONS = (
    "From the literature, identify the known epitope residues, binding "
    "liabilities, and failure modes for binders to this target. Then output "
    "JSON ONLY (no prose) with keys: "
    '`weights` (object mapping a SUBSET of the listed metrics to a SIGNED '
    "float — positive = higher value is better for binding success, negative "
    "= higher value is worse; assign negative weights where the literature "
    "says the feature hurts, e.g. aggregation/immunogenicity), "
    "`failure_penalties`, `epitope_residues` (integer PDB residue numbers), "
    "`liabilities` (strings), `proposed_features` (each "
    '{"name":..., "computable":"computable_now"|"needs_structure"}), '
    "`rationale`, `citations` (PMID strings). NEVER reference experimental "
    "binding labels or outcomes — you are setting a prior from literature + "
    "structure only.\n"
    "\n"
    "WEIGHTING RULES (the empirical power table above is the default ranking):\n"
    "- CONCENTRATE weight on the highest-power metrics. It is correct and "
    "expected to place the majority of total weight on the top 3-4 metrics. "
    "Metrics with power < ~0.15 are essentially noise — do NOT assign them "
    "weight unless the literature gives a specific, strong, target-particular "
    "reason.\n"
    "- Select AT MOST 12 metrics total (fewer is better). Do not spread weight "
    "thinly across all metrics — a diffuse prior is a FAILED prior.\n"
    "- Use the literature to decide WHERE THIS TARGET DEVIATES from the generic "
    "ranking — e.g. an architecture that makes a normally-weak metric matter, a "
    "known liability that warrants a negative weight, or a hotspot/epitope a "
    "structural metric should capture. The default is to FOLLOW the empirical "
    "power ranking; deviate only with a reason you can state in `rationale`.\n"
    "- Respect direction: the power table states higher=better vs lower=better; "
    "encode it in the SIGN of your weight (positive = higher is better, "
    "negative = higher is worse)."
)


def build_prior_prompt(
    target: str,
    target_features_row: dict,
    literature: dict,
    available_metrics,
    metric_power_table: str = "",
) -> str:
    """Build the LLM prompt (pure string; defensive about missing keys).

    ``metric_power_table`` is the ``format_power_table`` output (measured
    TRAIN-ONLY, leave-this-target-out — see ``main``). When non-empty it is
    injected as a labeled GROUND-TRUTH section the LLM is told to trust over
    intuition and to concentrate weight on.
    """
    lines: list[str] = []
    lines.append(f"TARGET: {target}")
    lines.append("")
    lines.append("STRUCTURAL FEATURES:")
    row = target_features_row or {}
    for f in _FEATURE_FIELDS:
        if f in row:
            lines.append(f"  - {f}: {row[f]}")

    lines.append("")
    lines.append("LITERATURE — ABSTRACTS:")
    abstracts = (literature or {}).get("abstracts") or []
    if abstracts:
        for ab in abstracts:
            if not isinstance(ab, dict):
                continue
            pmid = ab.get("pmid", "")
            title = ab.get("title", "")
            text = ab.get("abstract", "")
            lines.append(f"  - [PMID {pmid}] {title}")
            if text:
                lines.append(f"    {text}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("LITERATURE — OPEN TARGETS FACTS:")
    open_targets = (literature or {}).get("open_targets") or {}
    if open_targets:
        for k, v in open_targets.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(
        "MENU OF WEIGHTABLE METRICS — select WHICH of these matter for THIS "
        "target and assign each a SIGNED weight:"
    )
    for key in available_metrics:
        lines.append(f"  - {key}")

    table = (metric_power_table or "").strip()
    if table:
        lines.append("")
        lines.append(_POWER_TABLE_HEADER)
        lines.append(table)

    lines.append("")
    lines.append("INSTRUCTIONS:")
    lines.append(_INSTRUCTIONS)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _strip_code_fence(text: str) -> str:
    """Strip a surrounding ```json ... ``` (or ``` ... ```) fence if present."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    # Drop the opening fence line (``` or ```json).
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # Drop a trailing fence line.
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def generate_prior(
    target: str,
    target_features_row: dict,
    literature: dict,
    available_metrics,
    client,
    metric_power_table: str = "",
) -> Prior:
    """Build the prompt, call the client, parse + validate into a ``Prior``.

    ``metric_power_table`` is threaded into the prompt (TRAIN-ONLY power table,
    leave-this-target-out — set by the caller).
    """
    prompt = build_prior_prompt(
        target, target_features_row, literature, available_metrics,
        metric_power_table=metric_power_table,
    )
    raw = client.complete(prompt)
    spec = _parse_json_object(raw, target)
    return _prior_from_dict(spec)


def _parse_json_object(raw: str, target: str) -> dict:
    """Parse a JSON object from an LLM response tolerant of prose/fences.

    Strips a surrounding code fence, then tries a direct parse. If that fails,
    extracts the outermost object span (first ``{`` .. last ``}``) and parses
    that — handling prose before/after the JSON. Raises ValueError if no
    ``{...}`` span exists or it still won't parse.
    """
    payload = _strip_code_fence(raw)
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        pass

    start = payload.find("{")
    end = payload.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(payload[start : end + 1])
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"could not parse JSON object from LLM response for "
                f"{target}: {exc}"
            ) from exc
    raise ValueError(f"no JSON object found in LLM response for {target}")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
class RecordedClient:
    """Fake client returning canned responses. Used by ALL tests — no network.

    Pops responses in order; once exhausted, repeats the last response.
    """

    def __init__(self, responses):
        if isinstance(responses, str):
            responses = [responses]
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise RuntimeError("RecordedClient ran out of responses")
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class AnthropicClient:
    """Real client (stdlib urllib only). NEVER invoked by tests."""

    _URL = "https://api.anthropic.com/v1/messages"
    _MODEL = "claude-opus-4-6"
    _TIMEOUT = 120

    def __init__(self, model: str | None = None):
        self._model = model or self._MODEL

    @staticmethod
    def _load_api_key() -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
        env_path = os.path.join(_REPO_ROOT, ".env")
        if os.path.exists(env_path):
            with open(env_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        raise RuntimeError(
            "ANTHROPIC_API_KEY not found in environment or .env at repo root"
        )

    def complete(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self._URL,
            data=body,
            headers={
                "x-api-key": self._load_api_key(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self._TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data["content"][0]["text"]


# ---------------------------------------------------------------------------
# CLI (do NOT run in tests — guarded behind __main__)
# ---------------------------------------------------------------------------
_TARGET_FEATURES_CSV = os.path.join(
    _REPO_ROOT, "data", "processed", "target_features.csv"
)
_LABELED_FEATURES_CSV = os.path.join(
    _REPO_ROOT, "data", "processed", "labeled_features_bio.csv"
)
_LITERATURE_DIR = os.path.join(_REPO_ROOT, "data", "processed", "literature")
_OUTPUT_PATH = os.path.join(_REPO_ROOT, "data", "processed", "llm_priors.json")


def _load_target_rows(path: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            rows[row["target"]] = row
    return rows


def _write_priors(priors: dict[str, dict]) -> None:
    with open(_OUTPUT_PATH, "w") as fh:
        json.dump(priors, fh, indent=2)


def main() -> None:
    # Imported here (not at module top) so importing this module stays I/O-free
    # and dependency-light; main() is the only place these are needed.
    from scorer.data_loader import load_designs
    from scorer.metric_power import (
        discriminative_power,
        format_power_table,
        within_target_auc,
    )

    target_rows = _load_target_rows(_TARGET_FEATURES_CSV)
    # Load the full labeled design set ONCE; we re-derive a leave-T-out slice
    # per fold below so no target ever sees its own labels in its power table.
    designs = load_designs(_LABELED_FEATURES_CSV)
    # Model override via LLM_PRIOR_MODEL (default = AnthropicClient._MODEL).
    client = AnthropicClient(model=os.environ.get("LLM_PRIOR_MODEL") or None)
    priors: dict[str, dict] = {}
    skipped: list[str] = []

    for target, row in target_rows.items():
        lit_path = os.path.join(_LITERATURE_DIR, f"{target}.json")
        if not os.path.exists(lit_path):
            print(f"WARNING: no literature cache for {target}; skipping.")
            skipped.append(target)
            continue
        with open(lit_path) as fh:
            literature = json.load(fh)

        # LEAKAGE-SAFE per fold: compute the discriminative-power table on
        # TRAIN ONLY (every design whose target != T). T's own labels never
        # enter the table, so the prior for T is built blind to T's outcomes.
        train = [d for d in designs if d.get("target", "").upper() != target.upper()]
        wa = within_target_auc(train)
        dp = discriminative_power(train)
        table = format_power_table(wa, dp)

        # Per-target isolation: a bad response on one target must NOT discard
        # the priors already paid for. Catch broadly, skip, keep going.
        try:
            prior = generate_prior(
                target, row, literature, MENU_FEATURE_KEYS, client,
                metric_power_table=table,
            )
        except Exception as exc:  # noqa: BLE001 — cost protection: never crash
            print(f"WARNING: failed to generate prior for {target}: "
                  f"{type(exc).__name__}: {exc}; skipping.")
            skipped.append(target)
            continue

        priors[target] = {
            "weights": prior.weights,
            "failure_penalties": prior.failure_penalties,
            "epitope_residues": prior.epitope_residues,
            "liabilities": prior.liabilities,
            "proposed_features": prior.proposed_features,
            "rationale": prior.rationale,
            "citations": prior.citations,
        }
        # Incremental write: a crash mid-batch still leaves a valid partial file.
        _write_priors(priors)

        # Print signed weights + count so concentration is visible at a glance
        # (expect <=12 metrics, top weight on actifptm/interface_residues/ipsae).
        signed = ", ".join(
            f"{k}{'+' if w >= 0 else ''}{w:.3f}"
            for k, w in sorted(prior.weights.items(),
                               key=lambda kv: abs(kv[1]), reverse=True)
        )
        print(f"\n=== {target} ===")
        print(f"  weighted {len(prior.weights)} metrics (<=12 expected): {signed}")
        print(f"  epitope_residues: {prior.epitope_residues}")
        print(f"  liabilities: {prior.liabilities}")
        print(f"  proposed_features: {prior.proposed_features}")
        print(f"  citations: {prior.citations}")

    _write_priors(priors)
    print(f"\nWrote {len(priors)} priors -> {_OUTPUT_PATH}")
    print(f"Summary: {len(priors)} succeeded, {len(skipped)} skipped"
          + (f" ({', '.join(skipped)})" if skipped else ""))


if __name__ == "__main__":
    main()
