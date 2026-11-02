# Check that candidate validation records failures and continues with the next sequence.
from backends.nebius import run_validation
from backends.nebius.checkpoint import CampaignState


class FakeRunner:
    def __init__(self, fail_seeds=()):
        self.fail_seeds = set(fail_seeds)
        self.calls = []

    def run_validation_job(self, host, image, seed, sequence, candidate_id, local_out_root):
        self.calls.append((seed, sequence))
        if seed in self.fail_seeds:
            raise RuntimeError("boom")
        return {"seed": seed, "csv_line": f"{seed},0.8,0.7,0.6,0.65,0.6",
                "output_dir": f"out/seed_{seed:03d}"}


def test_runs_every_candidate_with_its_sequence(tmp_path):
    candidates = [(6, "MVEEM"), (1, "AAAAA"), (17, "CCCCC")]
    fake = FakeRunner()
    state = CampaignState(campaign_id="v", image="img", total_seeds=3)
    run_validation.run_loop(host="1.2.3.4", candidates=candidates, state=state,
                            checkpoint_path=tmp_path / "cp.json",
                            local_out_root=tmp_path / "out", runner=fake)
    assert [c[0] for c in fake.calls] == [6, 1, 17]
    assert "MVEEM" in fake.calls[0][1]
    assert state.completed_seeds == [6, 1, 17]


def test_failed_candidate_recorded_loop_continues(tmp_path):
    candidates = [(6, "MVEEM"), (1, "AAAAA")]
    fake = FakeRunner(fail_seeds={6})
    state = CampaignState(campaign_id="v", image="img", total_seeds=2)
    run_validation.run_loop(host="1.2.3.4", candidates=candidates, state=state,
                            checkpoint_path=tmp_path / "cp.json",
                            local_out_root=tmp_path / "out", runner=fake)
    assert state.failed_seeds == [6]
    assert state.completed_seeds == [1]
