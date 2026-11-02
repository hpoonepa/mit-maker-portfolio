"""Build the labeled FEATURE TABLE (Tracks 1+2: parse existing metrics +
compute cheap CPU sequence features) -> data/processed/labeled_features.csv.

ONE ROW PER DEDUPED LABELED DESIGN. Reuses scripts/combine_datasets.py loaders,
target normalization, replicate-majority resolution, expression conditioning,
and dedup-by-sequence + cross-source-conflict drop.

Tracks implemented here (CPU only, no GPU / Boltz / DSSP):
  TIER 1/2 — parse native metric columns from each source where present;
             leave EMPTY where a source lacks the metric (a later Boltz /
             Colab backfill job fills the gaps).
  TIER 3   — cheap binder-sequence features computed locally in pure Python.

NOT done here (deferred to a later task — they need structures + DSSP):
  target-side structural features (epitope planarity, pocket volume,
  secondary-structure fractions, druggability, ...).
"""
import csv
import json
import os
import sys

# Allow `python3 data/features.py` as well as `python3 -m data.features`.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pc_contracts.metrics import canonical_metric_key

# ---------------------------------------------------------------------------
# Reuse the prototype's loaders / normalization. We import the helpers rather
# than duplicating them so behaviour cannot drift from combine_datasets.py.
# ---------------------------------------------------------------------------
import importlib.util

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location(
    "combine_datasets", os.path.join(_SCRIPTS_DIR, "combine_datasets.py")
)
combine_datasets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(combine_datasets)

norm_target = combine_datasets.norm_target
to_bool = combine_datasets.to_bool
_majority = combine_datasets._majority

RAW = os.path.join(os.path.dirname(__file__), "raw")
OUT = os.path.join(os.path.dirname(__file__), "processed", "labeled_features.csv")

csv.field_size_limit(10 ** 7)

# Ingest source allowlist — discipline guard at the table boundary.
INGEST_SOURCE_ALLOWLIST = frozenset({"overath", "bindcraft", "proteinbase"})


# ===========================================================================
# TIER 3 — cheap sequence features (pure Python, no external libraries)
# ===========================================================================
# Average residue masses (monomer mass minus one water), Da.
_AA_RESIDUE_WEIGHT = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}
_WATER = 18.01528

_HYDROPHOBIC = frozenset("AILMFWVP")
_AROMATIC = frozenset("FWY")
_POSITIVE = frozenset("KR")
_NEGATIVE = frozenset("DE")

# pKa values for a simple isoelectric-point estimate (EMBOSS-style).
_PKA_NTERM = 9.69
_PKA_CTERM = 2.34
_PKA_SIDE = {  # positive (basic) and negative (acidic) ionizable side chains
    "K": (10.5, +1), "R": (12.4, +1), "H": (6.0, +1),
    "D": (3.65, -1), "E": (4.25, -1), "C": (8.3, -1), "Y": (10.7, -1),
}


def seq_length(seq: str) -> int:
    return len(seq or "")


def molecular_weight(seq: str) -> float:
    seq = (seq or "").upper()
    if not seq:
        return 0.0
    total = sum(_AA_RESIDUE_WEIGHT.get(a, 0.0) for a in seq)
    return total + _WATER


def cysteine_fraction(seq: str) -> float:
    seq = (seq or "").upper()
    if not seq:
        return 0.0
    return seq.count("C") / len(seq)


def hydrophobic_fraction(seq: str) -> float:
    seq = (seq or "").upper()
    if not seq:
        return 0.0
    return sum(1 for a in seq if a in _HYDROPHOBIC) / len(seq)


def aromatic_fraction(seq: str) -> float:
    seq = (seq or "").upper()
    if not seq:
        return 0.0
    return sum(1 for a in seq if a in _AROMATIC) / len(seq)


def net_charge_ph7(seq: str) -> float:
    seq = (seq or "").upper()
    if not seq:
        return 0.0
    pos = sum(1 for a in seq if a in _POSITIVE)
    neg = sum(1 for a in seq if a in _NEGATIVE)
    return float(pos - neg)


def _net_charge_at_ph(seq: str, ph: float) -> float:
    charge = 1.0 / (1.0 + 10 ** (ph - _PKA_NTERM))   # N-term, positive
    charge -= 1.0 / (1.0 + 10 ** (_PKA_CTERM - ph))  # C-term, negative
    for aa in seq:
        info = _PKA_SIDE.get(aa)
        if info is None:
            continue
        pka, sign = info
        if sign > 0:
            charge += 1.0 / (1.0 + 10 ** (ph - pka))
        else:
            charge -= 1.0 / (1.0 + 10 ** (pka - ph))
    return charge


