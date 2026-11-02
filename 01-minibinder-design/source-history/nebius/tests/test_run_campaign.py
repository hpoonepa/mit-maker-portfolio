import threading

from nebius import run_campaign
from nebius.checkpoint import CampaignState


class FakeRunner:
    """Stand-in for runner.run_one_job — records calls, fails configured seeds."""
    def __init__(self, fail_seeds=()):
        self.fail_seeds = set(fail_seeds)
        self.calls = []
        self._lock = threading.Lock()

    def run_one_job(self, host, image, seed, config_path, target_cif,
                    local_out_root, gpu_id=None):
        with self._lock:
            self.calls.append((seed, gpu_id))
        if seed in self.fail_seeds:
            raise RuntimeError(f"seed {seed} boom")
        return {"seed": seed, "csv_line": f"{seed},SEQ,85,0,0.8,0.9,0.7",
                "output_dir": f"out/seed_{seed:03d}"}


def _seeds(calls):
    return [s for s, _ in calls]


def test_seed_zero_gate_blocks_fanout_on_failure(tmp_path):
    fake = FakeRunner(fail_seeds={0})
    state = CampaignState(campaign_id="c", image="img", total_seeds=5)
    ok = run_campaign.run_loop(host="1.2.3.4", seeds=[0, 1, 2, 3, 4], state=state,
                               checkpoint_path=tmp_path / "cp.json",
                               local_out_root=tmp_path / "out", runner=fake)
    assert ok is False
    assert _seeds(fake.calls) == [0]
    assert 0 in state.failed_seeds


def test_happy_path_runs_all_seeds_and_checkpoints(tmp_path):
    fake = FakeRunner()
    state = CampaignState(campaign_id="c", image="img", total_seeds=3)
    ok = run_campaign.run_loop(host="1.2.3.4", seeds=[0, 1, 2], state=state,
                               checkpoint_path=tmp_path / "cp.json",
                               local_out_root=tmp_path / "out", runner=fake)
    assert ok is True
    assert _seeds(fake.calls) == [0, 1, 2]
    assert state.completed_seeds == [0, 1, 2]
    assert (tmp_path / "cp.json").exists()


def test_mid_run_failure_is_recorded_and_loop_continues(tmp_path):
    fake = FakeRunner(fail_seeds={2})
    state = CampaignState(campaign_id="c", image="img", total_seeds=4)
    ok = run_campaign.run_loop(host="1.2.3.4", seeds=[0, 1, 2, 3], state=state,
                               checkpoint_path=tmp_path / "cp.json",
                               local_out_root=tmp_path / "out", runner=fake)
    assert ok is True
    assert _seeds(fake.calls) == [0, 1, 2, 3]
    assert state.completed_seeds == [0, 1, 3]
    assert state.failed_seeds == [2]


def test_resume_skips_already_completed_seeds(tmp_path):
    fake = FakeRunner()
    state = CampaignState(campaign_id="c", image="img", total_seeds=4)
    state.completed_seeds = [0, 1]
    run_campaign.run_loop(host="1.2.3.4", seeds=[0, 1, 2, 3], state=state,
                          checkpoint_path=tmp_path / "cp.json",
                          local_out_root=tmp_path / "out", runner=fake)
    assert _seeds(fake.calls) == [2, 3]


def test_parallel_fanout_assigns_round_robin_gpus(tmp_path):
    """With max_parallel=4 and 9 seeds total, the gate runs first on GPU 0
    (sequential), then the remaining 8 seeds round-robin GPU ids 0..3."""
    fake = FakeRunner()
    state = CampaignState(campaign_id="c", image="img", total_seeds=9)
    ok = run_campaign.run_loop(host="1.2.3.4", seeds=list(range(9)), state=state,
                               checkpoint_path=tmp_path / "cp.json",
                               local_out_root=tmp_path / "out", runner=fake,
                               max_parallel=4)
    assert ok is True
    assert set(state.completed_seeds) == set(range(9))
    # The gate is seed 0 with gpu_id=0 and was first.
    assert fake.calls[0] == (0, 0)
    # The remaining 8 seeds (1..8) get gpu_ids cycled 0,1,2,3,0,1,2,3 based on
    # their index in the remaining list (assignment is deterministic before
    # submission, even if completion order is not).
    remaining_calls = {seed: gpu for seed, gpu in fake.calls[1:]}
    expected = {1: 0, 2: 1, 3: 2, 4: 3, 5: 0, 6: 1, 7: 2, 8: 3}
    assert remaining_calls == expected


def test_parallel_fanout_continues_through_failures(tmp_path):
    fake = FakeRunner(fail_seeds={3, 5})
    state = CampaignState(campaign_id="c", image="img", total_seeds=6)
    ok = run_campaign.run_loop(host="1.2.3.4", seeds=list(range(6)), state=state,
                               checkpoint_path=tmp_path / "cp.json",
                               local_out_root=tmp_path / "out", runner=fake,
                               max_parallel=4)
    assert ok is True
    assert sorted(state.completed_seeds) == [0, 1, 2, 4]
    assert sorted(state.failed_seeds) == [3, 5]
