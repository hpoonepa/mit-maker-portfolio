# SPDX-License-Identifier: MIT
"""Surface patch enumeration and the patch-geometry check (C5).

The synthetic fixture here is a *pair* of chains rather than conftest's single
one, because two of the five codes this check emits — ``MULTI_CHAIN_SITE`` and
cross-chain contiguity — cannot be reached at all on one chain, and reaching
them through a network download would make them untestable offline.

Its geometry is chosen so every threshold is crossed by a known margin rather
than by luck. Residues sit 6.0 A apart along x, so consecutive residues are
graph-neighbours at the 8.0 A cutoff and residues two apart are not: the
neighbour graph of a run is a bare path, and dropping a middle residue provably
splits it. Centroids are 6.0 A apart, so an *n*-residue run spans exactly
``6(n-1)`` A — 5 residues is 24 A (under the 25 A limit), 6 is 30 A (over).
Chain B is offset 6.0 A in y, so a residue in A and the one facing it in B are
neighbours: a two-chain site that is genuinely contiguous, which is the case
that must warn without being killed.
"""

from __future__ import annotations

import time
from pathlib import Path

import gemmi
import pytest

from hotspot_preflight.checks.patch import (
    CHECK_NAME,
    MAX_PATCH_DIAMETER_A,
    RFDIFFUSION_MAX_HOTSPOTS,
    RFDIFFUSION_MIN_HOTSPOTS,
    check_patch_geometry,
)
from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa
from hotspot_preflight.findings import Severity
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import load_target
from hotspot_preflight.surface import (
    EXPOSED_RELATIVE_SASA,
    PATCH_MAX_RESIDUES,
    PATCH_MIN_RESIDUES,
    PATCH_RADIUS_A,
    Patch,
    _neighbour_search,
    enumerate_patches,
    neighbour_graph,
    patch_contiguous,
    patch_diameter,
    residue_centroid,
    surface_residues,
)

# Fixture geometry. Asserted on below rather than merely assumed, so that a
# change to the fixture cannot quietly invalidate the threshold tests.
SPACING_A = 6.0
CHAIN_OFFSET_Y = 6.0
N_RESIDUES = 10


def _build_pair(path: Path) -> Path:
    st = gemmi.Structure()
    st.name = "PAIR"
    model = gemmi.Model("1")
    for chain_name, first_auth, dy in (("A", 101, 0.0), ("B", 201, CHAIN_OFFSET_Y)):
        chain = gemmi.Chain(chain_name)
        for i in range(N_RESIDUES):
            res = gemmi.Residue()
            res.name = "ALA"
            res.seqid = gemmi.SeqId(first_auth + i, " ")
            res.label_seq = i + 1
            res.het_flag = "A"
            res.entity_type = gemmi.EntityType.Polymer
            for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5), ("C", "C", 3.0)):
                atom = gemmi.Atom()
                atom.name, atom.element = name, gemmi.Element(elem)
                atom.pos = gemmi.Position(i * SPACING_A + dx, dy, 0.0)
                atom.occ, atom.b_iso = 1.0, 20.0
                res.add_atom(atom)
            chain.add_residue(res)
        model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    path.write_text(st.make_mmcif_document().as_string())
    return path


@pytest.fixture
def pair_cif(tmp_path: Path) -> Path:
    """Two 10-residue chains, 6 A apart in y. See the module docstring."""
    return _build_pair(tmp_path / "pair.cif")


@pytest.fixture
def pair(pair_cif: Path):
    return load_target(pair_cif)


def _a(*nums: int) -> list[ResidueKey]:
    return [ResidueKey("A", n) for n in nums]


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def _patch(*nums: int) -> Patch:
    """A Patch carrying only members. The geometry helpers read nothing else."""
    return Patch(
        residues=tuple(_a(*nums)), centroid=(0.0, 0.0, 0.0), area=1.0,
        mean_relative_sasa=1.0,
    )


def _profile(target, chain: str):
    """A profile for one chain, against one table from the whole structure.

    Never a table recomputed from the subset being measured: that rescales the
    denominators and the values stop being comparable across contexts. See
    ``test_burial.py::test_supplied_reference_is_used_rather_than_recomputed``.
    """
    return compute_burial(
        target.st,
        context="chain",
        focus_chain=chain,
        reference=reference_max_sasa(target.st),
    )