def isoelectric_point(seq: str) -> float:
    """Estimate pI by bisection on the Henderson-Hasselbalch net-charge curve.

    Simple EMBOSS-style estimate; reused only when a source lacks a native
    isoelectric_point value.
    """
    seq = (seq or "").upper()
    if not seq:
        return 7.0
    lo, hi = 0.0, 14.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _net_charge_at_ph(seq, mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ===========================================================================
# Canonical column names for the locked v1 feature list
# ===========================================================================
_COL_MIN_IPSAE = canonical_metric_key("boltz2_min_ipsae")          # TIER 1
_COL_LIS = canonical_metric_key("boltz2_lis")                      # TIER 1
_COL_IPTM = canonical_metric_key("boltz2_iptm")                   # TIER 1 (iptm family)
_COL_ACTIFPTM = canonical_metric_key("actifptm")                  # TIER 2
_COL_INTERFACE_RES = canonical_metric_key("interface_residues")  # TIER 2
_COL_COMPLEX_IPLDDT = canonical_metric_key("boltz2_complex_iplddt")  # TIER 2
_COL_MPNN = canonical_metric_key("proteinmpnn_score")            # TIER 3 partial
_COL_ESMFOLD_PLDDT = canonical_metric_key("esmfold_plddt")       # TIER 3 partial

# Non-prefixed feature/identity columns.
_IDENTITY_COLS = ["source", "target", "sequence", "binds", "assay", "license", "was_tested"]
_NATIVE_IPSAE_COLS = ["ipsae_min_native", "ipsae_source"]
_NON_METRIC_PARSE_COLS = ["shape_complementarity", "rmsd_binder"]
_SEQ_FEATURE_COLS = [
    "seq_length", "molecular_weight", "isoelectric_point",
    "cysteine_fraction", "hydrophobic_fraction", "aromatic_fraction",
    "net_charge_ph7",
]
_METRIC_COLS = [
    _COL_MIN_IPSAE, _COL_LIS, _COL_IPTM, _COL_ACTIFPTM,
    _COL_INTERFACE_RES, _COL_COMPLEX_IPLDDT, _COL_MPNN, _COL_ESMFOLD_PLDDT,
]


def feature_table_columns() -> list[str]:
    """Locked v1 column order for the labeled feature table."""
    return (
        _IDENTITY_COLS
        + [_COL_MIN_IPSAE]
        + _NATIVE_IPSAE_COLS
        + _NON_METRIC_PARSE_COLS
        + [_COL_LIS, _COL_IPTM, _COL_ACTIFPTM,
           _COL_INTERFACE_RES, _COL_COMPLEX_IPLDDT,
           _COL_MPNN, _COL_ESMFOLD_PLDDT]
        + _SEQ_FEATURE_COLS
    )


# ===========================================================================
# Row construction
# ===========================================================================
def _f(v):
    """Render a parsed metric value for CSV: float passthrough, empty stays ''."""
    if v is None or v == "":
        return ""
    return v


def _license_for(source: str, target: str) -> str:
    if source == "proteinbase" and (target or "").upper() == "NIPAH":
        return "unclear"
    return "open"


def _assay_for(rec: dict) -> str:
    source = rec["source"]
    if source in ("overath", "bindcraft"):
        return source
    # proteinbase: use its experimental binding assay if known, else "proteinbase"
    return rec.get("assay") or "proteinbase"


def build_feature_rows(deduped: list[dict]) -> list[dict]:
    """Turn deduped labeled design records into feature-table rows.

    Each input record must carry at least source/target/sequence/binds and may
    carry pre-parsed native metric values under their canonical column names
    plus ipsae_min_native / ipsae_source / shape_complementarity / rmsd_binder.
    """
    rows = []
    for rec in deduped:
        source = rec["source"]
        assert source in INGEST_SOURCE_ALLOWLIST, (
            f"source {source!r} not in ingest allowlist {sorted(INGEST_SOURCE_ALLOWLIST)}"
        )
        seq = rec["sequence"]
        target = rec["target"]
        row = {
            "source": source,
            "target": target,
            "sequence": seq,
            "binds": rec["binds"],
            "assay": _assay_for(rec),
            "license": _license_for(source, target),
            "was_tested": 1,
            # TIER 1
            _COL_MIN_IPSAE: _f(rec.get(_COL_MIN_IPSAE)),
            "ipsae_min_native": _f(rec.get("ipsae_min_native")),
            "ipsae_source": rec.get("ipsae_source") or "none",
            "shape_complementarity": _f(rec.get("shape_complementarity")),
            "rmsd_binder": _f(rec.get("rmsd_binder")),
            _COL_LIS: _f(rec.get(_COL_LIS)),
            _COL_IPTM: _f(rec.get(_COL_IPTM)),
            # TIER 2
            _COL_ACTIFPTM: _f(rec.get(_COL_ACTIFPTM)),
            _COL_INTERFACE_RES: _f(rec.get(_COL_INTERFACE_RES)),
            _COL_COMPLEX_IPLDDT: _f(rec.get(_COL_COMPLEX_IPLDDT)),
            # TIER 3 partial-parse
            _COL_MPNN: _f(rec.get(_COL_MPNN)),
            _COL_ESMFOLD_PLDDT: _f(rec.get(_COL_ESMFOLD_PLDDT)),
            # TIER 3 computed sequence features
            "seq_length": seq_length(seq),
            "molecular_weight": round(molecular_weight(seq), 4),
            "isoelectric_point": (
                rec.get("isoelectric_point")
                if rec.get("isoelectric_point") not in (None, "")
                else round(isoelectric_point(seq), 4)
            ),
            "cysteine_fraction": round(cysteine_fraction(seq), 6),
            "hydrophobic_fraction": round(hydrophobic_fraction(seq), 6),
            "aromatic_fraction": round(aromatic_fraction(seq), 6),
            "net_charge_ph7": net_charge_ph7(seq),
        }
        rows.append(row)
    return rows


# ===========================================================================
# Source loaders with native-metric parsing (extend combine_datasets loaders)
# ===========================================================================
def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_overath():
    rows = []
    with open(os.path.join(RAW, "overath.csv"), newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("A_seq") or "").strip().upper()
            b = to_bool(r.get("binder"))
            t = norm_target(r.get("target_id"))
            if not (seq and t and b is not None):
                continue
            # native ipSAE: prefer boltz1, else af3
            ipsae = _num(r.get("boltz1_ipSAE_min"))
            ipsae_src = "boltz1"
            if ipsae is None:
                ipsae = _num(r.get("af3_ipSAE_min"))
                ipsae_src = "af3" if ipsae is not None else "none"
            iptm = _num(r.get("colab_iptm_avg"))
            if iptm is None:
                iptm = _num(r.get("boltz1_iptm_avg"))
            rows.append({
                "source": "overath", "target": t, "sequence": seq, "binds": b,
                "ipsae_min_native": ipsae, "ipsae_source": ipsae_src,
                "rmsd_binder": _num(r.get("af2_binder_aligned_rmsd")),
                _COL_IPTM: iptm,
                _COL_ACTIFPTM: _num(r.get("colab_actifptm_avg")),
            })
    return rows


def load_bindcraft():
    rows = []
    with open(os.path.join(RAW, "bindcraft.csv"), newline="", encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("Sequence") or "").strip().upper()
            b = to_bool(r.get("Binding"))
            t = norm_target(r.get("Target"))
            if not (seq and t and b is not None):
                continue
            rows.append({
                "source": "bindcraft", "target": t, "sequence": seq, "binds": b,
                "ipsae_source": "none",
                "shape_complementarity": _num(r.get("Average_ShapeComplementarity")),
                "rmsd_binder": _num(r.get("Average_Binder_RMSD")),
                _COL_IPTM: _num(r.get("Average_i_pTM")),
                _COL_INTERFACE_RES: _num(r.get("Average_n_InterfaceResidues")),
            })
    return rows


def _proteinbase_comp_map(evals):
    """Collect computational metric values + binding assay indicator."""
    comp = {}
    assay = None
    for e in evals:
        if not isinstance(e, dict):
            continue
        et = e.get("type")
        if et == "computational":
            comp[e.get("metric")] = e.get("value")
        elif et == "experimental":
            m = e.get("metric")
            if m == "spr_kinetic_curves" and assay is None:
                assay = "spr"
            elif m == "bli_kinetic_curves" and assay is None:
                assay = "bli"
    return comp, assay


def load_proteinbase():
    rows = []
    with open(os.path.join(RAW, "proteinbase.csv"), newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("sequence") or "").strip().upper()
            ev = r.get("evaluations", "")
            if not seq or not ev or ev in ("[]", "null"):
                continue
            try:
                evals = json.loads(ev)
            except Exception:
                continue
            binding_bools, expressed_bools, target = [], [], None
            for e in evals:
                if not isinstance(e, dict) or e.get("type") != "experimental":
                    continue
                m = e.get("metric")
                if m == "binding":
                    b = to_bool(e.get("value"))
                    if b is not None:
                        binding_bools.append(b)
                        if target is None and e.get("target"):
                            target = norm_target(e.get("target"))
                elif m == "expressed":
                    eb = to_bool(e.get("value"))
                    if eb is not None:
                        expressed_bools.append(eb)
            if target is None:
                for e in evals:
                    if isinstance(e, dict) and e.get("target"):
                        target = norm_target(e.get("target"))
                        break
            expressed = _majority(expressed_bools, tie_true=True) if expressed_bools else True
            if not expressed:
                continue
            binds = _majority(binding_bools, tie_true=True)
            if not (seq and target and binds is not None):
                continue
            comp, assay = _proteinbase_comp_map(evals)
            rows.append({
                "source": "proteinbase", "target": target, "sequence": seq,
                "binds": binds, "assay": assay,
                "ipsae_source": "boltz2" if comp.get("boltz2_min_ipsae") is not None else "none",
                _COL_MIN_IPSAE: comp.get("boltz2_min_ipsae"),
                "shape_complementarity": comp.get("shape_complimentarity_boltz2_binder_ss"),
                _COL_LIS: comp.get("boltz2_lis"),
                _COL_IPTM: comp.get("boltz2_iptm"),
                _COL_INTERFACE_RES: comp.get("interface_residues"),
                _COL_COMPLEX_IPLDDT: comp.get("boltz2_complex_iplddt"),
                _COL_MPNN: comp.get("proteinmpnn_score"),
                _COL_ESMFOLD_PLDDT: comp.get("esmfold_plddt"),
                "isoelectric_point": comp.get("isoelectric_point"),
            })
    return rows


# Per-source priority for dedup (overath > proteinbase > bindcraft).
_METRIC_KEYS_TO_MERGE = (
    _COL_MIN_IPSAE, _COL_LIS, _COL_IPTM, _COL_ACTIFPTM,
    _COL_INTERFACE_RES, _COL_COMPLEX_IPLDDT, _COL_MPNN, _COL_ESMFOLD_PLDDT,
    "ipsae_min_native", "shape_complementarity", "rmsd_binder",
    "isoelectric_point",
)


def dedup_records(over, prot, bind):
    """Dedup by sequence; conflicting label across sources -> DROP + count.
    Identity/target taken from highest-priority source; metric values merged
    (priority-source value wins, then fill gaps from others)."""
    import collections
    grouped = collections.defaultdict(list)
    for r in over + prot + bind:  # priority order preserved
        grouped[r["sequence"]].append(r)
    combined, conflicts = [], 0
    for seq, recs in grouped.items():
        labels = {rec["binds"] for rec in recs}
        if len(labels) > 1:
            conflicts += 1
            continue
        keep = dict(recs[0])  # priority source provides source/target/assay/ipsae_source
        for rec in recs[1:]:
            for k in _METRIC_KEYS_TO_MERGE:
                if keep.get(k) in (None, "") and rec.get(k) not in (None, ""):
                    keep[k] = rec[k]
        combined.append(keep)
    return combined, conflicts


def build_table():
    over, prot, bind = load_overath(), load_proteinbase(), load_bindcraft()
    combined, conflicts = dedup_records(over, prot, bind)
    rows = build_feature_rows(combined)
    return rows, conflicts


def write_table(rows, out=OUT):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cols = feature_table_columns()
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return out


def main():
    import collections
    rows, conflicts = build_table()
    write_table(rows)
    cols = feature_table_columns()
    pos = sum(1 for r in rows if r["binds"])
    neg = len(rows) - pos
    targets = {r["target"] for r in rows}
    per_source = collections.Counter(r["source"] for r in rows)
    n_canon_ipsae = sum(1 for r in rows if r[_COL_MIN_IPSAE] != "")
    n_native_ipsae = sum(1 for r in rows if r["ipsae_min_native"] != "")
    coverage = {c: sum(1 for r in rows if str(r.get(c, "")) != "") for c in cols}

    print("=" * 60)
    print("LABELED FEATURE TABLE")
    print("=" * 60)
    print(f"total rows           : {len(rows)}")
    print(f"  positives          : {pos}")
    print(f"  negatives          : {neg}")
    print(f"distinct targets     : {len(targets)}")
    print(f"label conflicts dropped: {conflicts}")
    print(f"per-source           : {dict(per_source)}")
    print(f"non-empty {_COL_MIN_IPSAE}: {n_canon_ipsae}")
    print(f"non-empty ipsae_min_native      : {n_native_ipsae}")
    print("\nper-column non-empty coverage:")
    for c in cols:
        print(f"   {c:38s} {coverage[c]:6d}")
    print(f"\nwrote {OUT}")
    print("\nNOTE: target-side STRUCTURAL features (DSSP secondary structure, "
          "epitope planarity, pocket volume, druggability) are DEFERRED — "
          "they require target structures + DSSP and are a later task.")


if __name__ == "__main__":
    main()
