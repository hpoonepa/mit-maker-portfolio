"""End-to-end orchestrator test.

Runs the full metric suite on a single fixture design and verifies that
`validated.json` has the expected shape: every design gets every metric,
and placeholder metrics return finite floats rather than NaN/None. This
locks in the CONTRACT documented in README.md, not the numeric values
(which will churn as real implementations replace placeholders).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from papercrane_validator.orchestrator import run_validation


FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_METRIC_KEYS = {
    "ipsae",
    "dockq",
    "ptmenergy",
    "lis",
    "overath",
    "hotspot_contact",
    "esm_pll",
}


def _write_designs_json(tmp_path: Path) -> Path:
    """Rewrite upstream fixture with absolute paths into tmp_path/inputs."""
    src = json.loads((FIXTURES / "upstream_output.json").read_text())
    src["target_pdb"] = str(FIXTURES / "target.pdb")
    for d in src["designs"]:
        d["path"] = str(FIXTURES / Path(d["path"]).name)

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    p = inputs_dir / "designs.json"
    p.write_text(json.dumps(src))
    return p


def test_orchestrator_produces_canonical_shape(tmp_path):
    designs_json = _write_designs_json(tmp_path)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    exit_code = run_validation(
        designs_json=str(designs_json),
        outputs_dir=str(outputs_dir),
    )
    assert exit_code == 0

    validated = json.loads((outputs_dir / "validated.json").read_text())
    assert "designs" in validated
    assert len(validated["designs"]) == 1

    d = validated["designs"][0]
    assert d["seed"] == 42
    assert d["path"].endswith("design_0001.pdb")
    assert set(d["metrics"].keys()) == EXPECTED_METRIC_KEYS

    for k, v in d["metrics"].items():
        assert isinstance(v, float), f"metric {k} is not float: {v!r}"
        assert math.isfinite(v), f"metric {k} is non-finite: {v}"


def test_orchestrator_preserves_upstream_metrics(tmp_path):
    designs_json = _write_designs_json(tmp_path)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    run_validation(
        designs_json=str(designs_json),
        outputs_dir=str(outputs_dir),
    )

    validated = json.loads((outputs_dir / "validated.json").read_text())
    d = validated["designs"][0]
    assert d["upstream_metrics"]["iptm"] == pytest.approx(0.82)


def test_orchestrator_hotspot_contact_is_one_for_fixture(tmp_path):
    """Sanity: the hotspot metric we trust should return 1.0 on the fixture,
    because both hotspots (A/2, A/4) are designed to be in contact.
    """
    designs_json = _write_designs_json(tmp_path)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    run_validation(
        designs_json=str(designs_json),
        outputs_dir=str(outputs_dir),
    )

    validated = json.loads((outputs_dir / "validated.json").read_text())
    d = validated["designs"][0]
    assert d["metrics"]["hotspot_contact"] == pytest.approx(1.0)