# ---------------------------------------------------------------------------
# The fixture's geometry is what the threshold tests rest on
# ---------------------------------------------------------------------------


def test_fixture_geometry_is_what_the_thresholds_assume(pair):
    """Guard the margins. Every assertion below reads off these numbers."""
    first = residue_centroid(pair, ResidueKey("A", 101))
    second = residue_centroid(pair, ResidueKey("A", 102))
    assert second[0] - first[0] == pytest.approx(SPACING_A)

    # 5 residues fit under the diameter limit, 6 do not.
    assert SPACING_A * 4 < MAX_PATCH_DIAMETER_A < SPACING_A * 5

    # Consecutive residues are neighbours; residues two apart are not.
    graph = neighbour_graph(pair, _a(101, 102, 103))
    assert graph[ResidueKey("A", 101)] == {ResidueKey("A", 102)}
    assert graph[ResidueKey("A", 103)] == {ResidueKey("A", 102)}


# ---------------------------------------------------------------------------
# surface.py
# ---------------------------------------------------------------------------


def test_surface_residues_are_those_above_the_exposure_threshold(pair):
    profile = _profile(pair, "A")
    keys = surface_residues(pair, profile)
    assert keys == sorted(keys), "must come back canonically sorted"
    assert set(keys) <= set(profile.relative_sasa)
    for key in keys:
        assert profile.relative_sasa[key] >= EXPOSED_RELATIVE_SASA
    for key, value in profile.relative_sasa.items():
        if value < EXPOSED_RELATIVE_SASA:
            assert key not in keys


def test_residue_centroid_averages_heavy_atoms(pair):
    # N at x=0, CA at 1.5, C at 3.0 -> mean 1.5; y is the chain offset.
    assert residue_centroid(pair, ResidueKey("B", 201)) == pytest.approx(
        (1.5, CHAIN_OFFSET_Y, 0.0)
    )
    # An absent residue must raise, not return a sentinel: a centroid at the
    # origin would silently distort every distance measured against it.
    with pytest.raises(KeyError):
        residue_centroid(pair, ResidueKey("A", 999))


def test_neighbour_graph_is_symmetric_total_and_crosses_chains(pair):
    keys = _a(101, 102, 103, 110)
    graph = neighbour_graph(pair, keys)
    assert set(graph) == set(keys), "every requested key must appear, even isolated"
    assert graph[ResidueKey("A", 110)] == set()
    for key, partners in graph.items():
        assert key not in partners, "a residue is not its own neighbour"
        for other in partners:
            assert key in graph[other]
    across = neighbour_graph(pair, [ResidueKey("A", 101), ResidueKey("B", 201)])
    assert across[ResidueKey("A", 101)] == {ResidueKey("B", 201)}


def test_enumerate_patches_respects_the_size_bounds(pair):
    profile = _profile(pair, "A")
    patches = enumerate_patches(pair, profile, chain="A")
    assert patches, "a 10-residue exposed chain must yield at least one patch"
    for patch in patches:
        assert isinstance(patch, Patch)
        assert PATCH_MIN_RESIDUES <= patch.size <= PATCH_MAX_RESIDUES
        assert patch.size == len(patch.residues)
        assert tuple(sorted(patch.residues)) == patch.residues
        assert patch.area > 0
        assert patch.mean_relative_sasa >= EXPOSED_RELATIVE_SASA
        assert patch_diameter(pair, patch) <= PATCH_RADIUS_A * 2 + 1e-6


def test_enumerate_patches_deduplicates_and_is_deterministic(pair):
    profile = _profile(pair, "A")
    first = enumerate_patches(pair, profile, chain="A")
    second = enumerate_patches(pair, profile, chain="A")
    assert [p.residues for p in first] == [p.residues for p in second]
    sets = [frozenset(p.residues) for p in first]
    assert len(sets) == len(set(sets)), "overlapping patches, but no duplicates"


