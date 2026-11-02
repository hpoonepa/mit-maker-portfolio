"""target_features.py — Sequence-based target-side feature proxies (v1).

These are CHEAP, SEQUENCE-ONLY proxies for the per-target signal we ultimately
want from structure. There is NO structure tool here: secondary structure is a
Chou-Fasman propensity prediction, "interface class" is derived from that
prediction, and pocket/druggability are deliberately NaN (they require a real
structure + fpocket). This is a documented v1 — the planned upgrade is
structure-based features (AlphaFold structures + DSSP/fpocket) before drawing
any conclusion about the per-target thesis.

All functions are pure Python with zero third-party dependencies.
"""

from __future__ import annotations

import math

# Kyte-Doolittle hydropathy index (mean over residues -> epitope_hydrophobicity).
_KYTE_DOOLITTLE = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# Standard Chou-Fasman conformational propensities: (P(alpha), P(beta)).
_CHOU_FASMAN = {
    "A": (1.42, 0.83), "R": (0.98, 0.93), "N": (0.67, 0.89), "D": (1.01, 0.54),
    "C": (0.70, 1.19), "Q": (1.11, 1.10), "E": (1.51, 0.37), "G": (0.57, 0.75),
    "H": (1.00, 0.87), "I": (1.08, 1.60), "L": (1.21, 1.30), "K": (1.16, 0.74),
    "M": (1.45, 1.05), "F": (1.13, 1.38), "P": (0.57, 0.55), "S": (0.77, 0.75),
    "T": (0.83, 1.19), "W": (1.08, 1.37), "Y": (0.69, 1.47), "V": (1.06, 1.70),
}

# Residue sets.
_POLAR = set("STNQCYHKRDE")
_HYDROPHOBIC = set("AILMFWVP")
_AROMATIC = set("FWY")
# Disorder-promoting residues (Dunker et al.) — a simple disorder proxy.
_DISORDER_PROMOTING = set("SPEKQGRDAN")

_NAN = float("nan")


def _clean(seq: str) -> str:
    """Uppercase, strip surrounding whitespace, drop internal whitespace."""
    return "".join(seq.split()).upper()


def chou_fasman_fractions(seq: str) -> tuple[float, float, float]:
    """Per-residue Chou-Fasman SS classification -> (helix, strand, loop) fractions.

    Each residue is classified helix if P(a) > P(b) and P(a) > 1.0; strand if
    P(b) > P(a) and P(b) > 1.0; else loop. Fractions sum to 1.0. Unknown
    residues (not in the table) count as loop.
    """
    seq = _clean(seq)
    n = len(seq)
    if n == 0:
        return 0.0, 0.0, 0.0
    h = s = lp = 0
    for a in seq:
        props = _CHOU_FASMAN.get(a)
        if props is None:
            lp += 1
            continue
        pa, pb = props
        if pa > pb and pa > 1.0:
            h += 1
        elif pb > pa and pb > 1.0:
            s += 1
        else:
            lp += 1
    return h / n, s / n, lp / n


def interface_class(frac_helix: float, frac_strand: float, frac_loop: float) -> str:
    """Classify the dominant interface geometry from predicted SS fractions.

    "helical"    if frac_helix >= 0.45 and frac_helix > frac_strand
    "sheet_flat" if frac_strand >= 0.35 and frac_strand > frac_helix
    "mixed"      otherwise.

    (We never emit "ligand_present" — not determinable from sequence.)
    """
    if frac_helix >= 0.45 and frac_helix > frac_strand:
        return "helical"
    if frac_strand >= 0.35 and frac_strand > frac_helix:
        return "sheet_flat"
    return "mixed"


def compute_target_features(seq: str) -> dict:
    """Compute all sequence-based target-side features for a target sequence.

    Returns a dict with numeric features plus ``interface_class`` (str).
    ``pocket_volume`` and ``druggability`` are NaN (require structure+fpocket).
    """
    s = _clean(seq)
    n = len(s)
    if n == 0:
        raise ValueError("empty target sequence")

    frac_helix, frac_strand, frac_loop = chou_fasman_fractions(s)

    n_k = s.count("K")
    n_r = s.count("R")
    n_d = s.count("D")
    n_e = s.count("E")

    # Mean Kyte-Doolittle over known residues only (unknowns ignored), but
    # divided by n to keep it a per-residue mean of the full sequence.
    kd_sum = sum(_KYTE_DOOLITTLE.get(a, 0.0) for a in s)

    return {
        "log_length": math.log(n),
        "frac_polar": sum(1 for a in s if a in _POLAR) / n,
        "hydrophobic_fraction": sum(1 for a in s if a in _HYDROPHOBIC) / n,
        "aromatic_fraction": sum(1 for a in s if a in _AROMATIC) / n,
        "epitope_net_charge": (n_k + n_r - n_d - n_e) / n,
        "epitope_hydrophobicity": kd_sum / n,
        "frac_helix": frac_helix,
        "frac_strand": frac_strand,
        "frac_loop": frac_loop,
        "disorder_fraction": sum(1 for a in s if a in _DISORDER_PROMOTING) / n,
        "interface_class": interface_class(frac_helix, frac_strand, frac_loop),
        "pocket_volume": _NAN,
        "druggability": _NAN,
    }
