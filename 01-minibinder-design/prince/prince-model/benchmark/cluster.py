# SPDX-License-Identifier: MIT
"""Antigen-level redundancy clustering and held-out splits.

**Why clustering is not optional.** SARS-CoV-2 spike (P0DTC2) alone is 2,871 of
16,701 protein-antigen instances — 17%. A model evaluated with an unstratified
micro-average over instances is, to a first approximation, being evaluated on
one glycoprotein. Worse, a random per-complex split puts near-identical spike
complexes in both train and test, so the reported score measures memorisation.

So: **cluster by antigen, hold out by cluster, and report the macro-average over
clusters.** Those three together are what make the number mean something.

Accession and exact-sequence identities are joined transitively across antigen
chains before capping or splitting. A complex containing antigens A and B must
not create a third group separate from A and B. Both identity routes participate,
including when one deposition lacks the accession recorded by another.

This guarantees accession/exact-sequence disjointness, not remote-homology
disjointness: related proteins with different accessions and sequences may still
cross splits. Adding a connecting antigen can merge old components, so a rebuilt
benchmark requires new fitting and evaluation artifacts.

A **secondary** sensitivity analysis can adopt AsEP's published epitope-group
split by joining on PDB id. Do not re-run MMseqs2 to reproduce it; that adds a
binary dependency for a number we already have from the authors.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

__all__ = [
    "RCSB_GRAPHQL_URL",
    "GRAPHQL_BATCH_SIZE",
    "CLUSTER_CAP",
    "SPLIT_FRACTIONS",
    "MetadataFetchError",
    "ChainMeta",
    "fetch_chain_metadata",
    "assign_clusters",
    "cap_clusters",
    "assign_splits",
    "macro_average",
    "cluster_sizes",
]

RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"
GRAPHQL_BATCH_SIZE = 100
"""100 ids per request is what the probe measured at ~80 s for 86 requests."""

CLUSTER_CAP = 20
"""Hard cap on complexes kept per cluster.

