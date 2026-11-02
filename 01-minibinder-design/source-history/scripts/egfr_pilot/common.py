"""Small shared I/O and comparison rules; no model imports."""
import hashlib
import json
import math
from pathlib import Path

PINS = {"bindcraft2": "a8d0f2002df373842b86a3c20c5a060c5cfdf980",
        "mosaic": "b94b9d4eb9907a700a6d78ed2d29d3704c5df46c"}
AA = set("ACDEFGHIKLMNPQRSTVWY")


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sequence_id(sequence):
    if not 10 <= len(sequence) <= 250 or not set(sequence) <= AA:
        raise ValueError("Expected a single standard-amino-acid chain of length 10–250")
    return hashlib.sha256(sequence.encode()).hexdigest()[:20]


def numeric(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Non-finite metric")
    return value


def classify(result, seeds):
    """Exploratory structure gate, NEVER a pH or experimental binding label."""
    mono = result.get("monomer", {})
    if mono.get("plddt", 0) < .8:
        return False
    needed = math.ceil(2 * seeds / 3)
    for species in ("human", "mouse"):
        runs = result.get(species, [])
        if len(runs) != seeds or len({r['seed'] for r in runs}) != seeds:
            return False
        passing = sum(r.get("status") == "ok" and r.get("iptm", 0) >= .65
                      and r.get("binder_plddt", 0) >= .75
                      and r.get("interface_pae", 99) <= 10
                      and r.get("hotspot_contact", False) for r in runs)
        if passing < needed:
            return False
    return True


def sequence_clusters(sequences, threshold=.7):
    """Greedy clusters based on sequence identity."""
    from Bio.Align import PairwiseAligner
    aligner = PairwiseAligner(mode="global", match_score=1, mismatch_score=0,
                             open_gap_score=-1, extend_gap_score=-.1)
    representatives = []
    for seq in sorted(set(sequences)):
        def identity(other):
            a = aligner.align(seq, other)[0]
            matches = sum(seq[i] == other[j] for left, right in zip(*a.aligned)
                          for i, j in zip(range(*left), range(*right)))
            return matches / max(len(seq), len(other))
        if not any(identity(rep) >= threshold for rep in representatives):
            representatives.append(seq)
    return len(representatives)
