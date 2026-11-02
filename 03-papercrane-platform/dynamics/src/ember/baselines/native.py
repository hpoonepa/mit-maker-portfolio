"""Native static baselines from cached outputs, independent of R0 and BioEmu."""

from __future__ import annotations

from ..candidates import ranked_unique
from ..io import content_hash
from ..schema import Observation, Prediction, RankedSite, Target, require_indices, unique_ids
from .p2rank import P2RankSite


def fpocket_apo_prediction(
    target: Target,
    observations: list[Observation],
    *,
    method_sha256: str,
    top_k: int = 5,
    runtime_seconds: float | None = None,
    cost_usd: float | None = None,
) -> Prediction:
    if any(o.source != "apo" for o in observations) or len({o.frame_id for o in observations}) > 1:
        raise ValueError("Native fpocket baseline accepts one apo frame only")
    unique_ids(observations, "observation_id")
    for observation in observations:
        require_indices(observation.residues, "baseline pocket residues", len(target.sequence))
    ranked = [
        RankedSite(o.observation_id, o.residues, o.detector_score, "apo", o.observation_id, o.structure_path)
        for o in observations
    ]
    selected = ranked_unique(ranked, top_k=top_k)
    return Prediction(
        target.target_id,
        "fpocket-apo",
        "ok" if selected else "no_candidates",
        tuple(selected),
        content_hash(target),
        method_sha256,
        runtime_seconds=runtime_seconds,
        cost_usd=cost_usd,
    )


def p2rank_apo_prediction(
    target: Target,
    sites: list[P2RankSite],
    *,
    method_sha256: str,
    top_k: int = 5,
    runtime_seconds: float | None = None,
    cost_usd: float | None = None,
) -> Prediction:
    for site in sites:
        require_indices(site.residues, "baseline pocket residues", len(target.sequence))
    # Preserve authors' ranking exactly, including ties in score. Raw detector
    # scores/probabilities are retained in the original CSV, never recalibrated.
    ranked = [RankedSite(site.name, site.residues, -float(site.rank), "apo") for site in sites]
    selected = ranked_unique(ranked, top_k=top_k)
    return Prediction(
        target.target_id,
        "p2rank-apo",
        "ok" if selected else "no_candidates",
        tuple(selected),
        content_hash(target),
        method_sha256,
        runtime_seconds=runtime_seconds,
        cost_usd=cost_usd,
        warnings=("Ranking score is negative native rank; raw detector values remain in the source CSV.",),
    )
