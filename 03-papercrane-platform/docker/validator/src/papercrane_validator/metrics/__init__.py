"""Canonical-metric implementations for Paper Crane designs.

Each submodule exposes ONE public callable that takes a per-design context
object and returns a float. That uniform shape lets the orchestrator iterate
over metric names without per-metric special casing.
"""

from .dockq import compute_dockq
from .esm_pll import compute_esm_pll
from .hotspot import hotspot_contact_fraction
from .ipsae import compute_ipsae
from .lis import compute_lis
from .overath import compute_overath
from .ptmenergy import compute_ptmenergy

__all__ = [
    "compute_dockq",
    "compute_esm_pll",
    "hotspot_contact_fraction",
    "compute_ipsae",
    "compute_lis",
    "compute_overath",
    "compute_ptmenergy",
]
