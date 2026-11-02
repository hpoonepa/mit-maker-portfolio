"""Re-export Mosaic's pTMEnergy objective.

Reference: Nori, Parsan, Uhler and Jin, BindEnergyCraft: Casting Protein
Structure Predictors as Energy-Based Models for Binder Design (2025),
https://arxiv.org/abs/2505.21241.

The published method derives an energy objective from predicted alignment-error
outputs. This module imports the upstream implementation; it does not reproduce
the full BindEnergyCraft study. V4 used weight 0.075; V5 uses 1.5. These campaign
choices are not a new experimental validation of that weight or objective.
"""

from mosaic.losses.structure_prediction import pTMEnergy

__all__ = ["pTMEnergy"]


if __name__ == "__main__":
    print(f"pTMEnergy imported from: {pTMEnergy.__module__}")
