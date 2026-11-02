import copy
import json

import pytest

from scorer.evidence_audit import canonical_json
from scorer.evidence_benchmark import INPUT_VERSION, evaluate_benchmark, main


@pytest.fixture
def benchmark():
    methods = [
        {"id": mid, "producer": mid, "version": "1", "evidence_family": mid,
         "higher_is_better": True, "units": "unitless", "settings": {}}
        for mid in ("baseline", "alternative")
    ]
    campaigns = []
    for index in range(3):
        candidates = [
            {"id": cid, "origin": "fixture", "provenance": "synthetic", "scores": {
                "baseline": {"status": "observed", "value": base},
                "alternative": {"status": "observed", "value": alt},
            }} for cid, base, alt in [("A", 3, 2), ("B", 2, 3), ("C", 1, 1)]
        ]
        campaigns.append({
            "evaluation_group": f"group-{index}",
            "evidence": {"schema_version": "evidence-audit-input.v1", "campaign_id": f"campaign-{index}",
                         "data_kind": "synthetic_demo", "methods": copy.deepcopy(methods), "candidates": candidates},
            "outcomes": {"A": index == 0, "B": index != 0, "C": False},
        })
    return {"schema_version": INPUT_VERSION, "benchmark_id": "fixture", "baseline_method_id": "baseline",
            "development_groups": ["development"], "campaigns": campaigns}


def test_fixed_budget_and_paired_group_macro(benchmark):
    report = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)
    assert report["comparisons"]["baseline"]["group_macro_precision_at_k"] == pytest.approx(1 / 3)
    alternative = report["comparisons"]["alternative"]
    assert alternative["group_macro_precision_at_k"] == pytest.approx(2 / 3)
    assert alternative["versus_baseline"]["mean_delta"] == pytest.approx(1 / 3)
    assert alternative["versus_baseline"]["groups"] == 3


def test_cutoff_ties_use_expected_hits_and_full_bounds(benchmark):
    evidence = benchmark["campaigns"][0]["evidence"]
    evidence["candidates"][1]["scores"]["baseline"]["value"] = 3
    metrics = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)["campaigns"][0]["metrics"]["baseline"]
    assert metrics["precision_at_k"] == 0.5
    assert metrics["precision_tie_bounds"] == {"lower": 0, "upper": 1}
    assert metrics["ndcg_at_k"] == 0.5
    assert metrics["cutoff_tie"] is True


def test_unknown_outcome_excludes_campaign_without_reordering(benchmark):
    benchmark["campaigns"][0]["outcomes"]["A"] = None
    report = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)
    campaign = report["campaigns"][0]
    assert campaign["common_cohort_size"] == 3
    assert campaign["metrics"] == {}
    assert campaign["exclusion_reasons"] == ["unknown_outcomes_in_common_cohort"]
    assert report["summary"]["primary_campaigns"] == 2


def test_unknown_outside_cohort_does_not_become_a_negative(benchmark):
    campaign = benchmark["campaigns"][0]
    campaign["evidence"]["candidates"][2]["scores"]["baseline"] = {"status": "missing", "reason": "unavailable"}
    campaign["outcomes"]["C"] = None
    result = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)["campaigns"][0]
    assert result["primary_eligible"] is True
    assert result["excluded_from_cohort"] == 1


def test_zero_positive_campaign_retained_without_invented_recall(benchmark):
    benchmark["campaigns"][0]["outcomes"] = {"A": False, "B": False, "C": False}
    campaign = evaluate_benchmark(benchmark, top_k=2, bootstrap_samples=100)["campaigns"][0]
    assert campaign["primary_eligible"] is True
    for metrics in campaign["metrics"].values():
        assert metrics["precision_at_k"] == 0
        assert metrics["recall_at_k"] is None and metrics["ndcg_at_k"] is None


def test_short_cohort_is_not_given_a_smaller_primary_k(benchmark):
    report = evaluate_benchmark(benchmark, top_k=4, bootstrap_samples=100)
    assert report["summary"]["primary_campaigns"] == 0
    assert all(c["exclusion_reasons"] == ["common_cohort_smaller_than_fixed_k"] for c in report["campaigns"])
    assert report["comparisons"]["baseline"]["group_macro_precision_at_k"] is None


