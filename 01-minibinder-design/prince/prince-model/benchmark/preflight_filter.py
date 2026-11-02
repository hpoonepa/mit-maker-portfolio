# SPDX-License-Identifier: MIT
"""The `preflight` filter: our own checks, driven over benchmark antigens.

This is the arm that makes the project's claim measurable. Everything else in
``benchmark/`` is scaffolding; this is the only place where
``hotspot_preflight``'s structural checks actually run against SAbDab
antigens, and it is what turns kill-reason prevalence from a schema into a
number.

For one antigen it loads the structure, runs ``check_resolved``,
``check_numbering``, ``check_burial`` and ``check_patch_geometry``, and returns
the KILLed residues **with the finding code that killed each one**. A boolean
would make the primary metric unreportable: "the filter wrongly rejected 5% of
observed epitope residues" is not actionable, whereas "`BURIED_IN_ASSEMBLY`
caused every one of them" names the check to fix.

Three deliberate choices, each a trap already paid for in this repo:

* **One reference table per antigen.** ``reference_max_sasa`` is called once
  per structure and passed to every ``compute_burial`` call this module makes,
  because ``relative_sasa`` values stay inside 0-1 and keep their ordering
  even when the denominator silently changes — so a rescale is invisible in
  the output and only ``BurialProfile.reference_id`` catches it.
* **Gate on ``anchor_mean``, never ``anchor_max``.** On a maximum, one
  partly-occluded rim residue kills a patch that is clean everywhere else,
  which mass-kills surface near any oligomer contact. This module never reads
  ``anchor_max``; there is a test asserting that.
* **An antigen with no declared assembly is counted, not absorbed.**
  ``check_burial`` emits ``NO_ASSEMBLY_DEFINED`` as a WARN and measures the
  isolated chain, where every assembly delta is zero by construction. Those
  antigens cannot exercise assembly-awareness at all, so the code is surfaced
  as a site-level warning and its prevalence is reported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Collection, Iterable, Sequence

from hotspot_preflight.checks.burial import check_burial
from hotspot_preflight.checks.numbering import check_numbering
from hotspot_preflight.checks.patch import check_patch_geometry
from hotspot_preflight.checks.resolved import check_resolved
from hotspot_preflight.findings import Finding, Severity
from hotspot_preflight.report import select_assembly
from hotspot_preflight.residue import HotspotParseError, ResidueKey, parse_hotspot_spec

from .arms import FilterOutput, register_filter
from .evaluate import BenchmarkInstance, PredictorOutput
from .structures import STRUCTURE_SUFFIXES, StructureUnavailable, load_antigen, locate_structure

__all__ = [
    "PreflightFilter",
    "register_preflight",
    "parse_residue_keys",
    "ASSEMBLY_FALLBACK_CODE",
]

LOGGER = logging.getLogger(__name__)

ASSEMBLY_FALLBACK_CODE = "NO_ASSEMBLY_DEFINED"


def parse_residue_keys(
    tokens: Iterable[str], known_chains: Collection[str] | None = None
) -> list[ResidueKey]:
    """Parse manifest residue tokens (``"C325"``) into :class:`ResidueKey`.

    Delegates to ``parse_hotspot_spec`` rather than re-implementing the
    grammar, so insertion codes (``"A52A"``) and the bare-number rejection
    behave identically to the CLI. A second parser would be a second thing to
    keep correct.

    ``known_chains`` resolves a real ambiguity in the ``{chain}{number}`` token
    format: when a chain id ends in a digit the split is not determined by the
    string. 9axw has antigen chains ``AA1`` and ``BA1``, so ``AA147`` means
    chain ``AA1`` residue 47, while the same token against a chain called ``AA``
    means residue 147. Only the structure's chain list can decide, so pass it;
    without it the greedy alphabetic prefix wins and the residue is attributed
    to a chain that may not exist.

    The longest matching chain id wins, because it is the more specific reading
    and because a shorter prefix matching is exactly the failure being fixed. A
    token matching no known chain is parsed greedily and returned, so a residue
    naming a genuinely absent chain still becomes a key the caller can report
    NO_SUCH_CHAIN about rather than an exception.
    """
    cleaned = [t.strip() for t in tokens if t.strip()]
    if not cleaned:
        return []
    if not known_chains:
        return parse_hotspot_spec(",".join(cleaned))

    # Longest first: "AA1" must be tried before "AA".
    by_length = sorted(known_chains, key=len, reverse=True)
    out: list[ResidueKey] = []
    for token in cleaned:
        out.extend(_parse_one(token, by_length))
    # Deduplicate while preserving order, matching parse_hotspot_spec.
    return list(dict.fromkeys(out))


def _parse_one(token: str, chains_longest_first: Sequence[str]) -> list[ResidueKey]:
    """One token, resolved against known chain ids before falling back."""
    for chain in chains_longest_first:
        if not token.startswith(chain) or len(token) == len(chain):
            continue
        rest = token[len(chain):]
        try:
            # Re-use the grammar for the remainder by re-attaching a chain the
            # parser cannot mis-split: a single letter with no digits.
            parsed = parse_hotspot_spec(f"Z{rest}")
        except HotspotParseError:
            continue
        return [replace(k, auth_asym_id=chain) for k in parsed]
    return parse_hotspot_spec(token)


@dataclass(frozen=True)
class PreflightFilter:
    """Run the structural checks over one benchmark antigen.

    Args:
        structure_dir: directory holding downloaded coordinates. Not fetched
            here: a filter that hits the network mid-evaluation would make the
            run non-reproducible and the timings meaningless.
        run_burial: run ``check_burial``. The expensive one (SASA over an
            expanded assembly), so it is switchable for smoke runs — any run
            with it off is labelled through :attr:`note`.
        run_patch_geometry: run ``check_patch_geometry`` over each proposed
            patch.
        anchor_mean_floor: if set, a patch whose ``anchor_mean`` falls below
            this is killed. Applies only to predictions whose patches carry an
            ``anchor_mean``; ``anchor_max`` is never read.
    """

    structure_dir: Path
    run_burial: bool = True
    run_patch_geometry: bool = True
    anchor_mean_floor: float | None = None
    #: Mutable counters, shared across calls. A frozen dataclass holding a
    #: mutable dict is deliberate: the filter's identity must stay stable so
    #: arm pairing by object identity keeps working, while the tallies
    #: accumulate across the run.
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def note(self) -> str:
        """Text the report prints verbatim beside this arm."""
        off = [
            name
            for name, on in (("burial", self.run_burial),
                             ("patch_geometry", self.run_patch_geometry))
            if not on
        ]
        parts = [f"checks disabled: {', '.join(off)}"] if off else []
        if self.anchor_mean_floor is not None:
            parts.append(f"anchor_mean floor {self.anchor_mean_floor} (never anchor_max)")
        return "; ".join(parts)

    def locate(self, instance: BenchmarkInstance) -> Path | None:
        """Path to this instance's structure, or None if there is none.

        Separate from :meth:`__call__` so a caller can drop unavailable
        instances *before* evaluating and log each drop with its reason,
        rather than discovering the gap as a suspiciously clean kill rate.
        """
        return locate_structure(self.structure_dir, instance.pdb_id)

    def __call__(
        self,
        instance: BenchmarkInstance,
        prediction: PredictorOutput | None = None,
    ) -> FilterOutput:
        # The antigen is isolated from the complex FIRST. Running the checks
        # on the deposited file would measure the antigen with its antibody
        # still bound, so BURIED_IN_ASSEMBLY would fire on the real epitope
        # and the false-rejection rate would be an artifact of the crop rather
        # than a property of the filter. Spec 4.1 requires "the antigen alone".
        target, used_assembly = load_antigen(
            self.structure_dir, instance.pdb_id, instance.antigen_chains,
            use_assembly=self.run_burial,
        )
        self._bump("assembly_used" if used_assembly else "no_assembly_declared")
        # Mutates target.st.assemblies in place, and must precede check_burial,
        # which always expands assemblies[0] and takes no assembly argument.
        select_assembly(target, None)
        self._bump("instances")

        # The DECLARED antigen chains, not `target.chain_ids`. Expanding a
        # biological assembly adds copy chains named after the original with a
        # suffix — chain N of 1nca becomes N, N2, N3, N4 — and resolving a token
        # against those makes "N326" read as chain N3 residue 26. The manifest's
        # tokens were written against the chains the manifest declares.
        candidates = self._candidate_keys(
            instance, prediction,
            known_chains={c.strip() for c in instance.antigen_chains if c.strip()},
        )
        if not candidates:
            return FilterOutput(frozenset())

        findings: list[Finding] = []
        findings.extend(check_resolved(target, candidates))
        findings.extend(check_numbering(target, candidates))

        if self.run_burial:
            # check_burial raises on an unknown chain while check_resolved
            # reports it with a better message, so pre-filter by chain exactly
            # as report.run_preflight does.
            present = set(target.chain_ids)
            burial_keys = [k for k in candidates if k.auth_asym_id in present]
            if burial_keys:
                findings.extend(check_burial(target, burial_keys))

        killed: dict[str, list[str]] = {}
        warnings: set[str] = set()
        self._absorb(findings, killed, warnings, scope=candidates)

        if self.run_patch_geometry and prediction is not None:
            self._patch_checks(target, prediction, killed, warnings)

        return FilterOutput(
            killed=frozenset(killed),
            reasons={key: tuple(sorted(set(codes))) for key, codes in killed.items()},
            warnings=tuple(sorted(warnings)),
        )

    # -- internals ---------------------------------------------------------
    def _bump(self, name: str) -> None:
        self.stats[name] = self.stats.get(name, 0) + 1

    def _candidate_keys(
        self,
        instance: BenchmarkInstance,
        prediction: PredictorOutput | None,
        known_chains: Collection[str] | None = None,
    ) -> list[ResidueKey]:
        """Residues this filter must judge.

        The union of every residue the predictor proposed and the observed
        epitope. The epitope is included deliberately: the false-rejection
        rate is only measurable if the filter actually renders a verdict on
        the residues an antibody was seen to touch, even when no proposed
        patch happened to cover them.
        """
        tokens: set[str] = set(instance.epitope_residues)
        if prediction is not None:
            for patch in prediction.ranked_patches:
                tokens.update(patch)
        try:
            return parse_residue_keys(sorted(tokens), known_chains)
        except HotspotParseError as exc:
            # Synthetic or malformed keys (a test double's "pdb_decoy0_1") are
            # not residues; judging them is meaningless, so judge the epitope
            # alone rather than failing the whole instance.
            LOGGER.debug("unparseable candidate keys for %s: %s", instance.pdb_id, exc)
            try:
                return parse_residue_keys(
                    sorted(instance.epitope_residues), known_chains
                )
            except HotspotParseError:
                return []

    def _absorb(
        self,
        findings: Sequence[Finding],
        killed: dict[str, list[str]],
        warnings: set[str],
        *,
        scope: Sequence[ResidueKey],
    ) -> None:
        """Fold findings into per-residue kills and site-level warnings.

        A site-level KILL (``key=None``, e.g. ``NOT_CONTIGUOUS``) condemns the
        whole site, so it is attributed to every residue in ``scope`` — the
        alternative is a kill with no residue attached, which the prevalence
        accounting could not place.
        """
        for finding in findings:
            if finding.severity is Severity.KILL:
                targets = [finding.key] if finding.key is not None else list(scope)
                for key in targets:
                    killed.setdefault(str(key), []).append(finding.code)
            elif finding.severity is Severity.WARN and finding.key is None:
                warnings.add(finding.code)

    def _patch_checks(
        self,
        target: object,
        prediction: PredictorOutput,
        killed: dict[str, list[str]],
        warnings: set[str],
    ) -> None:
        """Run patch geometry per proposed patch, plus the anchor_mean gate."""
        for position, patch in enumerate(prediction.ranked_patches):
            try:
                keys = parse_residue_keys(sorted(patch))
            except HotspotParseError:
                continue
            if not keys:
                continue
            self._absorb(
                check_patch_geometry(target, keys), killed, warnings, scope=keys
            )
            self._anchor_gate(prediction, position, keys, killed)

    def _anchor_gate(
        self,
        prediction: PredictorOutput,
        position: int,
        keys: Sequence[ResidueKey],
        killed: dict[str, list[str]],
    ) -> None:
        """Kill a patch whose mean anchor exposure is below the floor.

        Reads ``anchor_mean`` only. ``anchor_max`` is named
        ``anchor_max_do_not_threshold`` in the tool's own JSON for a reason: a
        single partly-occluded rim residue would condemn a patch that is clean
        everywhere else, mass-killing surface anywhere near an oligomer
        contact.
        """
        if self.anchor_mean_floor is None:
            return
        scored = getattr(prediction, "scored_patches", None)
        if scored is None or position >= len(scored):
            return
        anchor_mean = getattr(scored[position], "anchor_mean", None)
        if anchor_mean is None or anchor_mean >= self.anchor_mean_floor:
            return
        for key in keys:
            killed.setdefault(str(key), []).append("ANCHOR_MEAN_BELOW_FLOOR")


def register_preflight(
    structure_dir: str | Path,
    *,
    name: str = "preflight",
    run_burial: bool = True,
    run_patch_geometry: bool = True,
    anchor_mean_floor: float | None = None,
) -> PreflightFilter:
    """Build and register the filter, returning it so its stats stay readable.

    Registration is an explicit call rather than an import side effect because
    the filter needs to be told where the coordinates are, and a registry
    entry that silently pointed at the wrong directory would produce a clean
    kill rate for the wrong reason.
    """
    directory = Path(structure_dir)
    if not directory.is_dir():
        raise NotADirectoryError(
            f"structure_dir {directory} is not a directory; the preflight "
            f"filter reads downloaded coordinates and never fetches them "
            f"mid-run, so point it at the download cache"
        )
    filter_fn = PreflightFilter(
        structure_dir=directory,
        run_burial=run_burial,
        run_patch_geometry=run_patch_geometry,
        anchor_mean_floor=anchor_mean_floor,
    )
    register_filter(name, filter_fn)
    return filter_fn