def test_enumerate_patches_restricted_to_a_chain_stays_on_it(pair):
    profile = compute_burial(
        pair.st, context="chain", reference=reference_max_sasa(pair.st)
    )
    patches = enumerate_patches(pair, profile, chain="B")
    assert patches
    for patch in patches:
        assert {k.auth_asym_id for k in patch.residues} == {"B"}


def test_enumerate_patches_honours_max_patches(pair):
    profile = _profile(pair, "A")
    full = enumerate_patches(pair, profile, chain="A")
    capped = enumerate_patches(pair, profile, chain="A", max_patches=2)
    assert len(capped) == min(2, len(full))
    assert [p.residues for p in capped] == [p.residues for p in full[:2]]


def test_every_enumerated_patch_is_contiguous(pair):
    profile = _profile(pair, "A")
    for patch in enumerate_patches(pair, profile, chain="A"):
        assert patch_contiguous(pair, patch)


def test_patch_diameter_is_the_widest_centroid_separation(pair):
    assert patch_diameter(pair, _patch(101, 102, 103)) == pytest.approx(SPACING_A * 2)


def test_patch_contiguous_agrees_with_the_check(pair):
    """One geometry, two entry points: they must not be able to disagree."""
    split, joined = _patch(101, 110), _patch(101, 102, 103)
    assert not patch_contiguous(pair, split)
    assert patch_contiguous(pair, joined)
    assert "NOT_CONTIGUOUS" in _codes(check_patch_geometry(pair, list(split.residues)))
    assert "NOT_CONTIGUOUS" not in _codes(
        check_patch_geometry(pair, list(joined.residues))
    )


# ---------------------------------------------------------------------------
# checks/patch.py — C5
# ---------------------------------------------------------------------------


def test_a_contiguous_compact_site_passes(pair):
    findings = check_patch_geometry(pair, _a(101, 102, 103, 104))
    assert _codes(findings) == ["PATCH_GEOMETRY_OK"]
    assert findings[0].severity is Severity.PASS
    assert findings[0].check == CHECK_NAME
    assert findings[0].key is None


def test_separated_hotspots_are_killed_with_their_components(pair):
    """A101 and A110 are 54 A apart: two sites, not one."""
    findings = check_patch_geometry(pair, _a(101, 110))
    kills = [f for f in findings if f.severity is Severity.KILL]
    assert [f.code for f in kills] == ["NOT_CONTIGUOUS"]
    kill = kills[0]
    assert kill.key is None
    assert kill.evidence["n_components"] == 2
    assert sorted(kill.evidence["components"]) == [["A101"], ["A110"]]
    assert "not one bindable site" in kill.message

    # Three islands must report three, not merely "more than one".
    three = check_patch_geometry(pair, _a(101, 105, 110))
    assert next(f for f in three if f.code == "NOT_CONTIGUOUS").evidence[
        "n_components"
    ] == 3


def test_a_wide_but_contiguous_site_only_warns(pair):
    """6 consecutive residues: 30 A across, still one connected patch."""
    keys = _a(101, 102, 103, 104, 105, 106)
    assert len(keys) <= RFDIFFUSION_MAX_HOTSPOTS
    findings = check_patch_geometry(pair, keys)
    codes = _codes(findings)
    assert "PATCH_TOO_LARGE" in codes
    assert "NOT_CONTIGUOUS" not in codes
    assert "HOTSPOT_COUNT_UNUSUAL" not in codes
    warn = next(f for f in findings if f.code == "PATCH_TOO_LARGE")
    assert warn.severity is Severity.WARN
    assert warn.evidence["diameter_a"] == pytest.approx(SPACING_A * 5)
    assert warn.evidence["max_diameter_a"] == MAX_PATCH_DIAMETER_A


def test_one_hotspot_is_an_unusual_count(pair):
    """Reported, but at PASS: a note about RFdiffusion's README, not a verdict.

    Severity deliberately PASS rather than WARN — see ``_count_findings``. The
    code measures the shape of the user's request, not the target, and a
    two-residue site is experimentally confirmed to bind (604 nM by BLI), so it
    must not demote a verdict. The finding still fires on the same inputs.
    """
    findings = check_patch_geometry(pair, _a(101))
    warn = next(f for f in findings if f.code == "HOTSPOT_COUNT_UNUSUAL")
    assert warn.severity is Severity.PASS
    assert warn.key is None
    assert warn.evidence["n_hotspots"] == 1
    assert warn.evidence["recommended"] == [
        RFDIFFUSION_MIN_HOTSPOTS,
        RFDIFFUSION_MAX_HOTSPOTS,
    ]
    assert "3-6" in warn.message


