# SPDX-License-Identifier: MIT
"""Tests for the packaging, citation and standards metadata.

These are not decorative. Each test here exists because the corresponding file
makes a claim that can drift out of agreement with the code:

* ``CITATION.cff`` claims a version; ``pyproject.toml`` also claims a version.
* ``codemeta.json`` claims a name and a licence; so does ``pyproject.toml``.
* ``NOTICE.md`` claims to attribute every runtime dependency; dependencies get
  added by people who are not thinking about attribution.
* Published metadata must not contain placeholder repository URLs.

Every value is read from ``pyproject.toml`` rather than hardcoded, so bumping a
version in one place and not the other fails here instead of shipping.

``test_notice_mentions_every_runtime_dependency`` is the one most likely to fail
on somebody else's change, and that is its purpose: adding a dependency without
attributing it in ``NOTICE.md`` should break the build.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# PyYAML is a declared runtime dependency, so importing it unconditionally is
# correct — if it is missing the environment is broken and a hard failure here
# is more useful than a skip.
import yaml

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 — the project supports >=3.10
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent

CITATION_CFF = REPO_ROOT / "CITATION.cff"
CODEMETA_JSON = REPO_ROOT / "codemeta.json"
CWL_DOC = REPO_ROOT / "hotspot-preflight.cwl"
NOTICE_MD = REPO_ROOT / "NOTICE.md"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


# --------------------------------------------------------------------------
# Fixtures: parse each file exactly once, and let a parse failure be the test
# failure rather than an error inside an unrelated assertion.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pyproject() -> dict:
    """The source of truth for name, version and licence."""
    with PYPROJECT_TOML.open("rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="module")
def citation() -> dict:
    return yaml.safe_load(CITATION_CFF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def codemeta() -> dict:
    return json.loads(CODEMETA_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cwl() -> dict:
    return yaml.safe_load(CWL_DOC.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# CITATION.cff — Citation File Format 1.2.0
# --------------------------------------------------------------------------


def test_citation_cff_exists() -> None:
    assert CITATION_CFF.is_file(), "CITATION.cff is missing"


def test_citation_cff_parses_as_yaml(citation: dict) -> None:
    assert isinstance(citation, dict), "CITATION.cff did not parse to a mapping"


def test_citation_cff_declares_version_1_2_0(citation: dict) -> None:
    # A string, not a float. YAML would read an unquoted 1.2 as a float, and
    # "1.2.0" is the only value the CFF 1.2.0 schema accepts here.
    assert citation["cff-version"] == "1.2.0"


@pytest.mark.parametrize(
    "key",
    [
        "cff-version",
        "message",
        "title",
        "abstract",
        "authors",
        "license",
        "keywords",
        "version",
        "type",
    ],
)
def test_citation_cff_has_required_key(citation: dict, key: str) -> None:
    """`cff-version`, `message`, `title` and `authors` are schema-required.

    The rest are required by this project rather than by the schema, because a
    citation record without a licence or a repository URL is not useful even
    when it validates.
    """
    assert key in citation, f"CITATION.cff is missing `{key}`"
    assert citation[key], f"CITATION.cff has an empty `{key}`"


def test_citation_cff_type_is_software(citation: dict) -> None:
    assert citation["type"] == "software"


def test_citation_cff_license_is_mit(citation: dict) -> None:
    """MIT is the SPDX identifier CFF expects in `license`."""
    assert citation["license"] == "MIT"


def test_citation_cff_author_is_the_team_as_an_entity(citation: dict) -> None:
    """No invented individual names, and no invented ORCIDs.

    CFF distinguishes a person author (`given-names`/`family-names`) from an
    entity author (`name`). The team is an entity. This test pins that choice so
    nobody later "improves" the file by inventing a person.
    """
    authors = citation["authors"]
    assert isinstance(authors, list) and authors, "no authors listed"
    for author in authors:
        assert "name" in author, (
            "expected entity authors with `name`; found a person-shaped author. "
            "Do not invent individual author names."
        )
        assert "given-names" not in author and "family-names" not in author
        assert "orcid" not in author, "do not invent an ORCID"


def test_citation_cff_declares_no_doi(citation: dict) -> None:
    """There is no DOI for this project yet, so there must not be one here."""
    assert "doi" not in citation, (
        "a `doi:` appeared in CITATION.cff. If an archival deposit now exists, "
        "delete this test; if it does not, the DOI is invented."
    )


def test_citation_version_matches_pyproject(citation: dict, pyproject: dict) -> None:
    assert str(citation["version"]) == pyproject["project"]["version"]


def test_citation_title_matches_pyproject_name(citation: dict, pyproject: dict) -> None:
    assert citation["title"] == pyproject["project"]["name"]


# --------------------------------------------------------------------------
# codemeta.json
# --------------------------------------------------------------------------


def test_codemeta_exists() -> None:
    assert CODEMETA_JSON.is_file(), "codemeta.json is missing"


def test_codemeta_parses_as_json(codemeta: dict) -> None:
    assert isinstance(codemeta, dict), "codemeta.json did not parse to an object"


def test_codemeta_declares_codemeta_context(codemeta: dict) -> None:
    assert "codemeta" in codemeta["@context"]


def test_codemeta_is_software_source_code(codemeta: dict) -> None:
    assert codemeta["@type"] == "SoftwareSourceCode"


def test_codemeta_name_matches_pyproject(codemeta: dict, pyproject: dict) -> None:
    assert codemeta["name"] == pyproject["project"]["name"]


def test_codemeta_version_matches_pyproject(codemeta: dict, pyproject: dict) -> None:
    assert codemeta["version"] == pyproject["project"]["version"]


def test_codemeta_license_matches_pyproject(codemeta: dict, pyproject: dict) -> None:
    """Agreement across three spellings of the same fact.

    `pyproject.toml` says `license = { text = "MIT" }`, codemeta uses an SPDX
    URL, and CITATION.cff uses the bare SPDX identifier. All three must mean
    MIT.
    """
    declared = pyproject["project"]["license"]
    spelling = declared if isinstance(declared, str) else declared.get("text", "")
    assert spelling == "MIT", f"pyproject licence is {spelling!r}, not MIT"
    assert codemeta["license"] == "https://spdx.org/licenses/MIT"


def test_codemeta_agrees_with_citation_cff(codemeta: dict, citation: dict) -> None:
    assert codemeta["name"] == citation["title"]
    assert codemeta["version"] == str(citation["version"])
    assert codemeta.get("codeRepository") == citation.get("repository-code")


def test_codemeta_requirements_cover_runtime_dependencies(
    codemeta: dict, pyproject: dict
) -> None:
    """Every runtime dependency appears in `softwareRequirements`."""
    declared = {
        _dependency_name(spec) for spec in pyproject["project"]["dependencies"]
    }
    listed = {
        entry["name"].lower()
        for entry in codemeta.get("softwareRequirements", [])
        if isinstance(entry, dict) and "name" in entry
    }
    missing = declared - listed
    assert not missing, (
        f"codemeta.json softwareRequirements is missing {sorted(missing)}. "
        "Add the dependency there as well as to pyproject.toml."
    )


def test_codemeta_edam_terms_are_well_formed(codemeta: dict) -> None:
    """EDAM IRIs must look like EDAM IRIs.

    This cannot confirm a term exists — that needs the ontology, and these
    tests are offline by design. Each identifier was resolved against the EBI
    OLS4 EDAM endpoint by hand on 2026-10-05 and recorded in docs/standards.md.
    What this test catches is a malformed or mistyped IRI.
    """
    entries = codemeta.get("applicationSubCategory", []) + codemeta.get(
        "featureList", []
    )
    assert entries, "no EDAM annotation found in codemeta.json"

    pattern = re.compile(r"^http://edamontology\.org/(topic|operation|format)_\d{4}$")
    for entry in entries:
        assert isinstance(entry, dict), f"expected an object, got {entry!r}"
        assert pattern.match(entry["@id"]), f"malformed EDAM IRI: {entry['@id']!r}"
        assert entry.get("name"), f"EDAM term {entry['@id']} has no label"


# --------------------------------------------------------------------------
# hotspot-preflight.cwl — CWL v1.2
# --------------------------------------------------------------------------


def test_cwl_exists() -> None:
    assert CWL_DOC.is_file(), "hotspot-preflight.cwl is missing"


def test_cwl_parses_as_yaml(cwl: dict) -> None:
    assert isinstance(cwl, dict), "the CWL document did not parse to a mapping"


def test_cwl_declares_version_1_2(cwl: dict) -> None:
    """v1.2 is the current stable CWL release.

    v1.3 exists only as the pre-release v1.3.0-dev1, so this must not drift
    upward without a deliberate decision.
    """
    assert cwl["cwlVersion"] == "v1.2"


def test_cwl_is_a_command_line_tool(cwl: dict) -> None:
    assert cwl["class"] == "CommandLineTool"


def test_cwl_invokes_preflight_check(cwl: dict) -> None:
    assert cwl["baseCommand"] == ["preflight", "check"]


@pytest.mark.parametrize("name", ["structure", "hotspots", "crop", "json_out", "csv_out"])
def test_cwl_declares_input(cwl: dict, name: str) -> None:
    assert name in cwl["inputs"], f"CWL document has no `{name}` input"


def test_cwl_structure_input_is_required_and_hotspots_too(cwl: dict) -> None:
    """A trailing `?` makes a CWL type optional. These two must not have one."""
    assert cwl["inputs"]["structure"]["type"] == "File"
    assert cwl["inputs"]["hotspots"]["type"] == "string"


@pytest.mark.parametrize("name", ["crop", "json_out", "csv_out"])
def test_cwl_optional_inputs_are_optional(cwl: dict, name: str) -> None:
    assert str(cwl["inputs"][name]["type"]).endswith("?"), (
        f"`{name}` should be an optional CWL type ending in `?`"
    )


def test_cwl_exit_code_map_is_explicit(cwl: dict) -> None:
    """The whole point of the exit-code block.

    CWL treats any non-zero exit as failure by default, so without an explicit
    `successCodes` a GO_WITH_WARNINGS run (exit 1) looks like a crash and a
    workflow aborts on a usable result.
    """
    assert cwl["successCodes"] == [0, 1], (
        "successCodes must list both 0 (GO) and 1 (GO_WITH_WARNINGS), or "
        "GO_WITH_WARNINGS will be reported as a tool failure"
    )
    assert cwl["permanentFailCodes"] == [2, 3], (
        "permanentFailCodes must list 2 (STOP) and 3 (usage error)"
    )
    # Declared empty on purpose: every non-zero code here is deterministic, so
    # nothing is worth retrying. Asserted so the empty list is not mistaken for
    # an oversight and "helpfully" populated.
    assert cwl["temporaryFailCodes"] == []


def test_cwl_exit_codes_partition_the_scheme(cwl: dict) -> None:
    """0/1/2/3 are each classified exactly once."""
    classified = (
        cwl["successCodes"] + cwl["temporaryFailCodes"] + cwl["permanentFailCodes"]
    )
    assert sorted(classified) == [0, 1, 2, 3]
    assert len(classified) == len(set(classified)), "an exit code is classified twice"


# --------------------------------------------------------------------------
# NOTICE.md — the attribution test that is meant to fail on new dependencies
# --------------------------------------------------------------------------


def _dependency_name(spec: str) -> str:
    """Strip version constraints and extras from a PEP 508 requirement string.

    ``"gemmi>=0.7.5"`` -> ``"gemmi"``;  ``"typer[all]>=0.12"`` -> ``"typer"``.
    """
    return re.split(r"[\[\]<>=!~;\s]", spec, maxsplit=1)[0].strip().lower()


def test_notice_exists() -> None:
    assert NOTICE_MD.is_file(), "NOTICE.md is missing"


def test_notice_mentions_every_runtime_dependency(pyproject: dict) -> None:
    """Adding a dependency without attributing it must fail the build.

    That is the entire purpose of this test. If it fails because you added a
    dependency, the fix is to add a row to the dependency table in NOTICE.md
    with its licence, not to relax this assertion.
    """
    notice = NOTICE_MD.read_text(encoding="utf-8").lower()
    declared = [_dependency_name(s) for s in pyproject["project"]["dependencies"]]
    assert declared, "pyproject.toml declares no runtime dependencies"

    unattributed = [name for name in declared if name not in notice]
    assert not unattributed, (
        f"NOTICE.md does not mention runtime dependencies {unattributed}. "
        "Every runtime dependency needs an attribution row with its licence."
    )


def test_notice_mentions_optional_dependencies(pyproject: dict) -> None:
    """Optional extras ship to users who ask for them, so they need crediting too."""
    notice = NOTICE_MD.read_text(encoding="utf-8").lower()
    extras = pyproject["project"].get("optional-dependencies", {})
    unattributed = [
        _dependency_name(spec)
        for specs in extras.values()
        for spec in specs
        if _dependency_name(spec) not in notice
    ]
    assert not unattributed, (
        f"NOTICE.md does not mention optional dependencies {unattributed}."
    )


def test_notice_credits_the_relative_sasa_reference() -> None:
    """Tien et al. 2013 supplies the published maximum-accessibility table."""
    notice = NOTICE_MD.read_text(encoding="utf-8")
    assert "Tien" in notice
    assert "e80635" in notice, "cite the article, not just the author"


def test_notice_credits_the_ported_statistics_code() -> None:
    """`benchmark/` statistics are ported from the authors' binder-scorer."""
    notice = NOTICE_MD.read_text(encoding="utf-8")
    assert "binder-scorer" in notice
    assert "benchmark/" in notice


