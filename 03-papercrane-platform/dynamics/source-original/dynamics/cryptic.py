"""Cryptic-pocket calling. PURE."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from dynamics.cluster import PocketSite
from dynamics.pockets import Pocket


@dataclass(frozen=True)
class CrypticCall:
    site: PocketSite
    score: float
    apo_match_distance: float | None
    apo_volume_ratio: float | None


def _dist(a, b) -> float:
    return sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def call_cryptic_pockets(
    sites: list[PocketSite],
    apo_pockets: list[Pocket],
    persistence_threshold: float = 0.2,
    distance_match_threshold: float = 5.0,
    volume_ratio_threshold: float = 0.3,
) -> list[CrypticCall]:
    """A site is cryptic if (a) persistence >= threshold AND (b) no apo pocket
    is both within distance_match_threshold AND comparably sized
    (apo_vol / site_vol >= volume_ratio_threshold)."""
    calls: list[CrypticCall] = []
    for site in sites:
        if site.persistence < persistence_threshold:
            continue

        nearest_d: float | None = None
        nearest_vol_ratio: float | None = None
        matched = False
        for apo in apo_pockets:
            d = _dist(site.centroid, apo.center)
            if nearest_d is None or d < nearest_d:
                nearest_d = d
                nearest_vol_ratio = (
                    apo.volume / site.mean_volume if site.mean_volume > 0 else None
                )
            if d <= distance_match_threshold:
                ratio = apo.volume / site.mean_volume if site.mean_volume > 0 else 1.0
                if ratio >= volume_ratio_threshold:
                    matched = True
                    break

        if matched:
            continue

        # Apo penalty only applies if the nearest apo is within the distance
        # match threshold; otherwise the site is genuinely apo-absent.
        if (
            nearest_d is not None
            and nearest_d <= distance_match_threshold
            and nearest_vol_ratio is not None
        ):
            apo_pen = min(nearest_vol_ratio, 1.0)
        else:
            apo_pen = 0.0
        score = site.persistence * (1.0 - apo_pen)
        calls.append(
            CrypticCall(
                site=site,
                score=score,
                apo_match_distance=nearest_d,
                apo_volume_ratio=nearest_vol_ratio,
            )
        )
    calls.sort(key=lambda c: -c.score)
    return calls