def test_nine_hotspots_are_an_unusual_count(pair):
    findings = check_patch_geometry(pair, _a(*range(101, 110)))
    warn = next(f for f in findings if f.code == "HOTSPOT_COUNT_UNUSUAL")
    assert warn.evidence["n_hotspots"] == 9


def test_counts_inside_the_recommended_band_do_not_warn(pair):
    for n in range(RFDIFFUSION_MIN_HOTSPOTS, RFDIFFUSION_MAX_HOTSPOTS + 1):
        keys = _a(*range(101, 101 + n))
        assert "HOTSPOT_COUNT_UNUSUAL" not in _codes(check_patch_geometry(pair, keys))


def test_hotspots_on_two_chains_warn_without_being_killed(pair):
    """A101-A102 face B201-B202 across 6 A: contiguous, but still suspicious."""
    keys = [
        ResidueKey("A", 101),
        ResidueKey("A", 102),
        ResidueKey("B", 201),
        ResidueKey("B", 202),
    ]
    findings = check_patch_geometry(pair, keys)
    codes = _codes(findings)
    assert "MULTI_CHAIN_SITE" in codes
    assert "NOT_CONTIGUOUS" not in codes
    warn = next(f for f in findings if f.code == "MULTI_CHAIN_SITE")
    assert warn.severity is Severity.WARN
    assert warn.key is None
    assert warn.evidence["chains"] == ["A", "B"]
    # Both readings must be stated: legitimate here, usually a mistake.
    assert "interface" in warn.message
    assert "mistake" in warn.message


def test_pass_is_withheld_and_order_is_canonical_when_findings_fire(pair):
    from hotspot_preflight.findings import sort_findings

    findings = check_patch_geometry(pair, _a(101, 110))
    assert "PATCH_GEOMETRY_OK" not in _codes(findings)
    assert findings == sort_findings(findings)


def test_empty_hotspot_list_is_rejected(pair):
    with pytest.raises(ValueError, match="no hotspot"):
        check_patch_geometry(pair, [])


def test_unmodelled_hotspots_do_not_produce_a_geometry_verdict(
    cif_without_unobs_category,
):
    """Residues 104 and 105 have no coordinates. Existence is another check's
    verdict, so patch geometry must neither claim them nor claim to be OK."""
    target = load_target(cif_without_unobs_category)
    findings = check_patch_geometry(target, _a(101, 104, 105))
    codes = _codes(findings)
    assert "PATCH_GEOMETRY_OK" not in codes
    assert not any(c.startswith("UNMODELLED") for c in codes)
    assert not any(c.startswith("BURIED") for c in codes)
    for f in findings:
        assert f.evidence.get("n_without_coordinates") == 2


def test_check_emits_no_burial_or_numbering_codes(pair):
    """C5 owns geometry only. Overlapping another check's codes would double
    count the same site in the aggregate verdict."""
    owned = {
        "NOT_CONTIGUOUS",
        "PATCH_TOO_LARGE",
        "HOTSPOT_COUNT_UNUSUAL",
        "MULTI_CHAIN_SITE",
        "PATCH_GEOMETRY_OK",
    }
    for keys in (_a(101), _a(101, 102, 103), _a(101, 110), _a(*range(101, 111))):
        for finding in check_patch_geometry(pair, keys):
            assert finding.code in owned
            assert finding.check == CHECK_NAME


