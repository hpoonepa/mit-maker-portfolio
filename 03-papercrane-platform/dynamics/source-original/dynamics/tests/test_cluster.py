import pytest
from dynamics.cluster import cluster_pockets_across_frames, PocketSite
from dynamics.pockets import Pocket


def _p(x: float, y: float, z: float, vol: float = 100.0, drug: float = 0.5) -> Pocket:
    return Pocket(center=(x, y, z), volume=vol, druggability=drug, n_residues=20)


def test_single_persistent_pocket_clusters_to_one_site():
    frames = [
        [_p(0.0, 0.0, 0.0, vol=100)],
        [_p(0.5, 0.1, 0.0, vol=105)],
        [_p(-0.3, 0.0, 0.1, vol=95)],
    ]
    sites = cluster_pockets_across_frames(frames, distance_threshold=4.0)
    assert len(sites) == 1
    assert sites[0].persistence == pytest.approx(1.0)
    assert sites[0].mean_volume == pytest.approx(100.0, rel=0.05)
    assert sites[0].n_frames_present == 3


def test_two_distinct_pockets_cluster_separately():
    frames = [
        [_p(0, 0, 0), _p(20, 20, 20)],
        [_p(0.5, 0, 0), _p(20.1, 20, 20)],
    ]
    sites = cluster_pockets_across_frames(frames, distance_threshold=4.0)
    assert len(sites) == 2


def test_transient_pocket_gets_partial_persistence():
    frames = [
        [_p(0, 0, 0)],
        [_p(0, 0, 0)],
        [],
        [],
        [_p(0, 0, 0)],
    ]
    sites = cluster_pockets_across_frames(frames, distance_threshold=4.0)
    assert len(sites) == 1
    assert sites[0].persistence == pytest.approx(0.6)
    assert sites[0].n_frames_present == 3


def test_empty_frames_returns_empty_list():
    assert cluster_pockets_across_frames([[], [], []], distance_threshold=4.0) == []


def test_pocket_appears_at_most_once_per_frame_in_site():
    # if a frame has two pockets in the same cluster they count as one frame present
    frames = [
        [_p(0, 0, 0), _p(0.5, 0, 0)],
        [_p(0.1, 0, 0)],
    ]
    sites = cluster_pockets_across_frames(frames, distance_threshold=4.0)
    assert len(sites) == 1
    assert sites[0].n_frames_present == 2