def test_campaign_replication_within_group_does_not_inflate_effective_n(benchmark):
    duplicate = copy.deepcopy(benchmark["campaigns"][0])
    duplicate["evidence"]["campaign_id"] = "repeated-campaign"
    benchmark["campaigns"].append(duplicate)
    report = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)
    assert report["summary"]["primary_campaigns"] == 4
    assert report["comparisons"]["alternative"]["versus_baseline"]["groups"] == 3
    assert report["comparisons"]["alternative"]["group_macro_precision_at_k"] == pytest.approx(2 / 3)


def test_single_group_does_not_receive_sampling_interval(benchmark):
    for campaign in benchmark["campaigns"]:
        campaign["evaluation_group"] = "one-group"
    result = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)
    assert result["comparisons"]["alternative"]["versus_baseline"]["interval_95"] is None


def test_agreement_does_not_automatically_mean_correctness(benchmark):
    for campaign in benchmark["campaigns"]:
        for candidate in campaign["evidence"]["candidates"]:
            candidate["scores"]["alternative"] = copy.deepcopy(candidate["scores"]["baseline"])
        campaign["outcomes"] = {"A": False, "B": True, "C": False}
    report = evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100)
    assert all(c["agreement_diagnostic"]["observed_positive_fraction"] == 0 for c in report["campaigns"])


def test_reordering_records_does_not_change_hash_or_bootstrap(benchmark):
    before = canonical_json(evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100, seed=4))
    benchmark["campaigns"].reverse()
    for campaign in benchmark["campaigns"]:
        campaign["evidence"]["methods"].reverse()
        campaign["evidence"]["candidates"].reverse()
    after = canonical_json(evaluate_benchmark(benchmark, top_k=1, bootstrap_samples=100, seed=4))
    assert after == before


def test_development_overlap_rejected(benchmark):
    benchmark["development_groups"].append("group-0")
    with pytest.raises(ValueError, match="overlaps"):
        evaluate_benchmark(benchmark)


def test_method_drift_rejected(benchmark):
    benchmark["campaigns"][1]["evidence"]["methods"][0]["version"] = "different"
    with pytest.raises(ValueError, match="definitions differ"):
        evaluate_benchmark(benchmark)


@pytest.mark.parametrize("value", ["True", 1, 0, [], {}])
def test_outcome_types_are_strict(benchmark, value):
    benchmark["campaigns"][0]["outcomes"]["A"] = value
    with pytest.raises(ValueError, match="true, false, or null"):
        evaluate_benchmark(benchmark)


def test_duplicate_campaign_and_missing_outcome_rejected(benchmark):
    benchmark["campaigns"].append(copy.deepcopy(benchmark["campaigns"][0]))
    with pytest.raises(ValueError, match="duplicate campaign"):
        evaluate_benchmark(benchmark)
    benchmark["campaigns"].pop()
    del benchmark["campaigns"][0]["outcomes"]["A"]
    with pytest.raises(ValueError, match="missing fields"):
        evaluate_benchmark(benchmark)


def test_demo_and_research_cannot_mix(benchmark):
    benchmark["campaigns"][0]["evidence"]["data_kind"] = "research"
    with pytest.raises(ValueError, match="cannot be mixed"):
        evaluate_benchmark(benchmark)


def test_cli_writes_finite_json_and_preserves_existing_output(benchmark, tmp_path):
    source, dest = tmp_path / "input.json", tmp_path / "output.json"
    source.write_text(canonical_json(benchmark))
    args = [str(source), "--top-k", "1", "--bootstrap-samples", "100", "--output", str(dest)]
    assert main(args) == 0
    original = dest.read_bytes()
    assert json.loads(original)["summary"]["primary_evaluation_groups"] == 3
    assert b"NaN" not in original and b"Infinity" not in original
    assert main(args) == 2
    assert dest.read_bytes() == original
