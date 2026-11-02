"""Cross-frame pocket clustering. PURE: same inputs → same outputs, no I/O."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from legacy_poc.pockets import Pocket


@dataclass(frozen=True)
class PocketSite:
    centroid: tuple[float, float, float]
    persistence: float          # fraction of total frames the site appears in
    n_frames_present: int
    total_frames: int
    mean_volume: float
    mean_druggability: float


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def cluster_pockets_across_frames(
    frames: list[list[Pocket]],
    distance_threshold: float = 4.0,
) -> list[PocketSite]:
    total = len(frames)
    if total == 0:
        return []

    flat: list[tuple[int, Pocket]] = [
        (fi, p) for fi, frame in enumerate(frames) for p in frame
    ]
    if not flat:
        return []

    n = len(flat)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _dist(flat[i][1].center, flat[j][1].center) <= distance_threshold:
                union(i, j)

    clusters: dict[int, list[tuple[int, Pocket]]] = {}
    for i, (fi, p) in enumerate(flat):
        clusters.setdefault(find(i), []).append((fi, p))

    sites: list[PocketSite] = []
    for members in clusters.values():
        frame_indices = {fi for fi, _ in members}
        cx = sum(p.center[0] for _, p in members) / len(members)
        cy = sum(p.center[1] for _, p in members) / len(members)
        cz = sum(p.center[2] for _, p in members) / len(members)
        vols = [p.volume for _, p in members]
        drugs = [p.druggability for _, p in members]
        sites.append(
            PocketSite(
                centroid=(cx, cy, cz),
                persistence=len(frame_indices) / total,
                n_frames_present=len(frame_indices),
                total_frames=total,
                mean_volume=sum(vols) / len(vols),
                mean_druggability=sum(drugs) / len(drugs),
            )
        )
    sites.sort(key=lambda s: -s.persistence)
    return sites
