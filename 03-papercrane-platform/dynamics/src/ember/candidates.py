"""Deterministic bounded-diameter site grouping; retains rare valid openings."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .io import content_hash
from .schema import Observation, RankedSite, Site, unique_ids


def jaccard(left, right) -> float:
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass(frozen=True)
class GroupingConfig:
    minimum_jaccard: float = 0.35
    maximum_center_distance: float | None = None
    candidate_cap: int = 64

    def __post_init__(self) -> None:
        if not 0 < self.minimum_jaccard <= 1:
            raise ValueError("Grouping Jaccard must be in (0, 1]")
        if self.maximum_center_distance is not None:
            if not math.isfinite(self.maximum_center_distance) or self.maximum_center_distance <= 0:
                raise ValueError("Maximum center distance must be positive and finite")
        if type(self.candidate_cap) is not int or self.candidate_cap < 1:
            raise ValueError("Candidate cap must be a positive integer")


def _medoid(group: list[Observation]) -> Observation:
    return min(group, key=lambda x: (-sum(jaccard(x.residues, y.residues) for y in group), x.observation_id))


def group_observations(
    observations: list[Observation], config: GroupingConfig = GroupingConfig()
) -> list[Site]:
    """Greedy complete-link grouping, stable under input permutation.

    A candidate joins only if it satisfies the criterion with EVERY member.
    Unlike single linkage, an intermediate observation cannot bridge two sites
    with incompatible residue sets. This is a deterministic heuristic, not an
    assertion that complete-link clustering has a unique global solution.

    If a spatial bound is enabled, inputs MUST already share the apo frame.
    This returns uncapped groups so evaluation can audit any coverage lost by cap.
    """
    unique_ids(observations, "observation_id")
    groups: list[list[Observation]] = []
    for observation in sorted(observations, key=lambda x: x.observation_id):
        choices = []
        for index, group in enumerate(groups):
            similarities = [jaccard(observation.residues, other.residues) for other in group]
            if min(similarities) < config.minimum_jaccard:
                continue
            if config.maximum_center_distance is not None and any(
                math.dist(observation.center, other.center) > config.maximum_center_distance
                for other in group
            ):
                continue
            choices.append((-min(similarities), index))
        if choices:
            groups[min(choices)[1]].append(observation)
        else:
            groups.append([observation])
    sites = []
    for group in groups:
        medoid = _medoid(group)
        site_id = "site-" + content_hash([x.observation_id for x in group])[:16]
        sites.append(Site(site_id, medoid.residues, tuple(group), medoid.observation_id))
    return sorted(sites, key=lambda x: x.site_id)


def cap_candidates(sites: list[Site], cap: int) -> tuple[list[Site], list[str]]:
    """Reference-free cap based on highest observation detector score.

    The score comes from a single named detector; combining incomparable detector
    scales requires a new development-frozen cap rule.
    """
    if type(cap) is not int or cap < 1:
        raise ValueError("Candidate cap must be a positive integer")
    unique_ids(sites, "site_id")
    ordered = sorted(sites, key=lambda s: (-max(o.detector_score for o in s.observations), s.site_id))
    return ordered[:cap], [s.site_id for s in ordered[cap:]]


def best_per_frame(site: Site, *, source: str = "ensemble") -> list[Observation]:
    """One observation per frame; extra detector fragments cannot inflate support."""
    frames = defaultdict(list)
    for observation in site.observations:
        if observation.source == source:
            frames[observation.frame_id].append(observation)
    return [min(frames[key], key=lambda o: (-o.detector_score, o.observation_id)) for key in sorted(frames)]


def representative(site: Site, *, ensemble_available: bool) -> Observation:
    """Fixed detector-based selector, NOT a trained conformation selector."""
    observations = [o for o in site.observations if o.source == "ensemble"] if ensemble_available else []
    if not observations:
        observations = [o for o in site.observations if o.source in {"apo", "surface"}]
    if not observations:
        raise ValueError("Site has no observation compatible with declared ensemble availability")
    return min(observations, key=lambda o: (-o.detector_score, o.observation_id))


def ranked_unique(sites: list[RankedSite], *, top_k: int, dedup_jaccard: float = 0.5) -> list[RankedSite]:
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k must be a nonnegative integer")
    if not 0 < dedup_jaccard <= 1:
        raise ValueError("Deduplication Jaccard must be in (0, 1]")
    unique_ids(sites, "site_id")
    retained: list[RankedSite] = []
    for site in sorted(sites, key=lambda x: (-x.score, x.site_id)):
        if len(retained) == top_k:
            break
        if all(jaccard(site.residues, other.residues) < dedup_jaccard for other in retained):
            retained.append(site)
    return retained