Without it, spike would still dominate the *training* set even though the
macro-average fixes the reporting. 20 is a choice, not a standard; it is stated
as such and the dropped instances are logged.
"""

SPLIT_FRACTIONS = (("train", 0.70), ("val", 0.15), ("test", 0.15))

_QUERY = """
query($ids:[String!]!){
  entries(entry_ids:$ids){
    rcsb_id
    polymer_entities{
      entity_poly{ pdbx_seq_one_letter_code_can rcsb_entity_polymer_type }
      rcsb_polymer_entity_container_identifiers{ auth_asym_ids uniprot_ids }
    }
  }
}
"""


class MetadataFetchError(RuntimeError):
    """RCSB metadata could not be obtained; message names the ids and the fix."""


@dataclass(frozen=True)
class ChainMeta:
    """What RCSB knows about one auth chain of one entry."""

    pdb_id: str
    auth_asym_id: str
    polymer_type: str
    sequence: str
    uniprot_accessions: tuple[str, ...]

    @property
    def sequence_digest(self) -> str:
        """sha1 of the canonical one-letter sequence, for the no-xref fallback."""
        return hashlib.sha1(self.sequence.encode("ascii", "ignore")).hexdigest()[:12]


def _post_graphql(ids: Sequence[str], timeout: float) -> dict:
    body = json.dumps({"query": _QUERY, "variables": {"ids": list(ids)}}).encode()
    request = urllib.request.Request(
        RCSB_GRAPHQL_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise MetadataFetchError(
            f"RCSB GraphQL POST failed for {len(ids)} ids starting {ids[0]}: "
            f"{exc}. The endpoint is {RCSB_GRAPHQL_URL}; retry, or build with "
            f"--no-cluster to produce a manifest without cluster ids."
        ) from exc
    except json.JSONDecodeError as exc:
        raise MetadataFetchError(
            f"RCSB GraphQL returned non-JSON for ids starting {ids[0]}: {exc}"
        ) from exc
    if payload.get("errors"):
        raise MetadataFetchError(
            f"RCSB GraphQL reported errors for ids starting {ids[0]}: "
            f"{json.dumps(payload['errors'])[:400]}"
        )
    return payload


def fetch_chain_metadata(
    pdb_ids: Iterable[str],
    cache_dir: Path | str,
    timeout: float = 120.0,
    batch_size: int = GRAPHQL_BATCH_SIZE,
    log: Callable[[str], None] | None = None,
) -> dict[tuple[str, str], ChainMeta]:
    """Fetch sequences and UniProt xrefs for every auth chain of every entry.

    Results are cached one JSON file per entry under ``cache_dir``, so a build
    interrupted at entry 5,000 of 8,548 resumes instead of restarting. Entries
    RCSB does not return are reported through ``log`` and simply absent from the
    result, which pushes them onto the sequence fallback or out of the build.

    Returns:
        ``{(pdb_id_lower, auth_asym_id): ChainMeta}``.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    emit = log or (lambda _msg: None)

    wanted = [p.lower() for p in dict.fromkeys(pdb_ids)]
    out: dict[tuple[str, str], ChainMeta] = {}
    missing: list[str] = []

    for pdb_id in wanted:
        path = cache_dir / f"{pdb_id}.json"
        if path.exists():
            out.update(_metas_from_cache(pdb_id, json.loads(path.read_text())))
        else:
            missing.append(pdb_id)

    for start in range(0, len(missing), batch_size):
        chunk = missing[start : start + batch_size]
        payload = _post_graphql([p.upper() for p in chunk], timeout)
        returned = {
            (entry.get("rcsb_id") or "").lower(): entry
            for entry in (payload.get("data") or {}).get("entries") or []
            if entry
        }
        for pdb_id in chunk:
            entry = returned.get(pdb_id)
            if entry is None:
                emit(f"DROP {pdb_id}: RCSB GraphQL returned no entry")
                continue
            entities = entry.get("polymer_entities") or []
            (cache_dir / f"{pdb_id}.json").write_text(json.dumps(entities))
            out.update(_metas_from_cache(pdb_id, entities))
        emit(
            f"rcsb metadata: {min(start + batch_size, len(missing))}/{len(missing)} "
            f"entries fetched"
        )
    return out


def _metas_from_cache(pdb_id: str, entities: list) -> dict[tuple[str, str], ChainMeta]:
    out: dict[tuple[str, str], ChainMeta] = {}
    for entity in entities or []:
        poly = entity.get("entity_poly") or {}
        ids = entity.get("rcsb_polymer_entity_container_identifiers") or {}
        sequence = (poly.get("pdbx_seq_one_letter_code_can") or "").replace("\n", "")
        accessions = tuple(sorted(ids.get("uniprot_ids") or ()))
        for auth_asym_id in ids.get("auth_asym_ids") or ():
            out[(pdb_id, auth_asym_id)] = ChainMeta(
                pdb_id=pdb_id,
                auth_asym_id=auth_asym_id,
                polymer_type=poly.get("rcsb_entity_polymer_type") or "",
                sequence=sequence,
                uniprot_accessions=accessions,
            )
    return out




def assign_clusters(
    instances: Sequence[tuple[str, str, Sequence[str]]],
    metadata: Mapping[tuple[str, str], ChainMeta],
) -> dict[str, str]:
    """Group connected antigen identities before capping and assigning splits."""
    parent: dict[str, str] = {}

    def root(token: str) -> str:
        parent.setdefault(token, token)
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    identities: dict[str, set[str]] = {}
    for instance_id, pdb_id, chains in instances:
        tokens: set[str] = set()
        for chain in chains:
            meta = metadata.get((pdb_id.lower(), chain))
            if meta is not None:
                tokens.update(f"up:{a}" for a in meta.uniprot_accessions)
                if meta.sequence:
                    tokens.add(f"seq:{meta.sequence_digest}")
        if not tokens:
            tokens.add(f"entry:{pdb_id.lower()}")
        identities[instance_id] = tokens
        anchor = min(tokens)
        for token in sorted(tokens):
            left, right = root(anchor), root(token)
            parent[max(left, right)] = min(left, right)

    return {
        instance_id: "component:" + root(min(tokens))
        for instance_id, tokens in identities.items()
    }


