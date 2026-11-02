#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Atom-level geometric features for candidate surface residues.

The existing 51-feature block is residue-centroid level: one point per residue
plus multiscale statistics over other residues' centroids. That throws away
everything a centroid cannot say -- which way a side chain points, what the
chemical micro-environment around it looks like, whether the local surface is a
pocket or a bump, and how deep the residue sits.

This module rebuilds the descriptor from the atoms. Every family here is a
long-established structural-biology measurement, implemented from first
principles on top of ``gemmi``/``numpy``/``scipy`` only:

* side-chain orientation relative to a locally estimated outward normal,
* atom-type radial distribution functions in three shells,
* local surface shape from the covariance of nearby solvent-exposed atoms,
* ray-cast "pocketness" on a Fibonacci sphere,
* depth, measured against the convex hull and the molecular surface,
* per-atom solvent accessibility (own Shrake-Rupley) aggregated to the residue
  and split backbone/side-chain and polar/apolar,
* hydrogen-bond and formal-charge micro-environment,
* packing density and backbone-geometry descriptors.

Hard constraints, enforced rather than assumed:

* No antibody atoms. The loader has already removed them; nothing here reads a
  complex.
* No epitope labels. ``instances[].epitope`` is read only by
  :func:`sanity_report`, which is a report and writes nothing into the features.
* No residue or chain identity. The residue's own atom names and residue name
  are used *only* to split its atoms into backbone/side-chain and polar/apolar
  -- the same split a SASA program makes -- never emitted as a type code. Every
  composition count is over *other* residues' atoms. ``size_sc_heavy_atoms`` is
  the one feature that correlates with identity by construction (side-chain
  size); it is named so it can be dropped in one line.

Implementation note: this block is recomputed at a few thousand contexts, so it
is written as array work rather than a per-residue Python loop. One KD-tree per
structure, one flat residue-atom neighbour list, and every per-residue statistic
is a segment reduction (:func:`numpy.bincount` / :func:`numpy.minimum.reduceat`)
or a batched 3x3 eigendecomposition over that list. The naive version spent 57%
of its time rebuilding a KD-tree once per residue.
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

HERE = Path(__file__).resolve().parent
ROOT = REPO
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import gemmi  # noqa: E402

from benchmark.structures import load_antigen  # noqa: E402

DEFAULT_CACHE_DIR = DATA / 'cache_full_antigen'
CIF_DIR = ROOT / ".cache/benchmark/cif"
DEFAULT_OUT_DIR = DATA / 'atom_cache'
NAMES_PATH = DATA / 'atom_feature_names.json'
RECEIPT_PATH = DATA / 'atom_receipt.json'

#: Bumped whenever a column's definition changes. Stored in every ``.npz`` so
#: ``--resume`` can tell "already done" from "done by an older definition" --
#: resuming on the context id alone would silently mix two feature blocks.
FEATURE_VERSION = "atom_v2"

# ---------------------------------------------------------------------------
# Chemistry tables. Element radii and the donor/acceptor/charge assignments are
# textbook; they are written out rather than imported so the numbers are
# auditable in place.
# ---------------------------------------------------------------------------

VDW = {"C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80, "SE": 1.90, "P": 1.80}
VDW_DEFAULT = 1.70
PROBE = 1.4
SASA_POINTS = 92

BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "OXT"})
HYDROXYL = frozenset({"OG", "OG1", "OH"})
#: Formal charge at pH 7, split across the atoms that share the delocalisation.
#: Histidine is deliberately uncharged: its protonation is pH- and
#: environment-dependent and a feature that silently assumes one is a liability.
FORMAL_CHARGE = {
    ("LYS", "NZ"): 1.0,
    ("ARG", "NH1"): 0.5,
    ("ARG", "NH2"): 0.5,
    ("ASP", "OD1"): -0.5,
    ("ASP", "OD2"): -0.5,
    ("GLU", "OE1"): -0.5,
    ("GLU", "OE2"): -0.5,
}

SHELLS = ((0.0, 4.0), (4.0, 8.0), (8.0, 12.0))
SHELL_TAGS = ("0_4", "4_8", "8_12")
SHAPE_RADII = (8.0, 12.0, 16.0)
ELEC_RADII = (5.0, 8.0)
PACK_RADII = (6.0, 8.0, 10.0)
COULOMB_RADIUS = 12.0
GAP_CAP = 12.0
NEIGHBOUR_RADIUS = 16.0  # covers every radius above; the one query we make

RAY_DIRECTIONS = 30
RAY_BLOCK_DIST = 2.0  # a ray passing this close to an atom centre is blocked
RAY_T_MIN = 2.0
RAY_MAX = 14.0
RAY_THRESHOLDS = (6.0, 9.0, 13.0)

SURFACE_ATOM_SASA = 1.0  # A^2; above this an atom is on the molecular surface
EXPOSED_ATOM_SASA = 5.0  # A^2; a comfortably solvent-facing atom
#: Total residue SASA below which the *composition* ratios report 0 instead of
#: a ratio. A fully buried residue has a total of order 1e-2 A^2, and dividing
#: one near-zero by another turned float rounding into a 0-or-1 coin flip for
#: the polar and side-chain fractions. A residue the solvent cannot reach has no
#: meaningful surface composition, so zero is the honest answer.
SASA_RATIO_FLOOR = 1.0

CA_NEIGHBOUR_RADIUS = 10.0
HBOND_DIST = 3.5
HBOND_SEQ_SEPARATION = 3


