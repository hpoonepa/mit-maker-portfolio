from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from html.parser import HTMLParser

import pytest

from scorer.evidence_audit import INPUT_VERSION, build_audit, canonical_json
from scorer.evidence_audit_cli import export_bundle, load_input, main, render_csv, render_html


@pytest.fixture
def evidence():
    methods = [
        {"id": "a", "producer": "engine-a", "version": "1", "evidence_family": "family-a",
         "higher_is_better": True, "units": "unitless", "settings": {}},
        {"id": "b", "producer": "engine-b", "version": "2", "evidence_family": "family-b",
         "higher_is_better": False, "units": "unitless", "settings": {"seed": 0}},
    ]
    candidates = [
        {"id": cid, "origin": "fixture", "provenance": "recorded", "scores": {
            "a": {"status": "observed", "value": a}, "b": {"status": "observed", "value": b},
        }} for cid, a, b in [("A", 9, 1), ("B", 8, 3), ("C", 7, 2), ("D", 6, 4)]
    ]
    return {"schema_version": INPUT_VERSION, "campaign_id": "example", "data_kind": "research",
            "methods": methods, "candidates": candidates}


def by_id(report):
    return {c["id"]: c for c in report["candidates"]}


def test_direction_aware_boundary_disagreement(evidence):
    report = build_audit(evidence, top_k=2)
    rows = by_id(report)
    assert rows["A"]["status"] == "consistently_in_top_k"
    assert rows["B"]["status"] == rows["C"]["status"] == "boundary_ambiguous"
    assert rows["D"]["status"] == "consistently_outside_top_k"
    assert rows["B"]["rank_envelope"] == {"best": 2, "worst": 3}
    assert report["method_agreement"][0]["top_k_jaccard"] == pytest.approx(1 / 3)


def test_ties_at_cutoff_are_not_broken_by_candidate_id(evidence):
    evidence["candidates"][1]["scores"]["a"]["value"] = 9
    report = build_audit(evidence, top_k=1)
    assert by_id(report)["A"]["rank_intervals"]["a"] == {"best": 1, "worst": 2}
    assert by_id(report)["A"]["status"] == "boundary_ambiguous"
    assert report["method_agreement"][0]["top_k_jaccard"] is None
    assert report["method_agreement"][0]["unavailable_reason"] == "cutoff_tie"


