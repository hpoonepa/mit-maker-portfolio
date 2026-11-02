import pytest
from dynamics.cluster import PocketSite
from dynamics.pockets import Pocket
from dynamics.cryptic import call_cryptic_pockets, CrypticCall


def _site(x, y, z, persistence=0.8, mean_volume=200.0):
    return PocketSite(
        centroid=(x, y, z),
        persistence=persistence,
        n_frames_present=int(persistence * 10),
        total_frames=10,
        mean_volume=mean_volume,
        mean_druggability=0.5,
    )


def _apo_pocket(x, y, z, vol=200.0):
    return Pocket(center=(x, y, z), volume=vol, druggability=0.5, n_residues=20)


def test_site_far_from_any_apo_pocket_is_cryptic():
    sites = [_site(0, 0, 0, persistence=0.9, mean_volume=180)]
    apo = [_apo_pocket(20, 20, 20, vol=200)]
    calls = call_cryptic_pockets(sites, apo, persistence_threshold=0.2)
    assert len(calls) == 1
    assert isinstance(calls[0], CrypticCall)
    assert calls[0].site is sites[0]


def test_site_matching_apo_pocket_not_cryptic():
    sites = [_site(0, 0, 0, persistence=0.9, mean_volume=200)]
    apo = [_apo_pocket(0.5, 0, 0, vol=190)]
    calls = call_cryptic_pockets(sites, apo, persistence_threshold=0.2)
    assert calls == []


def test_below_persistence_threshold_excluded():
    sites = [_site(0, 0, 0, persistence=0.1, mean_volume=200)]
    apo = [_apo_pocket(20, 20, 20)]
    calls = call_cryptic_pockets(sites, apo, persistence_threshold=0.2)
    assert calls == []


def test_apo_pocket_much_smaller_than_ensemble_site_still_cryptic():
    sites = [_site(0, 0, 0, persistence=0.7, mean_volume=300)]
    apo = [_apo_pocket(0.5, 0, 0, vol=30)]
    calls = call_cryptic_pockets(
        sites, apo, persistence_threshold=0.2, volume_ratio_threshold=0.3
    )
    assert len(calls) == 1


def test_score_increases_with_persistence_and_apo_absence():
    far_sites = [_site(0, 0, 0, persistence=0.95)]
    near_sites = [_site(0, 0, 0, persistence=0.3)]
    apo = [_apo_pocket(50, 50, 50)]
    far_calls = call_cryptic_pockets(far_sites, apo, persistence_threshold=0.2)
    near_calls = call_cryptic_pockets(near_sites, apo, persistence_threshold=0.2)
    assert far_calls[0].score > near_calls[0].score
