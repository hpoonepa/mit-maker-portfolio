#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Build the epitope benchmark manifest.

Typical use:

    # validate the pipeline on a small sample (does not download the full set)
    python scripts/build_benchmark.py --limit 30 --out build/benchmark

    # see what would happen, touching no network
    python scripts/build_benchmark.py --limit 30 --dry-run

    # full build, resumable: re-running picks up where it stopped
    python scripts/build_benchmark.py --out build/benchmark

    # given an existing manifest, just fetch the coordinates it names
    python scripts/build_benchmark.py --out build/benchmark --coords-only

Everything dropped is written to ``dropped.csv`` next to the manifest and
counted in the summary. There is no silent truncation anywhere: ``--limit``
reports how many instances it set aside, and so does the per-cluster cap.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path
from statistics import median

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT, REPO_ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from benchmark import cluster as clusterlib  # noqa: E402
from benchmark import epitope as epitopelib  # noqa: E402
from benchmark import manifest as manifestlib  # noqa: E402
from benchmark import sabdab  # noqa: E402

app = typer.Typer(add_completion=False)

DEFAULT_CACHE = REPO_ROOT / ".cache" / "benchmark"


def _log(message: str) -> None:
    typer.echo(message, err=True)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. No numpy dependency in the reporting path."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


@app.command()
def build(
    out: Path = typer.Option(
        REPO_ROOT / "build" / "benchmark", "--out", help="Output directory."
    ),
    limit: int = typer.Option(
        0, "--limit", help="Process at most N instances (0 = all). Reports the rest."
    ),
    cutoff: float = typer.Option(
        epitopelib.EPITOPE_CUTOFF_A, "--cutoff", help="Contact cutoff in angstrom."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Plan only: no coordinate or metadata downloads."
    ),
    cache: Path = typer.Option(DEFAULT_CACHE, "--cache", help="Download cache."),
    max_resolution: float = typer.Option(
        3.5, "--max-resolution", help="Drop entries worse than this."
    ),
    cluster_cap: int = typer.Option(
        clusterlib.CLUSTER_CAP, "--cluster-cap", help="Max complexes per cluster."
    ),
    only: str = typer.Option(
        "", "--only", help="Comma-separated PDB ids to restrict to (for validation)."
    ),
    refresh_snapshot: bool = typer.Option(
        False, "--refresh-snapshot", help="Refetch the SAbDab table and re-pin it."
    ),
    coords_only: bool = typer.Option(
        False,
        "--coords-only",
        help="Download the coordinates named by an existing manifest, then stop.",
    ),
    no_cluster: bool = typer.Option(
        False, "--no-cluster", help="Skip RCSB metadata; emit no cluster ids."
    ),
) -> None:
    """Derive epitope labels and write the manifest."""
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    cif_cache = cache / "cif"
    meta_cache = cache / "rcsb"

    if coords_only:
        _coords_only(out / "manifest.csv", cif_cache)
        return

    if refresh_snapshot:
        _log(f"fetching {sabdab.SUMMARY_URL}")
        snapshot = sabdab.fetch_summary()
        path = sabdab.save_snapshot(snapshot)
        _log(f"pinned snapshot -> {path}")
    else:
        snapshot = sabdab.load_summary(allow_network=False)
    _log(f"snapshot: {snapshot.as_log()}")

    all_instances = sabdab.parse_instances(snapshot.csv_text)
    counts_all = sabdab.count_instances(all_instances, n_rows=snapshot.n_rows)
    _log(
        f"table: {counts_all.n_rows} rows -> {counts_all.n_instances} antibody "
        f"instances -> {counts_all.n_entries} PDB entries "
        f"(row/entry inflation {counts_all.row_inflation:.2f}x)"
    )

    usable = sabdab.protein_antigen_instances(
        all_instances, max_resolution=max_resolution
    )
    counts_usable = sabdab.count_instances(usable)
    _log(
        f"protein antigen, <= {max_resolution} A: {counts_usable.n_instances} "
        f"instances across {counts_usable.n_entries} entries"
    )

    if only:
        wanted = {token.strip().lower() for token in only.split(",") if token.strip()}
        usable = [i for i in usable if i.pdb_id in wanted]
        _log(f"--only: restricted to {len(usable)} instances in {sorted(wanted)}")

    deferred = 0
    if limit and len(usable) > limit:
        deferred = len(usable) - limit
        usable = usable[:limit]
        _log(f"--limit {limit}: deferred {deferred} instances to a later run")

    if dry_run:
        _log(
            f"DRY RUN: would fetch {len({i.pdb_id for i in usable})} entries into "
            f"{cif_cache} and write {out / 'manifest.csv'}"
        )
        _log(f"elapsed {time.monotonic() - started:.1f}s")
        return

    # Cluster and cap BEFORE downloading coordinates. The cap decides which
    # complexes are wanted, and it needs only SAbDab chain roles plus RCSB
    # metadata (a few hundred kB per 100 entries) — not the 0.54 MB-per-entry
    # coordinate files. Capping afterwards downloads gigabytes to then discard
    # them: measured, the cap drops 20% of a random 80-entry sample, and far
    # more on the real distribution where spike alone is 17% of instances.
    dropped: list[manifestlib.DroppedRow] = []
    metadata: dict = {}
    if not no_cluster:
        metadata = clusterlib.fetch_chain_metadata(
            [i.pdb_id for i in usable], meta_cache, log=_log
        )

    cluster_of = clusterlib.assign_clusters(
        [(i.instance_id, i.pdb_id, i.antigen_chains) for i in usable], metadata
    )
    resolution_of = {
        i.instance_id: (i.resolution if i.resolution is not None else 99.0)
        for i in usable
    }
    kept, capped = clusterlib.cap_clusters(
        cluster_of, cap=cluster_cap, rank=lambda i: (resolution_of.get(i, 99.0),)
    )
    for instance_id, cluster_id in capped:
        dropped.append(
            manifestlib.DroppedRow(
                instance_id=instance_id,
                pdb_id=instance_id.split("-")[0].replace("pdb_0000", ""),
                reason="cluster_cap",
                detail=f"cluster {cluster_id} already has {cluster_cap} complexes",
            )
        )
    if capped:
        _log(
            f"cluster cap {cluster_cap}: dropped {len(capped)} redundant "
            f"complexes before downloading their coordinates"
        )

    wanted = [i for i in usable if i.instance_id in kept]
    _log(
        f"coordinates needed: {len({i.pdb_id for i in wanted})} entries for "
        f"{len(wanted)} instances in {len(set(kept.values()))} clusters"
    )

    # Every chain SAbDab calls an Hchain/Lchain anywhere in an entry, so the
    # antigen gate can refuse a *neighbouring* Fab's chain too, not just this
    # instance's own. Built from the full table rather than from `wanted`: an
    # instance the cluster cap removed still has its chains in the file.
    entry_antibody: dict[str, set[str]] = {}
    for inst in all_instances:
        entry_antibody.setdefault(inst.pdb_id, set()).update(inst.antibody_chains)

    results, epitope_drops = _derive_epitopes(
        wanted, cif_cache, cutoff, entry_antibody
    )
    dropped.extend(epitope_drops)

    split_of = clusterlib.assign_splits(kept.values())

    rows = [
        manifestlib.ManifestRow.from_epitope(
            result,
            heavy_chain=inst.heavy_chain,
            light_chain=inst.light_chain,
            cluster_id=kept[result.instance_id],
            split=split_of[kept[result.instance_id]],
            method=inst.method,
            resolution=inst.resolution,
            chain_resolution=resolutions,
        )
        for result, inst, resolutions in results
    ]
    # Clusters can end up under-filled when an instance is dropped after the
    # cap (empty antibody set, sub-floor epitope). That is logged, not fixed by
    # back-filling: back-filling would make the kept set depend on failures.
    kept = {row.instance_id: row.cluster_id for row in rows}

    manifest_path = manifestlib.write_manifest(rows, out / "manifest.csv")
    dropped_path = manifestlib.write_dropped(dropped, out / "dropped.csv")
    _report(rows, dropped, kept, manifest_path, dropped_path, deferred, started)