def test_ties_inside_shortlist_do_not_invalidate_membership(evidence):
    evidence["candidates"][1]["scores"]["a"]["value"] = 9
    report = build_audit(evidence, top_k=2)
    assert by_id(report)["A"]["status"] == "consistently_in_top_k"
    assert report["method_agreement"][0]["top_k_jaccard"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("status", ["missing", "failed", "not_applicable"])
def test_incomplete_evidence_is_excluded_from_every_method_not_zero_filled(evidence, status):
    evidence["candidates"][0]["scores"]["b"] = {"status": status, "reason": "fixture omission"}
    report = build_audit(evidence, top_k=1)
    rows = by_id(report)
    assert rows["A"]["status"] == "not_comparable"
    assert rows["A"]["rank_envelope"] is None
    assert rows["A"]["rank_intervals"] == {}
    assert rows["A"]["scores"]["b"]["status"] == status
    assert rows["B"]["rank_intervals"]["a"] == {"best": 1, "worst": 1}
    assert report["summary"]["comparable_candidates"] == 3


def test_zero_is_observed_not_missing(evidence):
    evidence["candidates"][0]["scores"]["b"]["value"] = 0
    assert by_id(build_audit(evidence, top_k=1))["A"]["status"] == "consistently_in_top_k"


def test_origin_coverage_exposes_selective_exclusion(evidence):
    evidence["candidates"][0]["origin"] = "source-with-missing-data"
    evidence["candidates"][0]["scores"]["b"] = {"status": "failed", "reason": "timeout"}
    report = build_audit(evidence, top_k=1)
    groups = {g["origin"]: g for g in report["coverage_by_origin"]}
    missing = groups["source-with-missing-data"]
    assert missing["total_candidates"] == 1 and missing["comparable_candidates"] == 0
    assert missing["observation_counts"]["b"]["failed"] == 1
    assert groups["fixture"]["comparable_candidates"] == 3


@pytest.mark.parametrize("provenance", ["unknown", "synthetic"])
def test_unverified_or_synthetic_research_rows_never_join_comparison(evidence, provenance):
    evidence["candidates"][0]["provenance"] = provenance
    row = by_id(build_audit(evidence, top_k=1))["A"]
    assert row["blocked_reasons"] == ["unverified_provenance"]
    assert row["rank_envelope"] is None


def test_demo_accepts_explicit_synthetic_rows_and_labels_results(evidence):
    evidence["data_kind"] = "synthetic_demo"
    evidence["candidates"][0]["provenance"] = "synthetic"
    report = build_audit(evidence, top_k=1)
    assert by_id(report)["A"]["status"] == "consistently_in_top_k"
    assert "Synthetic demonstration" in report["warnings"][0]
    assert "Synthetic demonstration" in render_html(report)


def test_shared_family_cannot_pose_as_cross_family_confirmation(evidence):
    evidence["methods"][1]["evidence_family"] = "family-a"
    report = build_audit(evidence, top_k=1)
    assert by_id(report)["A"]["status"] == "insufficient_comparison"
    assert report["method_agreement"][0]["same_evidence_family"] is True


def test_duplicating_a_method_does_not_vote_a_candidate_into_shortlist(evidence):
    before = build_audit(evidence, top_k=2)
    duplicate = {**evidence["methods"][0], "id": "a-copy"}
    evidence["methods"].append(duplicate)
    for candidate in evidence["candidates"]:
        candidate["scores"]["a-copy"] = copy.deepcopy(candidate["scores"]["a"])
    after = build_audit(evidence, top_k=2)
    assert [r["status"] for r in after["candidates"]] == [r["status"] for r in before["candidates"]]
    assert after["summary"]["declared_evidence_families"] == 2


def test_record_order_does_not_change_report_or_hash(evidence):
    before = canonical_json(build_audit(evidence, top_k=2))
    evidence["candidates"].reverse()
    evidence["methods"].reverse()
    assert canonical_json(build_audit(evidence, top_k=2)) == before


def test_monotone_rescaling_does_not_change_ranking(evidence):
    before = build_audit(evidence, top_k=2)
    for c in evidence["candidates"]:
        c["scores"]["a"]["value"] = c["scores"]["a"]["value"] * 100 + 10
    after = build_audit(evidence, top_k=2)
    assert [r["rank_intervals"] for r in after["candidates"]] == [r["rank_intervals"] for r in before["candidates"]]


def test_empty_comparison_has_no_fabricated_agreement(evidence):
    for c in evidence["candidates"]:
        c["provenance"] = "unknown"
    report = build_audit(evidence)
    assert report["summary"]["comparable_candidates"] == 0
    assert report["method_agreement"][0]["top_k_jaccard"] is None
    assert report["method_agreement"][0]["unavailable_reason"] == "empty_cohort"


def test_large_cutoff_is_explicitly_capped(evidence):
    report = build_audit(evidence, top_k=100)
    assert report["config"] == {"top_k": 100, "effective_top_k": 4}
    assert any("cannot distinguish" in w for w in report["warnings"])


@pytest.mark.parametrize("value", [True, None, "0.5", float("nan"), float("inf"), 10**1000])
def test_invalid_observed_numbers_rejected(evidence, value):
    evidence["candidates"][0]["scores"]["a"]["value"] = value
    with pytest.raises(ValueError, match="finite number"):
        build_audit(evidence)


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_invalid_cutoff_rejected(evidence, k):
    with pytest.raises(ValueError, match="top_k"):
        build_audit(evidence, top_k=k)


def test_missing_fields_and_unknown_methods_rejected(evidence):
    del evidence["candidates"][0]["scores"]["a"]
    with pytest.raises(ValueError, match="missing fields"):
        build_audit(evidence)
    evidence["candidates"][0]["scores"]["a"] = {"status": "observed", "value": 9}
    evidence["candidates"][0]["scores"]["typo"] = {"status": "observed", "value": 8}
    with pytest.raises(ValueError, match="unknown fields"):
        build_audit(evidence)


@pytest.mark.parametrize("collection", ["methods", "candidates"])
def test_duplicate_ids_rejected(evidence, collection):
    evidence[collection].append(copy.deepcopy(evidence[collection][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_audit(evidence)


def test_missing_observation_requires_reason_and_disallows_value(evidence):
    evidence["candidates"][0]["scores"]["a"] = {"status": "failed"}
    with pytest.raises(ValueError, match="reason"):
        build_audit(evidence)
    evidence["candidates"][0]["scores"]["a"] = {"status": "failed", "reason": "timeout", "value": 0}
    with pytest.raises(ValueError, match="must not contain a value"):
        build_audit(evidence)


def test_build_does_not_mutate_input(evidence):
    before = copy.deepcopy(evidence)
    build_audit(evidence, top_k=1)
    assert evidence == before


def test_html_escapes_user_content_and_csv_neutralizes_formulas(evidence):
    evidence["campaign_id"] = '<script>alert("x")</script>'
    evidence["candidates"][0]["origin"] = '<img src=x onerror="alert(1)">'
    evidence["candidates"][0]["id"] = "=HYPERLINK(\"bad\")"
    report = build_audit(evidence, top_k=1)
    html = render_html(report)
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "default-src 'none'" in html
    rows = list(csv.DictReader(io.StringIO(render_csv(report))))
    assert next(r for r in rows if "HYPERLINK" in r["candidate_id"])["candidate_id"].startswith("'=")


def test_portable_html_tables_are_complete_and_load_no_external_resources(evidence):
    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []
            self.row_width = 0
            self.external_resources = []

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.tables.append([])
            elif tag == "tr":
                self.row_width = 0
            elif tag in ("td", "th"):
                self.row_width += 1
            if tag in ("script", "img", "iframe", "link"):
                self.external_resources.append(tag)

        def handle_endtag(self, tag):
            if tag == "tr":
                self.tables[-1].append(self.row_width)

    parser = TableParser()
    parser.feed(render_html(build_audit(evidence, top_k=2)))
    assert len(parser.tables) == 4
    assert all(len(set(widths)) == 1 for widths in parser.tables)
    assert len(parser.tables[0]) == len(evidence["candidates"]) + 1
    assert parser.external_resources == []


def test_cli_exports_verifiable_reproducible_bundle_and_refuses_overwrite(evidence, tmp_path, capsys):
    source = tmp_path / "input.json"
    source.write_text(canonical_json(evidence))
    destination = tmp_path / "report"
    assert main([str(source), "--top-k", "2", "--output-dir", str(destination)]) == 0
    manifest = json.loads((destination / "manifest.json").read_text())
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    old = (destination / "report.json").read_bytes()
    assert main([str(source), "--output-dir", str(destination)]) == 2
    assert (destination / "report.json").read_bytes() == old
    second = tmp_path / "second"
    export_bundle(build_audit(evidence, top_k=2), second)
    assert all(p.read_bytes() == (second / p.name).read_bytes() for p in destination.iterdir())
    assert "failed" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("raw", ['{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}'])
def test_strict_json_parser_rejects_ambiguous_or_nonfinite_input(raw, tmp_path):
    source = tmp_path / "invalid.json"
    source.write_text(raw)
    with pytest.raises(ValueError):
        load_input(source)


def test_invalid_cli_input_leaves_no_output_directory(tmp_path):
    source = tmp_path / "invalid.json"
    source.write_text("{}")
    destination = tmp_path / "report"
    assert main([str(source), "--output-dir", str(destination)]) == 2
    assert not destination.exists()
