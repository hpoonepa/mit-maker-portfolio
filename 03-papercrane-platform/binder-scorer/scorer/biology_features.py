"""biology_features.py — Design-side (binder) biology descriptors (Orbion-style).

These are CHEAP, SEQUENCE-ONLY descriptors computed from the BINDER amino-acid
sequence. They were validated by Orbion 2026 ("Beyond Structure and Affinity")
as predictive of binder success beyond structure/affinity — aggregation
propensity was the most robust single signal, and the biology filters as a group
gave a 2.8x hit-rate lift. They are added as ``bio__*`` columns to the feature
table and weighted downstream by an LLM prior + a LightGBM baseline.

All functions are pure Python with zero third-party dependencies. The standard
Kyte-Doolittle hydropathy and Chou-Fasman propensity tables are REUSED from
``scorer.target_features`` (not duplicated).
"""

from __future__ import annotations

from scorer.target_features import (
    _KYTE_DOOLITTLE,
    _clean,
    chou_fasman_fractions,
)

# ---------------------------------------------------------------------------
# Tunable constants (documented, hardcoded — these define the descriptors).
# ---------------------------------------------------------------------------

# Aggregation propensity: max mean hydropathy over sliding windows of these sizes.
_AGG_WINDOW_SIZES = (5, 6, 7)

# Immunogenicity proxy: a 9-mer is "hydrophobic" if its mean KD exceeds this.
_IMMUNO_WINDOW = 9
_IMMUNO_HYDRO_THRESHOLD = 0.0

# Disorder-promoting residues (Dunker et al.) — same set used target-side.
_DISORDER_PROMOTING = set("SPEKQGRDAN")


def aggregation_propensity(seq: str) -> float:
    """Aggregation propensity from the binder sequence (higher = more prone).

    Definition (documented choice of the two Orbion-style options): the maximum,
    over all sliding windows of size in ``{5, 6, 7}``, of the mean Kyte-Doolittle
    hydropathy of the window. Contiguous hydrophobic stretches drive aggregation;
    this captures the single most hydrophobic local patch. Unknown residues
    contribute 0.0 hydropathy. Sequences shorter than the smallest window fall
    back to the mean hydropathy of the whole sequence. Empty -> 0.0.
    """
    s = _clean(seq)
    n = len(s)
    if n == 0:
        return 0.0
    kd = [_KYTE_DOOLITTLE.get(a, 0.0) for a in s]

    sizes = [w for w in _AGG_WINDOW_SIZES if w <= n]
    if not sizes:  # shorter than the smallest window -> whole-sequence mean
        return sum(kd) / n

    best = float("-inf")
    for w in sizes:
        window_sum = sum(kd[:w])
        best = max(best, window_sum / w)
        for i in range(w, n):
            window_sum += kd[i] - kd[i - w]
            best = max(best, window_sum / w)
    return best


def ptm_site_density(seq: str) -> float:
    """PTM-site density: (N-glyc sequons + O-glyc-prone S/T) / length.

    N-glycosylation sequons match the motif ``N[^P][ST]`` (each N that starts a
    valid sequon is counted, overlaps allowed). O-glyc-prone residues are the
    count of S and T. Length-normalized because Orbion flagged raw PTM density as
    length-confounded. Empty -> 0.0.
    """
    s = _clean(seq)
    n = len(s)
    if n == 0:
        return 0.0
    sequons = 0
    for i in range(n - 2):
        if s[i] == "N" and s[i + 1] != "P" and s[i + 2] in ("S", "T"):
            sequons += 1
    st = sum(1 for a in s if a in ("S", "T"))
    return (sequons + st) / n


def phospho_site_density(seq: str) -> float:
    """Phospho-acceptor density: (count of S + T + Y) / length. Empty -> 0.0."""
    s = _clean(seq)
    n = len(s)
    if n == 0:
        return 0.0
    return sum(1 for a in s if a in ("S", "T", "Y")) / n


def n_cys(seq: str) -> int:
    """Number of cysteine residues in the sequence."""
    return _clean(seq).count("C")


def cys_is_odd(seq: str) -> bool:
    """True if there is an odd number of cysteines (one unpaired cysteine)."""
    return n_cys(seq) % 2 == 1


def disulfide_potential(seq: str) -> float:
    """Potential disulfide pairs = floor(n_cys / 2). Empty -> 0.0.

    This is the single column written to the feature table. ``n_cys`` and
    ``cys_is_odd`` are exposed separately for callers that want them.
    """
    return float(n_cys(seq) // 2)


def disorder_fraction(seq: str) -> float:
    """Fraction of disorder-promoting residues {S,P,E,K,Q,G,R,D,A,N}. Empty -> 0.0."""
    s = _clean(seq)
    n = len(s)
    if n == 0:
        return 0.0
    return sum(1 for a in s if a in _DISORDER_PROMOTING) / n


def topology_helix_frac(seq: str) -> float:
    """Chou-Fasman predicted helix fraction of the design. Empty -> 0.0."""
    return chou_fasman_fractions(seq)[0]


def topology_strand_frac(seq: str) -> float:
    """Chou-Fasman predicted strand fraction of the design. Empty -> 0.0."""
    return chou_fasman_fractions(seq)[1]


def topology_loop_frac(seq: str) -> float:
    """Chou-Fasman predicted loop fraction of the design. Empty -> 0.0."""
    return chou_fasman_fractions(seq)[2]


def immunogenicity_proxy(seq: str) -> float:
    """Crude T-cell-epitope proxy: density of hydrophobic 9-mers.

    Counts sliding windows of length 9 whose mean Kyte-Doolittle hydropathy
    exceeds ``_IMMUNO_HYDRO_THRESHOLD`` (0.0), divided by sequence length. This
    is a PROXY: hydrophobic 9-mers are over-represented among MHC-II binding
    cores, so high density is a rough surrogate for immunogenic potential — it is
    NOT a real epitope predictor. Empty / too-short -> 0.0.
    """
    s = _clean(seq)
    n = len(s)
    if n < _IMMUNO_WINDOW:
        return 0.0
    kd = [_KYTE_DOOLITTLE.get(a, 0.0) for a in s]
    w = _IMMUNO_WINDOW
    window_sum = sum(kd[:w])
    hits = 1 if window_sum / w > _IMMUNO_HYDRO_THRESHOLD else 0
    for i in range(w, n):
        window_sum += kd[i] - kd[i - w]
        if window_sum / w > _IMMUNO_HYDRO_THRESHOLD:
            hits += 1
    return hits / n


# Ordered (column_name, function) pairs for the build script — single source of
# truth so the script and the module never drift.
BIO_FEATURE_FUNCS = (
    ("bio__aggregation_propensity", aggregation_propensity),
    ("bio__ptm_site_density", ptm_site_density),
    ("bio__phospho_site_density", phospho_site_density),
    ("bio__disulfide_potential", disulfide_potential),
    ("bio__disorder_fraction", disorder_fraction),
    ("bio__topology_helix_frac", topology_helix_frac),
    ("bio__topology_strand_frac", topology_strand_frac),
    ("bio__topology_loop_frac", topology_loop_frac),
    ("bio__immunogenicity_proxy", immunogenicity_proxy),
)


def compute_bio_features(seq: str) -> dict:
    """Compute all bio__ descriptors for a binder sequence as a flat dict."""
    return {name: fn(seq) for name, fn in BIO_FEATURE_FUNCS}
