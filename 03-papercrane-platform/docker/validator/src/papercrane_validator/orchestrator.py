"""Orchestrator: iterate designs, compute every canonical metric, aggregate.

All metrics are INDEPENDENT — no metric consumes another's output — with
one exception: `overath` is a composite and takes the hotspot-contact and
ESM2 pLL we already computed. The orchestrator enforces that ordering.

We keep this module intentionally boring: a for-loop over designs, a
for-loop over metrics, try/except around each metric call. That design
lets one bad metric (e.g. DockQ unavailable) fail without killing the
rest of the validation for the same design.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Mapping

from .metrics import (
    compute_dockq,
    compute_esm_pll,
    compute_ipsae,
    compute_lis,
    compute_overath,
    compute_ptmenergy,
    hotspot_contact_fraction,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class DesignRecord:
    path: str
    seed: int
    upstream_metrics: dict[str, float]
    sequence: str = ""


def _parse_designs_json(payload: Mapping[str, Any]) -> tuple[
    str,
    str,
    str,
    list[tuple[str, int]],
    list[DesignRecord],
]:
    """Extract the structured fields we need from `designs.json`.

    Returns (target_pdb, target_chain, binder_chain, hotspots, designs).
    Raises ValueError on malformed inputs — better to fail fast than to
    silently drop designs.
    """
    target_pdb = payload.get("target_pdb")
    if not target_pdb:
        raise ValueError("designs.json missing required 'target_pdb'")
    target_chain = payload.get("target_chain", "A")
    binder_chain = payload.get("binder_chain", "B")
    raw_hotspots = payload.get("hotspots", []) or []
    hotspots: list[tuple[str, int]] = []
    for hs in raw_hotspots:
        hotspots.append((hs["chain"], int(hs["resi"])))

    designs_payload = payload.get("designs")
    if not isinstance(designs_payload, list) or not designs_payload:
        raise ValueError("designs.json 'designs' must be a non-empty list")

    designs: list[DesignRecord] = []
    for i, d in enumerate(designs_payload):
        if "path" not in d:
            raise ValueError(f"design[{i}] missing 'path'")
        upstream = dict(d.get("upstream_metrics", {}))
        designs.append(
            DesignRecord(
                path=d["path"],
                seed=int(d.get("seed", 0)),
                upstream_metrics=upstream,
                sequence=str(upstream.get("sequence", "")),
            )
        )
    return target_pdb, target_chain, binder_chain, hotspots, designs


def _compute_metrics_for_design(
    design: DesignRecord,
    target_chain: str,
    binder_chain: str,
    hotspots: list[tuple[str, int]],
) -> dict[str, float]:
    """Run every metric for ONE design. Exceptions are logged and mapped
    to a sentinel (-1.0) so a single bad design doesn't nuke the whole
    run — but they ALWAYS show up in the output so downstream filters can
    drop them.
    """
    metrics: dict[str, float] = {}

    def _safe(name: str, fn, *args, **kwargs) -> float:
        try:
            v = float(fn(*args, **kwargs))
            return v
        except Exception as e:  # pragma: no cover -- defensive
            logger.warning("metric %s failed for %s: %s", name, design.path, e)
            return -1.0

    metrics["ipsae"] = _safe(
        "ipsae",
        compute_ipsae,
        design.path,
        design.upstream_metrics,
        target_chain=target_chain,
        binder_chain=binder_chain,
    )
    metrics["dockq"] = _safe(
        "dockq",
        compute_dockq,
        design.path,
        design.upstream_metrics,
        target_chain=target_chain,
        binder_chain=binder_chain,
    )
    metrics["ptmenergy"] = _safe(
        "ptmenergy", compute_ptmenergy, design.path, design.upstream_metrics
    )
    metrics["lis"] = _safe(
        "lis", compute_lis, design.path, design.upstream_metrics
    )
    metrics["hotspot_contact"] = _safe(
        "hotspot_contact",
        hotspot_contact_fraction,
        design.path,
        target_chain,
        binder_chain,
        hotspots,
    )
    metrics["esm_pll"] = _safe(
        "esm_pll", compute_esm_pll, design.sequence
    )
    # Overath is composite — feed it the two metrics it consumes.
    metrics["overath"] = _safe(
        "overath",
        compute_overath,
        design.upstream_metrics,
        metrics["hotspot_contact"],
        metrics["esm_pll"],
    )
    return metrics


def run_validation(designs_json: str, outputs_dir: str) -> int:
    """Entrypoint used by both the CLI and the test suite.

    Args:
        designs_json: absolute path to the input manifest.
        outputs_dir: absolute path to the writable output directory. The
            function writes `validated.json` into this directory.

    Returns:
        0 on success, non-zero on validation failure (malformed inputs,
        I/O errors). Metric-level failures are captured INSIDE the output
        JSON and do NOT fail the run — callers filter on the metric
        sentinels instead.
    """
    payload = json.loads(Path(designs_json).read_text())
    target_pdb, target_chain, binder_chain, hotspots, designs = _parse_designs_json(
        payload
    )

    logger.info(
        "Validating %d designs against %s (chains %s/%s, %d hotspots)",
        len(designs),
        target_pdb,
        target_chain,
        binder_chain,
        len(hotspots),
    )

    out_designs: list[dict[str, Any]] = []
    for d in designs:
        m = _compute_metrics_for_design(d, target_chain, binder_chain, hotspots)
        out_designs.append(
            {
                "path": d.path,
                "seed": d.seed,
                "upstream_metrics": d.upstream_metrics,
                "metrics": m,
            }
        )

    out_path = Path(outputs_dir) / "validated.json"
    out_path.write_text(
        json.dumps(
            {
                "target_pdb": target_pdb,
                "target_chain": target_chain,
                "binder_chain": binder_chain,
                "hotspots": [{"chain": c, "resi": r} for c, r in hotspots],
                "designs": out_designs,
            },
            indent=2,
        )
    )
    logger.info("Wrote %s", out_path)
    return 0
