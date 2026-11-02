"""Paper Crane canonical-metrics validator.

This package runs as the second stage in the Paper Crane pipeline: a design
tool (BindCraft, RFdiffusion, Boltz-2, ...) writes designs to /outputs, and
then the validator image is launched with the same /outputs mount plus a
/inputs/designs.json manifest. The validator computes the canonical metric
suite (ipSAE, DockQ, pTMEnergy, LIS, Overath, hotspot contact, ESM2 pLL) and
writes /outputs/validated.json.

See docs/plans/02-tool-integration.md section 5 for the architectural rationale.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
