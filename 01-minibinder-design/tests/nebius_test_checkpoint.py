# Check saved campaign state, completed seeds, and resume behavior.
import json
from backends.nebius.checkpoint import CampaignState

def test_new_state_has_no_completed_seeds():
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    assert s.completed_seeds == []
    assert s.failed_seeds == []
    assert s.results == []

def test_pending_seeds_excludes_completed_and_failed():
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    s.completed_seeds = [0, 1]
    s.failed_seeds = [2]
    assert s.pending_seeds(list(range(5))) == [3, 4]

def test_record_success_appends_result_and_seed():
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    s.record_success(seed=3, csv_line="3,SEQ,85,0,0.8,0.9,0.7", output_dir="out/seed_003")
    assert 3 in s.completed_seeds
    assert s.results[-1]["seed"] == 3
    assert s.results[-1]["csv_line"].startswith("3,")

def test_record_success_is_idempotent_on_repeat_seed():
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    s.record_success(seed=1, csv_line="1,A", output_dir="out/seed_001")
    s.record_success(seed=1, csv_line="1,A", output_dir="out/seed_001")
    assert s.completed_seeds == [1]  # no duplicate seed

def test_record_failure_appends_failed_seed():
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    s.record_failure(seed=4, error="boom")
    assert 4 in s.failed_seeds

def test_save_then_load_roundtrips(tmp_path):
    path = tmp_path / "cp.json"
    s = CampaignState(campaign_id="t", image="img", total_seeds=5)
    s.record_success(seed=0, csv_line="0,SEQ,85,0,0.8,0.9,0.7", output_dir="out/seed_000")
    s.save(path)
    loaded = CampaignState.load(path)
    assert loaded.campaign_id == "t"
    assert loaded.completed_seeds == [0]
    assert loaded.results[0]["csv_line"].startswith("0,")

def test_load_missing_file_returns_none():
    assert CampaignState.load("/nonexistent/path/cp.json") is None