def cap_clusters(
    cluster_of: Mapping[str, str],
    cap: int = CLUSTER_CAP,
    rank: Callable[[str], tuple] | None = None,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Keep at most ``cap`` instances per cluster, deterministically.

    Args:
        rank: sort key over instance ids; the lowest-ranking ``cap`` are kept.
            Pass resolution so the best structures survive. Ties and the default
            fall back to the instance id, so the result never depends on dict
            ordering.

    Returns:
        ``(kept, dropped)`` where ``dropped`` is ``(instance_id, cluster_id)``
        pairs, for the log. Nothing is dropped silently.
    """
    by_cluster: dict[str, list[str]] = defaultdict(list)
    for instance_id, cluster_id in cluster_of.items():
        by_cluster[cluster_id].append(instance_id)

    key = rank or (lambda instance_id: ())
    kept: dict[str, str] = {}
    dropped: list[tuple[str, str]] = []
    for cluster_id in sorted(by_cluster):
        members = sorted(by_cluster[cluster_id], key=lambda i: (key(i), i))
        for instance_id in members[:cap]:
            kept[instance_id] = cluster_id
        for instance_id in members[cap:]:
            dropped.append((instance_id, cluster_id))
    return kept, dropped


def assign_splits(
    cluster_ids: Iterable[str],
    fractions: Sequence[tuple[str, float]] = SPLIT_FRACTIONS,
    seed: str = "hotspot-preflight-v1",
) -> dict[str, str]:
    """Assign each **cluster** to a split. Never splits a cluster.

    The assignment is a hash of ``seed + cluster_id``, not a shuffle, for two
    reasons: it is reproducible without storing a permutation, and it is
    *stable* — adding entries to the benchmark later does not move existing
    clusters between splits, so results stay comparable across versions.
    """
    total = sum(weight for _name, weight in fractions)
    if total <= 0:
        raise ValueError("split fractions must sum to a positive number")

    bounds: list[tuple[str, float]] = []
    cumulative = 0.0
    for name, weight in fractions:
        cumulative += weight / total
        bounds.append((name, cumulative))

    out: dict[str, str] = {}
    for cluster_id in dict.fromkeys(cluster_ids):
        digest = hashlib.sha256(f"{seed}:{cluster_id}".encode()).digest()
        position = int.from_bytes(digest[:8], "big") / float(1 << 64)
        out[cluster_id] = next(
            (name for name, edge in bounds if position < edge), bounds[-1][0]
        )
    return out


def cluster_sizes(cluster_of: Mapping[str, str]) -> list[tuple[str, int]]:
    """Clusters and their instance counts, largest first, for the family table."""
    counts: dict[str, int] = defaultdict(int)
    for cluster_id in cluster_of.values():
        counts[cluster_id] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def macro_average(
    values: Mapping[str, float], cluster_of: Mapping[str, str]
) -> tuple[float, int]:
    """Mean over clusters of the per-cluster mean. The number we report.

    The micro-average over instances is deliberately not provided here. If you
    want it you can compute it in one line, but you must then say in the text
    that 17% of it is SARS-CoV-2 spike.

    Returns:
        ``(macro_average, n_clusters)``. ``n_clusters`` is part of the result
        because a macro-average over 3 clusters and over 2,051 are very
        different claims and the number must travel with the score.
    """
    per_cluster: dict[str, list[float]] = defaultdict(list)
    for instance_id, value in values.items():
        cluster_id = cluster_of.get(instance_id)
        if cluster_id is not None:
            per_cluster[cluster_id].append(value)
    if not per_cluster:
        return (float("nan"), 0)
    means = [sum(vs) / len(vs) for vs in per_cluster.values()]
    return (sum(means) / len(means), len(means))