def _derive_epitopes(
    instances,
    cif_cache: Path,
    cutoff: float,
    entry_antibody_chains: dict[str, set[str]] | None = None,
):
    """Fetch coordinates and derive one epitope per instance.

    Grouped by entry so each cif is parsed once even when it holds four Fabs.
    """
    by_entry: dict[str, list] = {}
    for inst in instances:
        by_entry.setdefault(inst.pdb_id, []).append(inst)

    results: list[tuple[epitopelib.EpitopeResult, object, tuple]] = []
    dropped: list[manifestlib.DroppedRow] = []

    for index, (pdb_id, group) in enumerate(sorted(by_entry.items()), start=1):
        try:
            target = epitopelib.cached_structure(pdb_id, cif_cache)
        except epitopelib.CoordinateFetchError as exc:
            for inst in group:
                dropped.append(
                    manifestlib.DroppedRow(
                        inst.instance_id, pdb_id, "coordinates_unavailable", str(exc)
                    )
                )
            _log(f"DROP {pdb_id}: {exc}")
            continue

        namespaces = epitopelib.chain_namespaces(target)
        chain_ids = list(namespaces.auth)
        for inst in group:
            antibody, unresolved_ab = epitopelib.resolve_chains(
                inst.antibody_chains, chain_ids
            )
            # Guard 5. Every annotated antigen identifier gets an outcome, and
            # the outcome names the namespace that answered. Nothing is
            # substituted: a chain we cannot place is a drop, not a guess.
            declared_ab = (entry_antibody_chains or {}).get(pdb_id, set())
            siblings, _ = epitopelib.resolve_chains(declared_ab, chain_ids)
            resolutions = epitopelib.resolve_antigen_chains(
                inst.antigen_chains,
                namespaces,
                antibody_chains=antibody,
                entry_antibody_chains=siblings,
            )
            antigen: list[str] = []
            for res in resolutions:
                if res.usable and res.chain not in antigen:
                    antigen.append(res.chain)
            refused = [res for res in resolutions if res.refused]
            if refused:
                detail = ", ".join(str(r) for r in resolutions)
                dropped.append(
                    manifestlib.DroppedRow(
                        inst.instance_id,
                        pdb_id,
                        "unresolvable_antigen_chain",
                        f"declared {list(inst.antigen_chains)}; {detail}",
                    )
                )
                _log(
                    f"DROP {inst.instance_id}: antigen chain(s) "
                    f"{', '.join(str(r) for r in refused)} cannot be placed in "
                    f"{pdb_id} (auth / label / non-polymer all checked); refusing "
                    f"to label from the {len(antigen)} chain(s) that did resolve"
                )
                continue
            if any(res.namespace != epitopelib.NS_AUTH for res in resolutions):
                _log(
                    f"note {inst.instance_id}: chain resolution "
                    f"{', '.join(str(r) for r in resolutions)}"
                )
            try:
                result = epitopelib.epitope(
                    target,
                    instance_id=inst.instance_id,
                    antibody_chains=antibody,
                    antigen_chains=antigen,
                    cutoff=cutoff,
                )
            except epitopelib.EmptyAntibodyAtomSet as exc:
                dropped.append(
                    manifestlib.DroppedRow(
                        inst.instance_id, pdb_id, "empty_antibody_atom_set", str(exc)
                    )
                )
                _log(f"DROP {inst.instance_id}: empty antibody atom set")
                continue
            except epitopelib.NoAntigenAtoms as exc:
                # Report the *declared* chains, not the resolved ones: the
                # resolved list is empty by definition here, so printing it
                # tells the reader nothing about what went wrong.
                dropped.append(
                    manifestlib.DroppedRow(
                        inst.instance_id,
                        pdb_id,
                        "no_protein_antigen_chain",
                        f"declared {list(inst.antigen_chains)}, resolved "
                        f"{', '.join(str(r) for r in resolutions)}: {exc}",
                    )
                )
                _log(
                    f"DROP {inst.instance_id}: none of the declared antigen "
                    f"chains {list(inst.antigen_chains)} is a protein chain "
                    f"of {pdb_id}"
                )
                continue

            if not result.passes_size_floor:
                dropped.append(
                    manifestlib.DroppedRow(
                        inst.instance_id,
                        pdb_id,
                        "below_size_floor",
                        f"{result.size} residues < {epitopelib.MIN_EPITOPE_RESIDUES}",
                    )
                )
                _log(
                    f"DROP {inst.instance_id}: epitope of {result.size} residues is "
                    f"below the {epitopelib.MIN_EPITOPE_RESIDUES}-residue floor"
                )
                continue
            results.append((result, inst, resolutions))

        if index % 50 == 0:
            _log(f"epitopes: {index}/{len(by_entry)} entries")
    return results, dropped


