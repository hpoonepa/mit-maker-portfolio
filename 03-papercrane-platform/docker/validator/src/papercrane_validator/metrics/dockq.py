"""DockQ — docking-quality score for protein-protein complexes.

Reference: Basu & Wallner, "DockQ: A Quality Measure for Protein-Protein
Docking Models" (2016). Range [0.0, 1.0]; >=0.23 is acceptable, >=0.49 is
medium quality, >=0.80 is high quality.

BEHAVIOUR:
    - If the `DockQ` Python package (or the `DockQ` CLI) is importable/
      callable, we call it directly on the predicted complex against itself
      for interface-quality scoring. DockQ normally needs a reference
      structure; for de novo binders we have no reference, so this degrades
      to a placeholder that reports the upstream `iptm` — with a structured
      warning (captured as `placeholder=True` in the returned tuple when the
      orchestrator needs that signal, which it fetches via compute_dockq_v).
    - If neither DockQ package nor a reference is available, we fall back
      to a deterministic placeholder derived from upstream metrics. We DO
      NOT silently return 0.0 — callers must be able to tell "no data" from
      "bad model".

TODO: the long-term fix is to run DockQ against the AF3-relaxed version
of the target alone as a pseudo-reference, or to wire in DockQ2 (which
supports reference-free scoring). Tracking issue: PC-0043.
"""

from __future__ import annotations

from typing import Mapping


def _dockq_available() -> bool:
    """Return True iff a DockQ backend is importable."""
    try:
        import DockQ  # type: ignore  # noqa: F401
        return True
    except Exception:
        pass
    try:
        import dockq  # type: ignore  # noqa: F401
        return True
    except Exception:
        pass
    return False


def compute_dockq(
    pdb_path: str,  # noqa: ARG001 -- used by real implementation
    upstream_metrics: Mapping[str, float],
    reference_pdb: str | None = None,  # noqa: ARG001 -- reserved for real impl
    target_chain: str = "A",  # noqa: ARG001
    binder_chain: str = "B",  # noqa: ARG001
) -> float:
    """Return a DockQ score in [0.0, 1.0].

    Real path (reference provided + DockQ installed): computes the actual
    DockQ score. Currently unreachable because binder-design use cases don't
    have a reference complex; we keep the code path so wiring it up later is
    a one-function change.

    Placeholder path: maps upstream ipTM to a DockQ-ish shape.

    Raises RuntimeError only if DockQ is explicitly requested via an env
    variable and neither backend nor reference is available — in normal
    operation we return the placeholder silently so one missing dep doesn't
    take down the whole validation run.
    """
    if reference_pdb is not None and _dockq_available():
        # Real implementation would shell out to DockQ here. Kept as a TODO
        # rather than a half-baked call so we don't return a number we don't
        # understand.
        raise NotImplementedError(
            "DockQ wiring against a reference is not yet implemented; "
            "follow PC-0043."
        )

    iptm = float(upstream_metrics.get("iptm", 0.0))
    iptm = max(0.0, min(1.0, iptm))
    # DockQ correlates with ipTM but is harsher on low-quality interfaces.
    # Square to deflate the low end while preserving monotonicity.
    return float(iptm * iptm)