def test_notice_does_not_duplicate_data_licences() -> None:
    """DATA_LICENSES.md owns data-source terms; duplicated terms drift apart.

    NOTICE.md should *link* to it and not restate SAbDab / AsEP / RCSB terms.

    Naming those sources in a pointer sentence is fine and useful; what must not
    appear is their licence *grants*, because a licence identifier copied into
    two files is a licence identifier that will eventually disagree with itself.
    So this test looks for the grants, not for the names.
    """
    notice = NOTICE_MD.read_text(encoding="utf-8")
    assert "DATA_LICENSES.md" in notice, "NOTICE.md should link to DATA_LICENSES.md"

    restated = [grant for grant in ("CC-BY-4.0", "CC0-1.0") if grant in notice]
    assert not restated, (
        f"NOTICE.md appears to restate data-source licence grants {restated}. "
        "Those belong in DATA_LICENSES.md only; link to it instead."
    )


# --------------------------------------------------------------------------
# Placeholders
def test_public_metadata_has_no_placeholder_urls():
    for path in (CITATION_CFF, CODEMETA_JSON):
        assert not re.search(r"<[a-z][a-z-]+>", path.read_text())


def test_repository_urls_agree_when_published(citation, codemeta):
    url = citation.get("repository-code")
    assert url == codemeta.get("codeRepository")
    if url is not None:
        assert url.startswith("https://")
