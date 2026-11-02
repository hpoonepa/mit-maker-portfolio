"""The run record is a judged deliverable, so it is tested like a contract.

Three properties matter more than the rest, and each has a test that fails loudly
if it regresses:

* **It validates against the published schema** - a record nobody can validate is
  not an interchange format.
* **Nothing it reports is restated here.** Thresholds and SASA parameters are
  imported from the modules that own them and compared, so a value changed
  without the record following breaks this file rather than shipping a record
  that misdescribes its own run.
* **It is byte-identical across runs of the same input** - a diff that is noise
  is a diff nobody reads.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from hotspot_preflight.checks.burial import (
    BURIAL_CONTACT_A,
    BURIED_RELATIVE_SASA,
    CROP_ARTIFACT_DELTA,
    PARTNER_OCCLUSION_DELTA,
    REQUIRED_PARAMETER_KEYS,
    SASA_PROBE_RADIUS,
    compute_burial,
)
from hotspot_preflight.record import (
    RUN_RECORD_VERSION,
    RUN_SPECIFIC_PARAMETER_KEYS,
    PreflightRun,
    sasa_parameters,
    to_run_record,
)
from hotspot_preflight.report import CHECK_ORDER, run_preflight
from hotspot_preflight.residue import ResidueKey, parse_hotspot_spec
from hotspot_preflight.schema import load_schema
from hotspot_preflight.structure import LOW_OCCUPANCY_THRESHOLD, load_target

# jsonschema is a dev dependency and does the real validation. The stdlib
# fallback below runs when it is absent, so the schema is still exercised in a
# bare environment rather than silently skipped. The fallback is deliberately
# shallow - required keys, types, and the severity enum, which is the minimum
# that can catch a record drifting from its published shape.

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,), "array": (list,), "string": (str,), "integer": (int,),
    "number": (int, float), "boolean": (bool,), "null": (type(None),),
}


def _fallback_validate(value: Any, node: dict[str, Any], root: dict[str, Any],
                       path: str = "$") -> None:
    """Minimal draft-2020-12 checking: $ref, type, enum, const, required."""
    ref = node.get("$ref")
    if ref is not None:
        assert ref.startswith("#/$defs/"), f"{path}: unresolvable {ref!r}"
        node = root["$defs"][ref[len("#/$defs/") :]]
    if "type" in node:
        names = node["type"]
        names = [names] if isinstance(names, str) else names
        # bool is an int in Python; JSON Schema does not agree.
        ok = any(
            isinstance(value, _TYPES[n])
            and not (n in ("number", "integer") and isinstance(value, bool))
            for n in names
        )
        assert ok, f"{path}: {value!r} is not of type {node['type']}"
    assert "enum" not in node or value in node["enum"], f"{path}: {value!r}"
    assert "const" not in node or value == node["const"], f"{path}: {value!r}"
    if isinstance(value, dict):
        for name in node.get("required", []):
            assert name in value, f"{path}: missing required {name!r}"
        if node.get("additionalProperties") is False:
            extra = set(value) - set(node.get("properties", {}))
            assert not extra, f"{path}: unexpected {sorted(extra)}"
        for name, sub in node.get("properties", {}).items():
            if name in value:
                _fallback_validate(value[name], sub, root, f"{path}.{name}")
    if isinstance(value, list) and "items" in node:
        for i, item in enumerate(value):
            _fallback_validate(item, node["items"], root, f"{path}[{i}]")


def _validate(instance: Any, schema: dict[str, Any]) -> str:
    try:
        import jsonschema
    except ModuleNotFoundError:  # pragma: no cover - jsonschema is a dev dep
        _fallback_validate(instance, schema, schema)
        return "fallback"
    jsonschema.validate(instance, schema)
    return "jsonschema"

@pytest.fixture
def clean_run(cif_with_unobs_category: Path) -> PreflightRun:
    """A101/A102 are modelled and exposed; the entry declares no assembly, so
    NO_ASSEMBLY_DEFINED is the only finding above PASS."""
    target = load_target(cif_with_unobs_category)
    return run_preflight(
        target, parse_hotspot_spec("A101,A102"), hotspot_spec="A101,A102"
    )


@pytest.fixture
def killed_run(cif_with_unobs_category: Path) -> PreflightRun:
    """A104 is declared but unmodelled - the 6F5J chain C failure, in miniature."""
    target = load_target(cif_with_unobs_category)
    return run_preflight(
        target, parse_hotspot_spec("A101,A104"), hotspot_spec="A101,A104"
    )

def test_run_records_round_trip_and_validate_against_the_schema(
    killed_run: PreflightRun, clean_run: PreflightRun
) -> None:
    """Both a STOP and a GO_WITH_WARNINGS record, since they differ in shape."""
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for run in (killed_run, clean_run):
        record = to_run_record(run)
        round_tripped = json.loads(json.dumps(record, sort_keys=True))
        assert round_tripped == record
        assert _validate(round_tripped, schema) in ("jsonschema", "fallback")


def test_record_carries_its_own_version_and_the_librarys(
    clean_run: PreflightRun,
) -> None:
    record = to_run_record(clean_run)
    assert record["record_version"] == RUN_RECORD_VERSION
    assert record["tool"]["name"] == "hotspot-preflight"
    # Falls back to the pyproject value when the package is not pip-installed,
    # which is how the test environment runs it.
    assert record["tool"]["version"] == "0.1.0"
    assert record["versions"]["gemmi"].startswith("0.7")
    assert record["versions"]["freesasa"]


def test_record_thresholds_equal_the_imported_module_constants(
    clean_run: PreflightRun,
) -> None:
    """The anti-desync test. Each threshold is compared against the constant it
    claims to report, imported from the module that owns it, so a threshold
    changed in one place and not the other fails here instead of shipping a
    record that lies about its own run."""
    thresholds = to_run_record(clean_run)["parameters"]["thresholds"]
    assert thresholds == {
        "low_occupancy_at_or_below": LOW_OCCUPANCY_THRESHOLD,
        "buried_relative_sasa_below": BURIED_RELATIVE_SASA,
        "crop_artifact_delta_above": CROP_ARTIFACT_DELTA,
        "partner_occlusion_delta_above": PARTNER_OCCLUSION_DELTA,
        "burial_contact_a": BURIAL_CONTACT_A,
        "sasa_probe_radius": SASA_PROBE_RADIUS,
    }


#: Where each run-specific burial parameter goes *instead of* the ``sasa``
#: block, or ``None`` when it is deliberately not recorded. Exists so that
#: "excluded" can never quietly come to mean "lost".
EXCLUSION_DESTINATIONS: dict[str, str | None] = {
    "freesasa_version": "versions.freesasa",
    "gemmi_version": "versions.gemmi",
    # Re-added from the real run rather than the probe, by _reference_id.
    "reference_id": "parameters.sasa.reference_id",
    # Per-context counters. check_burial builds up to three profiles per chain
    # and does not surface their counters in the findings, so there is no single
    # value to record; recording one chain's would be a half-truth.
    "n_reference_empirical": None,
    "n_reference_published": None,
    "n_reference_substituted": None,
    "n_fallback_radius_atoms": None,
    "focus_chain": None,
}


def test_no_burial_parameter_is_dropped_or_misreported(
    cif_with_unobs_category: Path, clean_run: PreflightRun
) -> None:
    """Both directions, against a real profile, naming no parameter.

    Every pinned value must equal the profile's, and every key the profile
    carries must either reach the record or be classified run-specific. A
    parameter added to the burial check thus lands in the record automatically,
    and one that cannot be classified fails here instead of vanishing.
    """
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    sasa = to_run_record(clean_run)["parameters"]["sasa"]
    assert profile.parameters and sasa_parameters()
    for key, value in sasa_parameters().items():
        assert profile.parameters[key] == value, key
    for key in profile.parameters:
        assert key in sasa or key in RUN_SPECIFIC_PARAMETER_KEYS, (
            f"{key!r} is in BurialProfile.parameters but reaches neither the "
            f"record nor RUN_SPECIFIC_PARAMETER_KEYS"
        )


def test_sasa_parameters_cover_every_required_key() -> None:
    """``REQUIRED_PARAMETER_KEYS`` is the burial check's own statement of what
    is load-bearing, so it is imported and subset-checked, never enumerated."""
    required = set(REQUIRED_PARAMETER_KEYS) - set(RUN_SPECIFIC_PARAMETER_KEYS)
    assert required <= set(sasa_parameters())


def test_every_exclusion_is_documented_and_relocated(
    clean_run: PreflightRun,
) -> None:
    """An exclusion needs a destination, and must be found at it."""
    assert set(RUN_SPECIFIC_PARAMETER_KEYS) == set(EXCLUSION_DESTINATIONS)
    record: Any = to_run_record(clean_run)
    for key, path in EXCLUSION_DESTINATIONS.items():
        if path is None:
            continue
        node = record
        for part in path.split("."):
            assert part in node, f"{key}: {path} is missing from the record"
            node = node[part]
        assert node is not None, f"{key}: {path} is null"


def test_record_reference_id_is_the_one_burial_actually_used(
    clean_run: PreflightRun,
) -> None:
    """The relative-SASA denominator scale, lifted from the findings rather
    than recomputed - a recomputed one could disagree with what was used."""
    recorded = to_run_record(clean_run)["parameters"]["sasa"]["reference_id"]
    from_findings = {
        f.evidence["reference_id"]
        for f in clean_run.report.findings
        if "reference_id" in f.evidence
    }
    assert from_findings == {recorded}


def test_reference_id_is_null_when_burial_never_ran(
    cif_with_unobs_category: Path,
) -> None:
    target = load_target(cif_with_unobs_category)
    run = run_preflight(target, [ResidueKey("Z", 101)])
    assert to_run_record(run)["parameters"]["sasa"]["reference_id"] is None


def test_record_carries_both_the_spec_as_typed_and_the_parsed_keys(
    killed_run: PreflightRun,
) -> None:
    site = to_run_record(killed_run)["site"]
    assert site["hotspot_spec"] == "A101,A104"
    assert site["keys"] == ["A101", "A104"]
    assert site["residues"] == [
        {"chain": "A", "auth_seq_id": 101, "icode": None},
        {"chain": "A", "auth_seq_id": 104, "icode": None},
    ]


def test_record_carries_the_crop_range(cif_with_unobs_category: Path) -> None:
    target = load_target(cif_with_unobs_category)
    run = run_preflight(
        target, parse_hotspot_spec("A101"), crop_range=("A", 101, 103)
    )
    crop = to_run_record(run)["site"]["crop_range"]
    assert crop == {"chain": "A", "first": 101, "last": 103}


def test_record_identifies_the_input_by_digest_and_not_by_path(
    cif_with_unobs_category: Path, clean_run: PreflightRun
) -> None:
    """A record is committed and diffed, so it must identify the coordinates
    without embedding the machine it was produced on."""
    expected = hashlib.sha256(cif_with_unobs_category.read_bytes()).hexdigest()
    record = to_run_record(clean_run)
    assert clean_run.input_digest == expected
    assert record["input"]["sha256"] == expected
    assert record["input"]["filename"] == "with_unobs.cif"
    text = json.dumps(record, sort_keys=True)
    assert str(cif_with_unobs_category.parent) not in text


def test_record_mirrors_the_site_report(killed_run: PreflightRun) -> None:
    report, record = killed_run.report, to_run_record(killed_run)
    assert record["verdict"] == "STOP"
    assert record["n_kill"] == len(report.kills)
    assert record["n_warn"] == len(report.warnings)
    assert record["kill_codes"] == report.kill_codes()
    assert len(record["findings"]) == len(report.findings)
    assert record["findings"][0] == report.findings[0].to_dict()
    assert {f["severity"] for f in record["findings"]} <= {"PASS", "WARN", "KILL"}
    assert set(record["tool_formats"]) == {"rfdiffusion", "bindcraft", "boltzgen"}


def test_record_is_byte_identical_across_runs_of_the_same_input(
    cif_with_unobs_category: Path,
) -> None:
    """No timestamp, no ordering wobble, nothing machine-dependent. The
    record carries no time field at all; one added later must be injectable,
    because a record that differs every run cannot be diffed."""
    def once() -> str:
        target = load_target(cif_with_unobs_category)
        run = run_preflight(
            target, parse_hotspot_spec("A101,A104"), hotspot_spec="A101,A104"
        )
        return json.dumps(to_run_record(run), sort_keys=True, indent=2)

    assert once() == once()


def test_record_carries_the_assembly_that_burial_actually_used(
    clean_run: PreflightRun,
) -> None:
    """The synthetic entry declares none, which the record must say rather than
    implying the asymmetric unit was the biological form."""
    assert clean_run.assembly_id is None
    assert to_run_record(clean_run)["input"]["assembly_id"] is None


def test_record_names_the_checks_that_ran(clean_run: PreflightRun) -> None:
    """Default order, and the record follows what actually ran rather than the
    constant - --no-patch and --evidence both change it."""
    assert to_run_record(clean_run)["parameters"]["checks"] == list(CHECK_ORDER)


@pytest.mark.network
def test_6f5j_record_validates_against_the_schema(real_6f5j: Path) -> None:
    """The only record built on an entry with a real biological assembly and 393
    observed residues, so it exercises shapes the synthetic fixtures cannot."""
    target = load_target(real_6f5j)
    run = run_preflight(
        target, parse_hotspot_spec("C325,C326"), hotspot_spec="C325,C326"
    )
    record = json.loads(json.dumps(to_run_record(run), sort_keys=True))
    _validate(record, load_schema())
    assert record["input"]["target_id"] == "6F5J"
    assert record["input"]["filename"] == "6f5j_updated.cif"
    assert record["input"]["assembly_id"] == "1"
