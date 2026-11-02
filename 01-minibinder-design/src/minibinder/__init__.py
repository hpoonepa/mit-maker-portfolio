"""Target inspection, campaign design, independent folding and candidate scoring.

The main campaign targets DWV VP3 (5G51); earlier RBX1/2LGV experiments remain
as reference source. Upstream Mosaic supplies the structure predictors,
ProteinMPNN and optimizer. This package supplies target-specific settings,
objectives, analysis and compute runners; see CITATIONS.md for credits.
"""

__all__ = ["prepare", "design", "fold", "score", "filter"]