def _coords_only(manifest_path: Path, cif_cache: Path) -> None:
    """Download exactly the coordinates an existing manifest names.

    This is the companion to shipping no coordinates in git: a user clones the
    repo, gets the manifest, and runs this to materialise the structures.
    """
    if not manifest_path.exists():
        raise typer.BadParameter(
            f"no manifest at {manifest_path}; run a build first, or point --out "
            f"at the directory that contains manifest.csv"
        )
    rows = manifestlib.read_manifest(manifest_path)
    ids = sorted({row.pdb_id for row in rows})
    _log(f"{len(ids)} entries named by {manifest_path}")
    failed = 0
    for index, pdb_id in enumerate(ids, start=1):
        try:
            epitopelib.cached_structure(pdb_id, cif_cache)
        except epitopelib.CoordinateFetchError as exc:
            failed += 1
            _log(f"FAIL {pdb_id}: {exc}")
        if index % 50 == 0:
            _log(f"coordinates: {index}/{len(ids)}")
    _log(f"done: {len(ids) - failed} fetched into {cif_cache}, {failed} failed")


def _report(rows, dropped, kept, manifest_path, dropped_path, deferred, started):
    sizes = [float(row.n_epitope) for row in rows]
    reasons = Counter(row.reason for row in dropped)
    clusters = clusterlib.cluster_sizes(kept)
    splits = Counter(row.split for row in rows)

    _log("")
    _log(f"manifest  {manifest_path}  ({len(rows)} instances)")
    _log(f"dropped   {dropped_path}   ({len(dropped)} instances)")
    for reason, count in reasons.most_common():
        _log(f"            {reason}: {count}")
    if deferred:
        _log(f"deferred by --limit: {deferred}")
    if sizes:
        _log(
            f"epitope size: median {median(sizes):.0f}, "
            f"IQR {_percentile(sizes, 0.25):.0f}-{_percentile(sizes, 0.75):.0f}, "
            f"range {min(sizes):.0f}-{max(sizes):.0f}"
        )
    _log(f"clusters: {len(clusters)}; largest {clusters[:3]}")
    _log(f"splits (instances): {dict(sorted(splits.items()))}")
    _log(f"elapsed {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    app()
