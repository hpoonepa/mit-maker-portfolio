from nebius.candidates_5g51_v4 import CANDIDATES

def test_there_are_23_candidates():
    assert len(CANDIDATES) == 23

def test_each_candidate_is_seed_and_sequence():
    for seed, seq in CANDIDATES:
        assert isinstance(seed, int)
        assert isinstance(seq, str)
        assert len(seq) > 0
        assert set(seq).issubset(set("ACDEFGHIKLMNPQRSTVWY"))

def test_seeds_are_unique():
    seeds = [s for s, _ in CANDIDATES]
    assert len(seeds) == len(set(seeds))