# ---------------------------------------------------------------------------
# Crystal symmetry: a lattice neighbour is not a patch neighbour
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_neighbour_search_and_graph_reject_crystal_symmetry(real_1tim_for_patch: Path):
    """A lattice neighbour is not a patch neighbour.

    1TIM is P 2 1 2 1 2 1 with a real cell, so a NeighborSearch built with that
    cell returns lattice images; growing a patch into one would report a surface
    that exists only in the crystal. The control half proves the hazard is real.
    The second half is its behavioural form: a symmetry mate maps back onto the
    author residue it copies, so a leak shows up as an edge between two residues
    nowhere near each other in the deposited coordinates.
    """
    target = load_target(real_1tim_for_patch)
    model = target.st[0]

    def images(search) -> set[int]:
        found: set[int] = set()
        for chain in model:
            for res in chain:
                for atom in res:
                    for mark in search.find_atoms(atom.pos, "\0", radius=8.0):
                        found.add(mark.image_idx)
        return found

    control = gemmi.NeighborSearch(model, target.st.cell, 8.0).populate()
    assert images(control) != {0}, "control: the real cell does return images"
    assert images(_neighbour_search(model, 8.0)) == {0}

    keys = [ResidueKey("A", r.seqid.num) for r in model["A"] if len(r)]
    graph = neighbour_graph(target, keys, cutoff_a=8.0)
    centroids = {k: residue_centroid(target, k) for k in keys}
    for key, partners in graph.items():
        for other in partners:
            a, b = centroids[key], centroids[other]
            span = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
            assert span < 8.0 + 15.0, f"{key}-{other} are {span:.1f} A apart"


@pytest.fixture(scope="session")
def real_1tim_for_patch() -> Path:
    """1TIM, the crystal-symmetry control. Cached next to the other entries."""
    import urllib.error
    import urllib.request

    cache = Path(__file__).resolve().parents[1] / ".cache"
    cache.mkdir(exist_ok=True)
    path = cache / "1tim_updated.cif"
    if not path.exists():  # pragma: no cover - network path
        url = "https://www.ebi.ac.uk/pdbe/entry-files/download/1tim_updated.cif"
        try:
            urllib.request.urlretrieve(url, path)
        except (urllib.error.URLError, OSError) as exc:
            pytest.skip(f"cannot download 1TIM: {exc}")
    return path


# ---------------------------------------------------------------------------
# 6F5J: the real epitope this project exists for
# ---------------------------------------------------------------------------

# Chain C of the DWV capsid: the epitope of the one binder that measurably bound
# (l79_s469532_mpnn9, KD_app ~600 nM by BLI). Enumeration must find this.
EPITOPE_CHAIN = "C"
EPITOPE_RESIDUES = (325, 326)


@pytest.fixture(scope="session")
def f5j_profile(real_6f5j: Path):
    target = load_target(real_6f5j)
    profile = compute_burial(
        target.st,
        context="chain",
        focus_chain=EPITOPE_CHAIN,
        reference=reference_max_sasa(target.st),
    )
    return target, profile


@pytest.mark.network
def test_the_real_epitope_lands_in_an_enumerated_patch(f5j_profile):
    target, profile = f5j_profile
    keys = [ResidueKey(EPITOPE_CHAIN, n) for n in EPITOPE_RESIDUES]
    patches = enumerate_patches(target, profile, chain=EPITOPE_CHAIN)
    assert any(all(k in p.residues for k in keys) for p in patches), (
        f"no enumerated patch contains {', '.join(str(k) for k in keys)}"
    )


@pytest.mark.network
def test_the_real_epitope_is_not_called_discontiguous(f5j_profile):
    target, _ = f5j_profile
    keys = [ResidueKey(EPITOPE_CHAIN, n) for n in EPITOPE_RESIDUES]
    assert "NOT_CONTIGUOUS" not in _codes(check_patch_geometry(target, keys))


@pytest.mark.network
def test_enumeration_on_a_real_chain_is_fast_enough(f5j_profile):
    """Generous by design: this guards the O(n*k) contract, not the constant.

    A naive all-pairs-of-atoms implementation on a chain this size takes
    minutes, so a limit two orders of magnitude above the measured time still
    catches the regression that matters.
    """
    target, profile = f5j_profile
    start = time.perf_counter()
    patches = enumerate_patches(target, profile, chain=EPITOPE_CHAIN)
    elapsed = time.perf_counter() - start
    assert patches
    assert elapsed < 30.0, f"enumeration took {elapsed:.1f}s"