def _feature_names() -> list[str]:
    names = [
        "orient_has_sidechain",
        "orient_sc_arm_len",
        "orient_dot_local_out",
        "orient_dot_global_out",
        "orient_dot_surface_normal",
        "orient_local_out_dot_normal",
        "orient_sc_sasa_fraction",
        "orient_sc_minus_bb_depth",
    ]
    for tag in SHELL_TAGS:
        names += [
            f"rdf{tag}_log_count",
            f"rdf{tag}_frac_C",
            f"rdf{tag}_frac_N",
            f"rdf{tag}_frac_O",
            f"rdf{tag}_frac_S",
            f"rdf{tag}_frac_backbone",
            f"rdf{tag}_frac_exposed",
            f"rdf{tag}_mean_atom_sasa",
        ]
    for radius in SHAPE_RADII:
        tag = int(radius)
        names += [
            f"shape{tag}_log_surf_count",
            f"shape{tag}_eig0_frac",
            f"shape{tag}_eig1_frac",
            f"shape{tag}_planarity",
            f"shape{tag}_anisotropy",
            f"shape{tag}_convexity_dot",
            f"shape{tag}_mean_signed_offset",
        ]
    names += [
        "ray_blocked_frac_6",
        "ray_blocked_frac_9",
        "ray_blocked_frac_13",
        "ray_mean_free_path",
        "ray_std_free_path",
        "ray_open_anisotropy",
    ]
    names += [
        "depth_hull_signed",
        "depth_hull_max_atom",
        "depth_to_surface_atom",
        "depth_bb_to_surface_atom",
        "depth_com_over_rg",
        "depth_com_over_max",
    ]
    names += [
        "sasa_total_abs",
        "sasa_total_rel",
        "sasa_bb_abs",
        "sasa_bb_rel",
        "sasa_sc_abs",
        "sasa_sc_rel",
        "sasa_polar_abs",
        "sasa_polar_rel",
        "sasa_apolar_abs",
        "sasa_apolar_rel",
        "sasa_frac_polar",
        "sasa_frac_sidechain",
        "sasa_exposed_atom_frac",
    ]
    for radius in ELEC_RADII:
        tag = int(radius)
        names += [
            f"elec{tag}_log_donors",
            f"elec{tag}_log_acceptors",
            f"elec{tag}_log_positive",
            f"elec{tag}_log_negative",
            f"elec{tag}_net_charge_density",
            f"elec{tag}_hbond_balance",
        ]
    names += ["elec_min_dist_charged", "elec_min_dist_polar", "elec_coulomb_12A"]
    names += [f"pack_density_{int(r)}" for r in PACK_RADII]
    names += [
        "chain_ca_span",
        "chain_pseudo_angle_cos",
        "chain_pseudo_dihedral_cos",
        "chain_pseudo_dihedral_sin",
        "chain_log_ca_within_10",
        "chain_bb_hbond_count",
        "chain_mean_contact_order",
    ]
    names += ["size_sc_heavy_atoms"]
    return names


FEATURE_NAMES = _feature_names()
N_FEATURES = len(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


def fibonacci_sphere(n: int) -> np.ndarray:
    """``n`` roughly equidistant unit vectors.

    The golden-angle spiral rather than a random sample: a ray cast or a SASA
    estimate on random directions has variance that moves between residues, and
    a feature whose noise differs per residue is not comparable across them.
    """
    i = np.arange(n, dtype=float) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = math.pi * (1.0 + 5.0**0.5) * i
    return np.stack(
        [np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)],
        axis=1,
    )


SASA_SPHERE = fibonacci_sphere(SASA_POINTS)
RAY_DIRS = fibonacci_sphere(RAY_DIRECTIONS)


def shrake_rupley(pos: np.ndarray, radii: np.ndarray, block: int = 48) -> np.ndarray:
    """Per-atom solvent accessible surface area, in square angstroms.

    Shrake-Rupley: roll a probe sphere over each atom's expanded surface and
    count the sample points no other expanded sphere occludes. Implemented here
    rather than shelled out because the residue aggregation needs the
    backbone/side-chain and polar/apolar splits, which a per-residue total
    cannot be taken apart into.

    Atoms are processed in blocks against a single shared tree. The occluder set
    comes from a k-nearest query, and any atom whose k-th neighbour is still
    inside its occlusion cutoff falls back to an exact ball query -- so the
    k-cap is a speed choice, never a correctness one.
    """
    n_atoms = len(pos)
    if n_atoms == 0:
        return np.zeros(0)
    expanded = radii + PROBE
    cutoff = expanded + float(expanded.max())
    tree = cKDTree(pos)
    out = np.empty(n_atoms)
    k = int(min(n_atoms, 72))
    exact: list[int] = []
    for start in range(0, n_atoms, block):
        stop = min(start + block, n_atoms)
        idx = np.arange(start, stop)
        dist, jj = tree.query(pos[idx], k=k)
        dist = np.atleast_2d(dist)
        jj = np.atleast_2d(jj)
        if k < n_atoms:
            short = dist[:, -1] < cutoff[idx]
            if short.any():
                exact.extend(idx[short].tolist())
        valid = (jj != idx[:, None]) & (dist < cutoff[idx][:, None])
        points = (
            pos[idx][:, None, :]
            + SASA_SPHERE[None, :, :] * expanded[idx][:, None, None]
        )
        # Float64 and an explicit difference rather than the |a|^2 - 2a.b + |b|^2
        # expansion: the expansion is one matmul cheaper but cancels catastrophically
        # on coordinates near 100 A, and an error of a fraction of a sample point is
        # enough to move an atom across the 1 A^2 surface threshold -- which then
        # moves every shape and exposure feature that reads the surface set.
        delta = points[:, :, None, :] - pos[jj][:, None, :, :]
        d2 = np.einsum("bpkc,bpkc->bpk", delta, delta)
        hit = (d2 < (expanded[jj] ** 2)[:, None, :]) & valid[:, None, :]
        free = ~hit.any(axis=2)
        out[start:stop] = 4.0 * math.pi * expanded[idx] ** 2 * free.mean(axis=1)
    for i in exact:
        nb = np.asarray(
            [j for j in tree.query_ball_point(pos[i], cutoff[i]) if j != i], dtype=int
        )
        points = pos[i] + SASA_SPHERE * expanded[i]
        if nb.size:
            delta = points[:, None, :] - pos[nb][None, :, :]
            d2 = np.einsum("pkc,pkc->pk", delta, delta)
            free = ~np.any(d2 < (expanded[nb] ** 2)[None, :], axis=1)
        else:
            free = np.ones(SASA_POINTS, dtype=bool)
        out[i] = 4.0 * math.pi * expanded[i] ** 2 * float(free.mean())
    return out


def isolated_sasa(pos: np.ndarray, radii: np.ndarray, groups: list[np.ndarray]) -> np.ndarray:
    """Per-atom SASA with every other residue deleted.

    This is the reference the relative values divide by. Deriving it from the
    structure rather than reading a tabulated per-residue maximum keeps the
    normaliser free of any residue-type lookup, and makes it exact for the
    modified residues the tables do not list.
    """
    out = np.zeros(len(pos))
    for atoms in groups:
        n = len(atoms)
        if n == 0:
            continue
        p = pos[atoms]
        r = radii[atoms] + PROBE
        points = p[:, None, :] + SASA_SPHERE[None, :, :] * r[:, None, None]
        delta = points[:, :, None, :] - p[None, None, :, :]
        d2 = np.einsum("apkc,apkc->apk", delta, delta)
        hit = d2 < (r**2)[None, None, :]
        hit[np.arange(n), :, np.arange(n)] = False
        out[atoms] = 4.0 * math.pi * r**2 * (~hit.any(axis=2)).mean(axis=1)
    return out


def _unit_rows(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    return np.divide(vec, norm, out=np.zeros_like(vec), where=norm > 1e-8)


def _seg_sum(seg: np.ndarray, weights, n: int) -> np.ndarray:
    if seg.size == 0:
        return np.zeros(n)
    return np.bincount(seg, weights=weights, minlength=n)[:n].astype(float)


def _seg_min(seg: np.ndarray, value: np.ndarray, n: int, cap: float) -> np.ndarray:
    """Smallest ``value`` per segment, ``cap`` where a segment is empty."""
    out = np.full(n, cap)
    if seg.size:
        order = np.argsort(value, kind="stable")
        seg_sorted = seg[order]
        uniq, first = np.unique(seg_sorted, return_index=True)
        out[uniq] = np.minimum(value[order][first], cap)
    return out


def _batched_cov(
    seg: np.ndarray, points: np.ndarray, n: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-segment count, centroid and covariance, as stacked arrays.

    The covariance comes from segment sums of the coordinates and of their outer
    products, so a few thousand local point clouds are reduced in one pass
    instead of one ``numpy`` call each.

    ``points`` must be offsets from each segment's own reference point, not
    absolute coordinates. ``E[xx] - E[x]E[x]`` loses most of its significant
    digits when the mean is far from the origin -- on crystal coordinates near
    100 A that cancellation visibly moved the eigenvalue ratios of the smallest
    patch. Offsets are O(10 A), so the subtraction is harmless.
    """
    count = _seg_sum(seg, None, n)
    safe = np.maximum(count, 1.0)[:, None]
    mean = np.stack([_seg_sum(seg, points[:, c], n) for c in range(3)], axis=1) / safe
    second = np.empty((n, 3, 3))
    for a in range(3):
        for b in range(a, 3):
            s = _seg_sum(seg, points[:, a] * points[:, b], n) / safe[:, 0]
            second[:, a, b] = s
            second[:, b, a] = s
    cov = second - mean[:, :, None] * mean[:, None, :]
    return count, mean, cov


def _safe_eigh(cov: np.ndarray, usable: np.ndarray, with_vectors: bool):
    """Eigendecomposition of a stack of 3x3 covariances.

    Unusable segments (too few points to define a plane) get the identity so the
    batched call cannot fail; their outputs are zeroed by the caller.
    """
    work = cov.copy()
    work[~usable] = np.eye(3)
    work = 0.5 * (work + np.swapaxes(work, -1, -2))
    if with_vectors:
        return np.linalg.eigh(work)
    return np.linalg.eigvalsh(work)


# ---------------------------------------------------------------------------
# Structure -> atom arrays
# ---------------------------------------------------------------------------


def _is_amino_acid(res: gemmi.Residue) -> bool:
    info = gemmi.find_tabulated_residue(res.name)
    return info is not None and info.is_amino_acid()


def _keystr(chain_name: str, seqid) -> str:
    icode = seqid.icode
    return f"{chain_name}:{seqid.num}" + (f":{icode}" if icode else "")


class AtomModel:
    """Flat atom arrays for one antigen, plus the residue index that owns each.

    Every amino acid in the loaded (antibody-free) assembly is included,
    chains outside the declared antigen set too, because those chains are real
    protein that occludes and shapes the candidate surface. Only residues the
    cache names get a feature row.
    """

    def __init__(self, st: gemmi.Structure):
        pos: list[tuple[float, float, float]] = []
        radii: list[float] = []
        elem: list[str] = []
        names: list[str] = []
        is_bb: list[bool] = []
        donor: list[bool] = []
        acceptor: list[bool] = []
        charge: list[float] = []
        owner: list[int] = []

        self.atoms_of: list[np.ndarray] = []
        self.ca: list[int] = []
        self.n_atom: list[int] = []
        self.c_atom: list[int] = []
        self.chain_of: list[int] = []
        self.slot_of: list[int] = []
        self.seq_of: list[int] = []
        self.by_key: dict[str, int] = {}
        chain_ids: dict[str, int] = {}
        self.chain_members: dict[int, list[int]] = {}

        for chain in st[0]:
            chain_id = chain_ids.setdefault(chain.name, len(chain_ids))
            members = self.chain_members.setdefault(chain_id, [])
            for res in chain:
                if not _is_amino_acid(res):
                    continue
                start = len(pos)
                ca = n_bb = c_bb = -1
                for atom in res:
                    if atom.element.atomic_number <= 1:
                        continue
                    if atom.altloc not in ("\x00", "", "A"):
                        continue
                    symbol = atom.element.name.upper()
                    if atom.name == "CA":
                        ca = len(pos)
                    elif atom.name == "N":
                        n_bb = len(pos)
                    elif atom.name == "C":
                        c_bb = len(pos)
                    pos.append((atom.pos.x, atom.pos.y, atom.pos.z))
                    radii.append(VDW.get(symbol, VDW_DEFAULT))
                    elem.append(symbol)
                    names.append(atom.name)
                    is_bb.append(atom.name in BACKBONE_ATOMS)
                    donor.append(
                        (symbol == "N" and not (res.name == "PRO" and atom.name == "N"))
                        or atom.name in HYDROXYL
                    )
                    acceptor.append(
                        symbol == "O"
                        or (res.name == "HIS" and atom.name in ("ND1", "NE2"))
                    )
                    charge.append(FORMAL_CHARGE.get((res.name, atom.name), 0.0))
                    owner.append(len(self.atoms_of))
                if len(pos) == start:
                    continue
                index = len(self.atoms_of)
                self.atoms_of.append(np.arange(start, len(pos)))
                self.ca.append(ca)
                self.n_atom.append(n_bb)
                self.c_atom.append(c_bb)
                self.chain_of.append(chain_id)
                self.slot_of.append(len(members))
                self.seq_of.append(res.seqid.num)
                members.append(index)
                # Last writer wins, matching ``residue_points``' dict semantics
                # so an assembly that duplicates a key agrees with the cache.
                self.by_key[_keystr(chain.name, res.seqid)] = index

        self.pos = np.asarray(pos, dtype=float).reshape(-1, 3)
        self.radii = np.asarray(radii, dtype=float)
        self.elem = np.asarray(elem)
        self.is_bb = np.asarray(is_bb, dtype=bool)
        self.is_donor = np.asarray(donor, dtype=bool)
        self.is_acceptor = np.asarray(acceptor, dtype=bool)
        self.charge = np.asarray(charge, dtype=float)
        self.owner = np.asarray(owner, dtype=int)
        self.chain_arr = np.asarray(self.chain_of, dtype=int)
        self.slot_arr = np.asarray(self.slot_of, dtype=int)
        self.seq_arr = np.asarray(self.seq_of, dtype=int)
        self.n_res = len(self.atoms_of)


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def compute_features(st: gemmi.Structure, keys: list[str]) -> np.ndarray:
    model = AtomModel(st)
    if len(model.pos) == 0:
        raise ValueError("no heavy atoms in antigen")
    missing = [k for k in keys if k not in model.by_key]
    if missing:
        raise ValueError(
            f"{len(missing)} cache keys absent from structure: {missing[:5]}"
        )

    pos = model.pos
    rows = np.asarray([model.by_key[k] for k in keys], dtype=int)
    n = len(rows)

    atom_sasa = shrake_rupley(pos, model.radii)
    ref_sasa = isolated_sasa(pos, model.radii, [model.atoms_of[r] for r in rows])
    is_surface = atom_sasa > SURFACE_ATOM_SASA
    is_exposed = atom_sasa > EXPOSED_ATOM_SASA
    is_polar = np.isin(model.elem, ("N", "O"))

    com = pos.mean(axis=0)
    centred = pos - com
    rg = max(float(np.sqrt(np.mean(np.sum(centred**2, axis=1)))), 1e-6)
    max_from_com = max(float(np.sqrt(np.max(np.sum(centred**2, axis=1)))), 1e-6)

    tree = cKDTree(pos)

    # --- reference points, one small pass over the emitted residues ---------
    probe = np.zeros((n, 3))
    bb_point = np.zeros((n, 3))
    sc_dir = np.zeros((n, 3))
    has_sc = np.zeros(n)
    sc_count = np.zeros(n)
    for i, ridx in enumerate(rows):
        atoms = model.atoms_of[ridx]
        bb_mask = model.is_bb[atoms]
        bb_atoms, sc_atoms = atoms[bb_mask], atoms[~bb_mask]
        bb_point[i] = pos[bb_atoms].mean(axis=0) if bb_atoms.size else pos[atoms].mean(axis=0)
        ca = model.ca[ridx]
        anchor = pos[ca] if ca >= 0 else bb_point[i]
        if sc_atoms.size:
            probe[i] = pos[sc_atoms].mean(axis=0)
            has_sc[i] = 1.0
            sc_count[i] = float(sc_atoms.size)
            sc_dir[i] = probe[i] - anchor
        else:
            probe[i] = anchor
            # Glycine: the N-CA-C bisector points where CB would be, which is
            # the direction a binder sees, so the feature stays meaningful
            # instead of going to zero on every glycine.
            n_bb, c_bb = model.n_atom[ridx], model.c_atom[ridx]
            if n_bb >= 0 and c_bb >= 0:
                sc_dir[i] = anchor - 0.5 * (pos[n_bb] + pos[c_bb])
            else:
                sc_dir[i] = anchor - com
    sc_dir = _unit_rows(sc_dir)

    # --- one neighbour list, reused by every radius -------------------------
    raw = tree.query_ball_point(probe, NEIGHBOUR_RADIUS)
    counts = np.fromiter((len(x) for x in raw), dtype=int, count=n)
    pi = np.repeat(np.arange(n), counts)
    aj = (
        np.concatenate([np.asarray(x, dtype=int) for x in raw])
        if counts.sum()
        else np.zeros(0, dtype=int)
    )
    keep = model.owner[aj] != rows[pi] if aj.size else np.zeros(0, dtype=bool)
    pi, aj = pi[keep], aj[keep]
    offset = pos[aj] - probe[pi]
    dist = np.linalg.norm(offset, axis=1)

    blocks: list[np.ndarray] = []

    # --- local frame --------------------------------------------------------
    pack_mask = dist <= PACK_RADII[-1]
    pack_count, pack_mean, _ = _batched_cov(pi[pack_mask], offset[pack_mask], n)
    local_com = np.where((pack_count >= 4)[:, None], probe + pack_mean, com[None, :])
    local_out = _unit_rows(probe - local_com)
    global_out = _unit_rows(probe - com)
    local_out = np.where(
        (np.linalg.norm(local_out, axis=1) > 0)[:, None], local_out, global_out
    )

    surf_mask = is_surface[aj]
    shape_masks = [surf_mask & (dist <= r) for r in SHAPE_RADII]
    shape_stats = [_batched_cov(pi[m], offset[m], n) for m in shape_masks]
    # The widest surface patch defines the outward normal.
    wide_count, _, wide_cov = shape_stats[-1]
    usable = wide_count >= 4
    _, vecs = _safe_eigh(wide_cov, usable, with_vectors=True)
    normal = vecs[:, :, 0]
    flip = np.einsum("ij,ij->i", normal, local_out) < 0
    normal[flip] *= -1.0
    normal = np.where(usable[:, None], normal, local_out)

    # --- SASA aggregates ----------------------------------------------------
    row_of_atom = np.full(len(pos), -1, dtype=int)
    for i, ridx in enumerate(rows):
        row_of_atom[model.atoms_of[ridx]] = i
    owned = row_of_atom >= 0
    seg = row_of_atom[owned]
    bb_a = model.is_bb[owned]
    pol_a = is_polar[owned]
    s_a, r_a = atom_sasa[owned], ref_sasa[owned]

    def _split(weights, mask=None):
        w = weights if mask is None else weights * mask
        return _seg_sum(seg, w, n)

    total, total_ref = _split(s_a), _split(r_a)
    bb_s, bb_ref = _split(s_a, bb_a), _split(r_a, bb_a)
    sc_s, sc_ref = _split(s_a, ~bb_a), _split(r_a, ~bb_a)
    pol_s, pol_ref = _split(s_a, pol_a), _split(r_a, pol_a)
    apol_s, apol_ref = _split(s_a, ~pol_a), _split(r_a, ~pol_a)
    n_atoms_row = _seg_sum(seg, None, n)
    exposed_frac = _seg_sum(seg, is_exposed[owned].astype(float), n) / np.maximum(
        n_atoms_row, 1.0
    )

    def _rel(value, reference):
        return np.where(
            reference > 1e-6,
            np.minimum(value / np.maximum(reference, 1e-6), 1.5),
            0.0,
        )

    def _ratio(part, whole):
        """Composition fraction, zeroed where the denominator is meaningless."""
        return np.where(
            whole > SASA_RATIO_FLOOR, part / np.maximum(whole, SASA_RATIO_FLOOR), 0.0
        )

    # --- depth to the molecular surface -------------------------------------
    surf_pairs = surf_mask
    sc_gap = _seg_min(pi[surf_pairs], dist[surf_pairs], n, GAP_CAP) / GAP_CAP
    bb_dist = np.linalg.norm(pos[aj[surf_pairs]] - bb_point[pi[surf_pairs]], axis=1)
    bb_gap = _seg_min(pi[surf_pairs], bb_dist, n, GAP_CAP) / GAP_CAP

    # 1. side-chain orientation
    blocks.append(
        np.stack(
            [
                has_sc,
                np.minimum(np.linalg.norm(probe - bb_point, axis=1) / 6.0, 1.5),
                np.einsum("ij,ij->i", sc_dir, local_out),
                np.einsum("ij,ij->i", sc_dir, global_out),
                np.einsum("ij,ij->i", sc_dir, normal),
                np.einsum("ij,ij->i", local_out, normal),
                _ratio(sc_s, total),
                np.clip((bb_gap - sc_gap) * GAP_CAP / 5.0, -2.0, 2.0),
            ],
            axis=1,
        )
    )

    # 2. atom-type radial distribution
    rdf_cols = []
    for lo, hi in SHELLS:
        m = (dist >= lo) & (dist < hi)
        s, a = pi[m], aj[m]
        c = _seg_sum(s, None, n)
        safe = np.maximum(c, 1.0)
        rdf_cols.append(np.log1p(c) / 6.0)
        for symbol in ("C", "N", "O", "S"):
            rdf_cols.append(_seg_sum(s, (model.elem[a] == symbol).astype(float), n) / safe)
        rdf_cols.append(_seg_sum(s, model.is_bb[a].astype(float), n) / safe)
        rdf_cols.append(_seg_sum(s, is_exposed[a].astype(float), n) / safe)
        rdf_cols.append(_seg_sum(s, atom_sasa[a], n) / safe / 20.0)
    blocks.append(np.stack(rdf_cols, axis=1))

    # 3. local surface shape and curvature
    shape_cols = []
    for radius, (count, mean, cov) in zip(SHAPE_RADII, shape_stats):
        ok = count >= 4
        eig = _safe_eigh(cov, ok, with_vectors=False)
        e0, e1, e2 = eig[:, 0], eig[:, 1], eig[:, 2]
        tot = e0 + e1 + e2
        to_mean = mean  # already relative to this residue's probe point
        dot_out = np.einsum("ij,ij->i", to_mean, local_out)
        shape_cols += [
            np.where(ok, np.log1p(count) / 7.0, 0.0),
            np.where(ok & (tot > 1e-12), e0 / np.maximum(tot, 1e-12), 0.0),
            np.where(ok & (tot > 1e-12), e1 / np.maximum(tot, 1e-12), 0.0),
            np.where(ok & (e2 > 1e-12), (e1 - e0) / np.maximum(e2, 1e-12), 0.0),
            np.where(ok & (e2 > 1e-12), (e2 - e0) / np.maximum(e2, 1e-12), 0.0),
            np.where(ok, np.einsum("ij,ij->i", _unit_rows(to_mean), local_out), 0.0),
            np.where(ok, dot_out / radius, 0.0),
        ]
    blocks.append(np.stack(shape_cols, axis=1))

    # 4. ray-cast pocketness
    free = _cast_rays(probe, pos, pi, aj, dist, offset, n)
    norm_free = free / RAY_MAX
    blocks.append(
        np.stack(
            [np.mean(free <= t, axis=1) for t in RAY_THRESHOLDS]
            + [
                norm_free.mean(axis=1),
                norm_free.std(axis=1),
                np.linalg.norm(norm_free @ RAY_DIRS / RAY_DIRECTIONS, axis=1),
            ],
            axis=1,
        )
    )

    # 5. depth
    hull_depth, hull_atom_depth = _hull_depths(model, pos, probe, rows)
    probe_from_com = np.linalg.norm(probe - com, axis=1)
    blocks.append(
        np.stack(
            [
                hull_depth,
                hull_atom_depth,
                sc_gap,
                bb_gap,
                probe_from_com / rg,
                probe_from_com / max_from_com,
            ],
            axis=1,
        )
    )

    # 6. SASA aggregates
    blocks.append(
        np.stack(
            [
                total / 100.0,
                _rel(total, total_ref),
                bb_s / 100.0,
                _rel(bb_s, bb_ref),
                sc_s / 100.0,
                _rel(sc_s, sc_ref),
                pol_s / 100.0,
                _rel(pol_s, pol_ref),
                apol_s / 100.0,
                _rel(apol_s, apol_ref),
                _ratio(pol_s, total),
                _ratio(sc_s, total),
                exposed_frac,
            ],
            axis=1,
        )
    )

    # 7. hydrogen-bond and electrostatic micro-environment
    elec_cols = []
    for radius in ELEC_RADII:
        m = dist <= radius
        s, a = pi[m], aj[m]
        c = _seg_sum(s, None, n)
        don = _seg_sum(s, model.is_donor[a].astype(float), n)
        acc = _seg_sum(s, model.is_acceptor[a].astype(float), n)
        q = model.charge[a]
        pos_q = _seg_sum(s, np.where(q > 0, q, 0.0), n)
        neg_q = _seg_sum(s, np.where(q < 0, -q, 0.0), n)
        net = _seg_sum(s, q, n)
        elec_cols += [
            np.log1p(don) / 4.0,
            np.log1p(acc) / 4.0,
            np.log1p(pos_q) / 2.0,
            np.log1p(neg_q) / 2.0,
            np.where(c > 0, net / (1.0 + c) * 10.0, 0.0),
            np.where(c > 0, (don - acc) / (1.0 + don + acc), 0.0),
        ]
    charged_pairs = np.abs(model.charge[aj]) > 1e-9
    polar_pairs = is_polar[aj]
    elec_cols.append(
        _seg_min(pi[charged_pairs], dist[charged_pairs], n, GAP_CAP) / GAP_CAP
    )
    elec_cols.append(_seg_min(pi[polar_pairs], dist[polar_pairs], n, GAP_CAP) / GAP_CAP)
    cb = charged_pairs & (dist <= COULOMB_RADIUS)
    elec_cols.append(
        _seg_sum(pi[cb], model.charge[aj[cb]] / np.maximum(dist[cb], 1.0), n)
    )
    blocks.append(np.stack(elec_cols, axis=1))

    # 8. packing density
    pack_cols = []
    for radius in PACK_RADII:
        c = _seg_sum(pi[dist <= radius], None, n)
        pack_cols.append(c / (4.0 / 3.0 * math.pi * radius**3 * 0.1))
    blocks.append(np.stack(pack_cols, axis=1))

    # 9. backbone geometry, identity-free
    blocks.append(_chain_geometry(model, pos, rows, tree))

    # 10. side-chain size (identity-correlated by construction)
    blocks.append((sc_count / 8.0)[:, None])

    out = np.concatenate(blocks, axis=1)
    if out.shape != (n, N_FEATURES):
        raise ValueError(f"built {out.shape}, expected {(n, N_FEATURES)}")
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _cast_rays(
    probe: np.ndarray,
    pos: np.ndarray,
    pi: np.ndarray,
    aj: np.ndarray,
    dist: np.ndarray,
    offset: np.ndarray,
    n: int,
    chunk: int = 256,
) -> np.ndarray:
    """Distance along each direction at which protein first blocks the ray.

    A residue in an open groove has long free paths in most directions; one at
    the bottom of a pocket is blocked early almost everywhere. Solved
    analytically -- project each neighbouring atom onto each direction and take
    the nearest one whose perpendicular offset is inside the ray radius --
    rather than by sampling points along the ray, which costs a nearest-neighbour
    query per sample and quantises the answer to the step size.
    """
    free = np.full((n, RAY_DIRECTIONS), RAY_MAX)
    # An atom whose centre sits just past RAY_MAX can still clip a ray inside it
    # (t = sqrt(d^2 - perp^2) < d), so the blocker set has to reach past the
    # longest path we report or the far end of the cast silently reads as open.
    m = dist <= RAY_MAX + RAY_BLOCK_DIST
    if not m.any():
        return free
    seg, off = pi[m], offset[m]
    counts = np.bincount(seg, minlength=n)[:n]
    starts = np.concatenate([[0], np.cumsum(counts)])
    r2 = np.einsum("ij,ij->i", off, off)
    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        a, b = starts[lo], starts[hi]
        if a == b:
            continue
        t = off[a:b] @ RAY_DIRS.T
        perp2 = r2[a:b][:, None] - t**2
        blocked = (perp2 < RAY_BLOCK_DIST**2) & (t >= RAY_T_MIN)
        tv = np.where(blocked, t, RAY_MAX)
        local = starts[lo:hi] - a
        reduced = np.minimum.reduceat(tv, np.minimum(local, len(tv) - 1), axis=0)
        empty = counts[lo:hi] == 0
        reduced[empty] = RAY_MAX
        free[lo:hi] = np.clip(reduced, RAY_T_MIN, RAY_MAX)
    return free


def _hull_depths(
    model: AtomModel, pos: np.ndarray, probe: np.ndarray, rows: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Distance from the probe point, and from the deepest atom, to the hull."""
    n = len(rows)
    try:
        eq = ConvexHull(pos).equations
    except Exception:
        return np.zeros(n), np.zeros(n)
    def _depth(points: np.ndarray, block: int = 2048) -> np.ndarray:
        # Chunked: a 16k-atom antigen has thousands of hull facets, and the full
        # outer product is hundreds of megabytes per worker.
        out = np.empty(len(points))
        for lo in range(0, len(points), block):
            hi = min(lo + block, len(points))
            out[lo:hi] = (points[lo:hi] @ eq[:, :3].T + eq[:, 3]).max(axis=1)
        return np.clip(-out, 0.0, 15.0) / 15.0

    depth = _depth(probe)
    atom_all = _depth(pos)
    atom_depth = np.asarray(
        [float(atom_all[model.atoms_of[r]].max()) for r in rows]
    )
    return depth, atom_depth


def _chain_geometry(
    model: AtomModel, pos: np.ndarray, rows: np.ndarray, tree: cKDTree
) -> np.ndarray:
    """CA-trace geometry and backbone hydrogen bonding, all identity-free.

    Shares the caller's KD-tree. Building one per residue here is what made the
    first version of this module spend most of its runtime on tree construction.
    """
    n = len(rows)
    ca = np.asarray(model.ca, dtype=int)
    chain = model.chain_arr
    slot = model.slot_arr
    seq = model.seq_arr

    # Sequence neighbours by (chain, slot), rejected across a numbering gap.
    order: dict[tuple[int, int], int] = {
        (int(chain[r]), int(slot[r])): r for r in range(model.n_res)
    }

    def _offset_residue(ridx: int, step: int) -> int:
        other = order.get((int(chain[ridx]), int(slot[ridx]) + step), -1)
        if other < 0 or ca[other] < 0:
            return -1
        if abs(int(seq[other]) - int(seq[ridx])) > abs(step) + 1:
            return -1
        return other

    here = np.full(n, -1, dtype=int)
    prev = np.full(n, -1, dtype=int)
    nxt = np.full(n, -1, dtype=int)
    nxt2 = np.full(n, -1, dtype=int)
    for i, ridx in enumerate(rows):
        here[i] = ca[ridx]
        prev[i] = _offset_residue(ridx, -1)
        nxt[i] = _offset_residue(ridx, 1)
        nxt2[i] = _offset_residue(ridx, 2)

    def _ca_pos(idx: np.ndarray) -> np.ndarray:
        out = np.zeros((n, 3))
        ok = idx >= 0
        out[ok] = pos[ca[idx[ok]]]
        return out

    p_here = np.zeros((n, 3))
    p_here[here >= 0] = pos[here[here >= 0]]
    p_prev, p_next, p_next2 = _ca_pos(prev), _ca_pos(nxt), _ca_pos(nxt2)
    tri = (here >= 0) & (prev >= 0) & (nxt >= 0)
    quad = tri & (nxt2 >= 0)

    span = np.where(
        tri, np.minimum(np.linalg.norm(p_next - p_prev, axis=1) / 7.0, 1.5), 0.0
    )
    angle = np.where(
        tri,
        np.einsum(
            "ij,ij->i", _unit_rows(p_prev - p_here), _unit_rows(p_next - p_here)
        ),
        0.0,
    )
    b0, b1, b2 = p_here - p_prev, p_next - p_here, p_next2 - p_next
    n1, n2 = np.cross(b0, b1), np.cross(b1, b2)
    m1 = np.cross(n1, _unit_rows(b1))
    x = np.einsum("ij,ij->i", n1, n2)
    y = np.einsum("ij,ij->i", m1, n2)
    norm = np.hypot(x, y)
    good = quad & (norm > 1e-9)
    dih_cos = np.where(good, x / np.where(norm > 1e-9, norm, 1.0), 0.0)
    dih_sin = np.where(good, y / np.where(norm > 1e-9, norm, 1.0), 0.0)

    # CA neighbour count and contact order, from one batched query.
    ca_valid = np.flatnonzero(ca >= 0)
    ca_tree = cKDTree(pos[ca[ca_valid]]) if ca_valid.size else None
    ca_near = np.zeros(n)
    contact_order = np.zeros(n)
    if ca_tree is not None:
        hits = ca_tree.query_ball_point(p_here, CA_NEIGHBOUR_RADIUS)
        lens = np.fromiter((len(h) for h in hits), dtype=int, count=n)
        hp = np.repeat(np.arange(n), lens)
        hj = (
            np.concatenate([np.asarray(h, dtype=int) for h in hits])
            if lens.sum()
            else np.zeros(0, dtype=int)
        )
        other = ca_valid[hj] if hj.size else hj
        keep = (other != rows[hp]) & (here[hp] >= 0) if hj.size else np.zeros(0, bool)
        hp, other = hp[keep], other[keep]
        ca_near = _seg_sum(hp, None, n)
        same = chain[other] == chain[rows[hp]]
        gap = np.abs(slot[other] - slot[rows[hp]]).astype(float)
        c_same = _seg_sum(hp[same], None, n)
        s_same = _seg_sum(hp[same], gap[same], n)
        contact_order = np.where(
            c_same > 0, np.log1p(s_same / np.maximum(c_same, 1.0)) / 5.0, 0.0
        )

    # Backbone-backbone hydrogen bonds at non-local sequence separation: the
    # identity-free signature of a strand pairing or a helix turn.
    hbonds = np.zeros(n)
    donor_rows: list[int] = []
    donor_atoms: list[int] = []
    for i, ridx in enumerate(rows):
        atoms = model.atoms_of[ridx]
        sel = atoms[model.is_bb[atoms] & np.isin(model.elem[atoms], ("N", "O"))]
        donor_rows.extend([i] * len(sel))
        donor_atoms.extend(sel.tolist())
    if donor_atoms:
        da = np.asarray(donor_atoms, dtype=int)
        dr = np.asarray(donor_rows, dtype=int)
        hits = tree.query_ball_point(pos[da], HBOND_DIST)
        lens = np.fromiter((len(h) for h in hits), dtype=int, count=len(da))
        src = np.repeat(np.arange(len(da)), lens)
        partner = (
            np.concatenate([np.asarray(h, dtype=int) for h in hits])
            if lens.sum()
            else np.zeros(0, dtype=int)
        )
        if partner.size:
            own = model.owner[partner]
            row = dr[src]
            ok = (
                (own != rows[row])
                & model.is_bb[partner]
                & np.isin(model.elem[partner], ("N", "O"))
                & (model.elem[partner] != model.elem[da[src]])
            )
            local = (chain[own] == chain[rows[row]]) & (
                np.abs(slot[own] - slot[rows[row]]) < HBOND_SEQ_SEPARATION
            )
            ok &= ~local
            hbonds = _seg_sum(row[ok], None, n)
    return np.stack(
        [
            span,
            angle,
            dih_cos,
            dih_sin,
            np.log1p(ca_near) / 5.0,
            np.minimum(hbonds, 6.0) / 6.0,
            contact_order,
        ],
        axis=1,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _read_cache(path: Path) -> dict:
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def build_one(task: tuple[str, str, bool]) -> dict:
    cache_path, out_dir_str, resume = task
    path = Path(cache_path)
    out_dir = Path(out_dir_str)
    start = time.monotonic()
    # Read inside the guard: a truncated or empty cache file used to propagate
    # out of the worker and abort the whole pool through ``future.result()``,
    # which cost a 30-minute run over one bad file out of 561.
    try:
        cache = _read_cache(path)
        context_id = cache["context_id"]
        keys = cache["keys"]
    except Exception as exc:  # noqa: BLE001
        return {
            "context": path.name.split(".")[0],
            "ok": False,
            "error": f"unreadable cache: {exc!r}",
            "seconds": round(time.monotonic() - start, 2),
        }
    target_path = out_dir / f"{context_id}.npz"
    if resume and target_path.exists():
        try:
            held = np.load(target_path, allow_pickle=False)
            same = (
                str(held["version"][0]) == FEATURE_VERSION
                and list(held["keys"]) == keys
                and held["feat"].shape == (len(keys), N_FEATURES)
                and np.isfinite(held["feat"]).all()
            )
            if same:
                feat = held["feat"]
                return _summary(context_id, keys, feat, start, reused=True)
        except Exception:
            pass  # unreadable or older layout: recompute
    try:
        target, _ = load_antigen(CIF_DIR, cache["pdb"], cache["chains"])
        feat = compute_features(target.st, keys)
        if feat.shape != (len(keys), N_FEATURES):
            raise ValueError(f"shape {feat.shape} != {(len(keys), N_FEATURES)}")
        if not np.isfinite(feat).all():
            raise ValueError("non-finite feature")
        out_dir.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: np.savez_compressed streams into the file, so a
        # worker killed mid-write leaves a truncated archive that np.load
        # reports as "pickled data". rename(2) is atomic within a filesystem.
        # The name must still end in .npz: savez_compressed silently appends the
        # extension otherwise, and the rename would then chase a file numpy
        # never wrote.
        tmp = target_path.with_name(f"{target_path.stem}.tmp{os.getpid()}.npz")
        np.savez_compressed(
            tmp,
            keys=np.asarray(keys),
            feat=feat,
            version=np.asarray([FEATURE_VERSION]),
        )
        os.replace(tmp, target_path)
        return _summary(context_id, keys, feat, start, reused=False)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        return {
            "context": context_id,
            "ok": False,
            "error": repr(exc),
            "seconds": round(time.monotonic() - start, 2),
        }


def _summary(
    context_id: str, keys: list[str], feat: np.ndarray, start: float, reused: bool
) -> dict:
    return {
        "context": context_id,
        "ok": True,
        "reused": reused,
        "residues": len(keys),
        "seconds": round(time.monotonic() - start, 2),
        "sum": feat.astype(np.float64).sum(axis=0).tolist(),
        "min": feat.min(axis=0).astype(float).tolist(),
        "max": feat.max(axis=0).astype(float).tolist(),
        "zero_var": (feat.var(axis=0) <= 0).tolist(),
    }


def sanity_report(context_ids: list[str], cache_dir: Path, out_dir: Path) -> dict:
    """Standardised mean difference between epitope and non-epitope residues.

    Labels are read here and nowhere else. Features are z-scored *within* each
    context before pooling, because a model ranking candidate patches ranks them
    within one target: a between-protein scale difference is not signal it can
    use, and pooling raw values would let one large antigen set the scale.

    Reported twice. ``all_residues`` keeps every residue, which lets any
    exposure proxy look strong simply because epitopes are solvent-exposed and
    most residues are not. ``exposed_only`` restricts the negatives to residues
    already past the surface threshold, which is the discrimination the ranker
    actually has to make.
    """
    out: dict = {}
    for tag, min_rsa in (("all_residues", None), ("exposed_only_rsa20", 0.20)):
        ep = np.zeros(N_FEATURES)
        ep_sq = np.zeros(N_FEATURES)
        non = np.zeros(N_FEATURES)
        non_sq = np.zeros(N_FEATURES)
        n_ep = n_non = 0.0
        auc_num = np.zeros(N_FEATURES)
        auc_den = 0.0
        used = 0
        for context_id in context_ids:
            cache = _read_cache(cache_dir / f"{context_id}.json.gz")
            epitope: set[str] = set()
            for inst in cache["instances"]:
                if inst.get("split") == "test":
                    epitope.update(inst.get("epitope") or [])
            if not epitope:
                continue
            npz_path = out_dir / f"{context_id}.npz"
            if not npz_path.exists():
                continue
            feat = np.load(npz_path)["feat"].astype(np.float64)
            label = np.asarray([d in epitope for d in cache["display_keys"]])
            if min_rsa is not None:
                col = cache["feature_names"].index("relative_sasa")
                rsa = np.asarray([r[col] for r in cache["features"]])
                keep = (rsa >= min_rsa) | label
                feat, label = feat[keep], label[keep]
            if label.sum() < 3 or (~label).sum() < 3:
                continue
            sd = feat.std(axis=0)
            sd[sd < 1e-9] = 1.0
            z = (feat - feat.mean(axis=0)) / sd
            ep += z[label].sum(axis=0)
            ep_sq += (z[label] ** 2).sum(axis=0)
            non += z[~label].sum(axis=0)
            non_sq += (z[~label] ** 2).sum(axis=0)
            n1, n0 = float(label.sum()), float((~label).sum())
            n_ep += n1
            n_non += n0
            ranks = np.argsort(np.argsort(feat, axis=0), axis=0) + 1.0
            auc_num += ((ranks[label].sum(axis=0) - n1 * (n1 + 1) / 2.0) / (n1 * n0)) * (
                n1 * n0
            )
            auc_den += n1 * n0
            used += 1
        if used == 0 or min(n_ep, n_non) < 2:
            out[tag] = {"contexts_used": used, "note": "no labelled test contexts"}
            continue
        m_ep, m_non = ep / n_ep, non / n_non
        v_ep = np.maximum(ep_sq / n_ep - m_ep**2, 0.0)
        v_non = np.maximum(non_sq / n_non - m_non**2, 0.0)
        pooled = np.sqrt(
            ((n_ep - 1) * v_ep + (n_non - 1) * v_non) / max(n_ep + n_non - 2, 1)
        )
        pooled[pooled < 1e-9] = 1.0
        d = (m_ep - m_non) / pooled
        auc = auc_num / auc_den
        out[tag] = {
            "contexts_used": used,
            "epitope_residues": int(n_ep),
            "other_residues": int(n_non),
            "note": "within-context z-scored; Cohen's d and rank AUC, epitope vs other",
            "top10": [
                {
                    "feature": FEATURE_NAMES[i],
                    "cohens_d": round(float(d[i]), 4),
                    "auc": round(float(auc[i]), 4),
                }
                for i in np.argsort(-np.abs(d))[:10]
            ],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--contexts", nargs="*")
    ap.add_argument("--receipt", default=str(RECEIPT_PATH))
    ap.add_argument(
        "--no-resume",
        action="store_true",
        help="recompute contexts that already have an up-to-date .npz",
    )
    ap.add_argument("--no-sanity", action="store_true")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.out_dir)
    if not cache_dir.is_dir():
        raise SystemExit(f"no such cache dir: {cache_dir}")
    paths = sorted(cache_dir.glob("*.json.gz"))
    if args.contexts:
        wanted = set(args.contexts)
        paths = [p for p in paths if p.name.split(".")[0] in wanted]
    if args.limit:
        paths = paths[: args.limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    NAMES_PATH.write_text(json.dumps(FEATURE_NAMES, indent=1))
    resume = not args.no_resume
    tasks = [(str(p), str(out_dir), resume) for p in paths]

    start = time.monotonic()
    results: list[dict] = []
    if args.workers <= 1:
        for task in tasks:
            results.append(build_one(task))
            row = results[-1]
            print(row["context"], row["ok"], row["seconds"], flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(build_one, t) for t in tasks]
            for done, fut in enumerate(as_completed(futures), start=1):
                row = fut.result()
                results.append(row)
                if not row["ok"] or done % 50 == 0:
                    print(
                        f"[{done}/{len(tasks)}] {row['context']} ok={row['ok']} "
                        f"{row.get('error','')}",
                        flush=True,
                    )
    runtime = time.monotonic() - start

    ok = [r for r in results if r["ok"]]
    reused = sum(1 for r in ok if r.get("reused"))
    total = np.zeros(N_FEATURES)
    lo = np.full(N_FEATURES, np.inf)
    hi = np.full(N_FEATURES, -np.inf)
    n_rows = 0
    always_constant = np.ones(N_FEATURES, dtype=bool)
    for r in ok:
        total += np.asarray(r["sum"])
        lo = np.minimum(lo, np.asarray(r["min"]))
        hi = np.maximum(hi, np.asarray(r["max"]))
        n_rows += r["residues"]
        always_constant &= np.asarray(r["zero_var"], dtype=bool)
    mean = total / max(n_rows, 1)

    receipt = {
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "feature_version": FEATURE_VERSION,
        "python": sys.executable,
        "gemmi": gemmi.__version__,
        "cache_dir": str(cache_dir),
        "out_dir": str(out_dir),
        "contexts_attempted": len(paths),
        "contexts_completed": len(ok),
        "contexts_reused": reused,
        "residues": n_rows,
        "runtime_seconds": round(runtime, 1),
        "workers": args.workers,
        "feature_count": N_FEATURES,
        "feature_names": FEATURE_NAMES,
        "errors": [
            {"context": r["context"], "error": r["error"]}
            for r in results
            if not r["ok"]
        ],
        "constant_in_every_context": [
            FEATURE_NAMES[i] for i in np.flatnonzero(always_constant)
        ],
        "pooled_stats": [
            {
                "feature": FEATURE_NAMES[i],
                "min": round(float(lo[i]), 6) if np.isfinite(lo[i]) else None,
                "mean": round(float(mean[i]), 6),
                "max": round(float(hi[i]), 6) if np.isfinite(hi[i]) else None,
            }
            for i in range(N_FEATURES)
        ],
    }
    if not args.no_sanity:
        receipt["epitope_sanity_check"] = sanity_report(
            [r["context"] for r in ok], cache_dir, out_dir
        )
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))
    print(
        f"done {len(ok)}/{len(paths)} contexts ({reused} reused), {n_rows} residues, "
        f"{N_FEATURES} features, {runtime:.1f}s -> {args.receipt}"
    )


if __name__ == "__main__":
    main()
