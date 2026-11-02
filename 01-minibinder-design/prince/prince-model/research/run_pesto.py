"""Run the pretrained PeSTo model as an external comparator over the benchmark antigens.

PeSTo (https://github.com/LBM-EPFL/PeSTo) is CC BY-NC-SA 4.0. It is used here ONLY
as a third-party comparator, executed out-of-tree from its own clone. No PeSTo code
is copied or vendored by this script: it imports the upstream modules by path and
calls them. The only thing this script produces is per-residue numbers.

What it does, per context in ``cache_full_antigen/``:

1. Loads the antigen exactly as our pipeline does (``benchmark.structures.load_antigen``),
   so the antibody chains are already gone. PeSTo never sees an antibody chain --
   that would leak the epitope it is being asked to find.
2. Writes that antigen to a scratch PDB with SYNTHETIC single-character chain ids and
   SYNTHETIC sequential residue numbers, remembering the map back to
   ``(auth_asym_id, auth_seq_id, icode)``. This is the whole alignment story: PeSTo's
   ``clean_structure`` renumbers residues 1..N and *discards insertion codes*, so author
   numbering cannot be recovered from its output. Round-tripping through a synthetic
   numbering we chose makes the mapping exact instead of inferred. 293 of our keys carry
   an insertion code, so this is not hypothetical.
3. Carries a per-atom provenance index (``okey``) through PeSTo's own preprocessing.
   Every function in that chain (``clean_structure``, ``atom_select``, ``split_by_chain``,
   ``concatenate_chains``) is key-generic -- it masks or concatenates *all* fields of the
   structure dict -- so an extra field rides along untouched and lands next to the atoms
   it describes. The residue grouping matrix ``M`` then tells us which output row each
   ``okey`` owns, and we assert the atoms of a row agree. No positional arithmetic, so no
   off-by-one is possible: a residue PeSTo dropped comes back as ``null``, not as a shift.

Channel choice: ``config_model["dm"]["N2"] == 5`` and ``config_data["r_types"]`` is
``[protein, dna+rna, ion, ligand, lipid]``, so ``z[:, 0]`` is the protein-protein
interface channel. ``interface_type_evaluation.ipynb`` confirms it: it builds
``pc = cat([1 - max(p), p])`` and reads class ``i`` at ``pc[:, i+1]`` with
``class_names = ["protein", "DNA/RNA", "ion", "ligand", "lipid"]``, i.e. class 0
("protein") is ``sigmoid(z[:, 0])``. ``z`` is logits; the notebook applies ``sigmoid``.
There is no trained "any interface" channel in this model, so we also record the
notebook's own stand-in for one, ``max_c sigmoid(z[:, c])``, as ``pesto_any``.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import gzip
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = DATA / 'upstream-pesto'
SAVE_PATH = UPSTREAM / "model" / "save" / "i_v4_1_2021-09-07_11-21"
PRINCE_ROOT = REPO
CIF_DIR = PRINCE_ROOT / ".cache" / "benchmark" / "cif"
CACHE_DIR = DATA / 'cache_full_antigen'
OUT_DIR = DATA / 'pesto_cache'
RECEIPT = DATA / 'pesto_receipt.json'
SCRATCH = DATA / "scratch/pesto"

#: Whether PeSTo's training data plausibly overlaps this benchmark. Recorded in the
#: receipt because if it does, PeSTo's score here is optimistic and the comparison has
#: to be reported with that caveat attached. Every claim below is sourced; where the
#: authors are silent, this says so rather than inferring.
PESTO_TRAINING_OVERLAP = {
    "overlap_can_be_ruled_out": False,
    "verdict": (
        "Overlap CANNOT be ruled out, and it is demonstrably present on the side we "
        "score. PeSTo's scores on this benchmark must be reported as optimistic."
    ),
    "training_data": (
        "First bioassembly of all PDB biological assemblies (paper Methods/'Datasets': "
        "'The dataset is composed of all the biological assemblies from the Protein Data "
        "Bank'; Methods/'Training': 'We trained only on the first bioassembly provided by "
        "the PDB database'; consistent with config.py 'max_ba': 1). Fetched by live rsync "
        "with no date pin (upstream-pesto/data/rsyncPDB.sh)."
    ),
    "stated_date_cutoff": None,
    "stated_date_cutoff_note": (
        "No cutoff is stated anywhere: checked README.md, pesto.yml, data/rsyncPDB.sh, "
        "data/datasets/README.md, processing/split_dataset.ipynb, processing/"
        "build_dataset.py, the i_v4_1 config and slurm logs, and the paper's Methods and "
        "Data availability sections."
    ),
    "derived_date_bound": "2021-03-03",
    "derived_date_bound_note": (
        "DERIVED BY US, not an authors' claim: RCSB initial_release_date resolved for all "
        "30,629 resolvable entries in the shipped split lists whose id begins 6-9 gives a "
        "maximum release date of 2021-03-03, with releases falling to zero after it "
        "(2021-01: 418, 2021-02: 405, 2021-03: 96, then none). The checkpoint is dated "
        "2021-09-07, which bounds it from above independently."
    ),
    "redundancy_filtering": (
        "30% sequence identity, cluster level (paper Methods/'Datasets': 'The subunits are "
        "clustered using a maximum of 30% sequence identity between clusters'), using "
        "RCSB bc-30.out (named only in processing/split_dataset.ipynb, not the paper)."
    ),
    "antibody_handling": (
        "Neither excluded nor specially handled; not stated in the paper or the code. A "
        "grep for antibod|immunoglob|epitope|paratope|nanobod across all source in the "
        "clone returns zero matches. Immunoglobulin chains land mostly in the held-out "
        "split as an incidental side effect of 30% clustering (8.9% of a 448-subunit "
        "validation sample vs ~0.2% genuine in a 472-subunit train sample), but that is a "
        "side effect, not a design choice, and it is incomplete -- genuine antibody chains "
        "remain in train (e.g. 6S3T_D, 6MHR_C, 6OYH_C, 5CJX_G)."
    ),
    "why_antigens_are_not_protected": (
        "We score the ANTIGEN, and antigens are not protected by the antibody-side "
        "clustering effect. Training labels for a subunit are OR'd over every contacting "
        "partner in its bioassembly regardless of which split that partner went to "
        "(src/dataset.py select_by_sid masks only the target subunit; model/data_handler.py "
        "Dataset.__getitem__ ORs over all ckeys). The guard that would have prevented this, "
        "select_complete_assemblies, exists in src/dataset.py but is never called -- "
        "model/save/i_v4_1_2021-09-07_11-21/main.py imports only select_by_sid, "
        "select_by_max_ba and select_by_interface_types. So where an antigen chain is in "
        "train and its first bioassembly contains the Fab, that antigen's epitope was a "
        "positive protein-protein training label."
    ),
    "measured_overlap_this_benchmark": {
        "method": (
            "Exact per-subunit id join of each context's PDB id + declared antigen auth "
            "chain ids against subunits_train_set.txt (376,216 entries, read via "
            "'git cat-file -p HEAD:data/datasets/subunits_train_set.txt' because the "
            "working-tree copy is a sparse 0-block file that reads as empty)."
        ),
        "contexts_with_antigen_chain_in_pesto_train": 98,
        "contexts_total": 561,
        "fraction": 0.1747,
        "entry_level_upper_bound": 118,
        "test_split_contexts_leaked": 14,
        "test_split_contexts_clean": 91,
        "caveats": (
            "A train-list hit is an UPPER bound on exact-chain exposure: PeSTo's HDF5 "
            "filters (max_ba=1, <=8192 atoms, >=48 residues, must have a contact of a "
            "selected type) cut 376,216 subunits to 113,805 actually trained on. A MISS is "
            "not safety: 30% clustering means a homolog of an antigen may be in train even "
            "when that exact chain is not, and bounding that needs a sequence search, not "
            "an id join."
        ),
    },
    "homolog_level_bound": {
        "method": (
            "Antigen chains joined to RCSB 30%-identity clusters (bc-30.out, shipped in "
            "upstream-pesto/data/datasets/), then asked whether any cluster-mate appears "
            "in subunits_train_set.txt. This is the homolog-level analogue of the exact "
            "join, at the identity threshold PeSTo itself clustered on."
        ),
        "contexts_with_cluster_coverage": 393,
        "contexts_total": 561,
        "coverage_caveat": (
            "168 of 561 antigen chains are absent from the shipped bc-30.out, so no bound "
            "is computable for them. That file is a LATER RCSB download than the one used "
            "to build the splits (533,352 sids, vs 575,340 across the three split files, "
            "with 19,305 train sids missing from it), so it is an imperfect instrument."
        ),
        "covered_contexts_with_30pct_homolog_in_train": 125,
        "covered_contexts_with_30pct_homolog_in_train_fraction": 0.318,
        "test_covered": 90,
        "test_covered_with_30pct_homolog_in_train": 30,
        "covered_contexts_with_30pct_homolog_in_any_split": 392,
        "interpretation": (
            "Homolog-level exposure to the TRAIN split is 31.8% of covered contexts "
            "(33.3% of covered test contexts), roughly double the 17.5% exact-chain "
            "figure. But 99.7% of covered contexts have a 30%-identity cluster-mate "
            "somewhere in PeSTo's PDB snapshot, which is unavoidable for a model trained "
            "on all of PDB and means 'did it see a homolog' is not a discriminating "
            "question. The discriminating question is epitope-LABEL exposure, which is "
            "what the exact-chain join (17.5%) and the train-cluster join (31.8%) measure."
        ),
    },
    "measured_effect_on_scores": {
        "note": (
            "Stratification of the test-split signal by leak status. Not the real "
            "evaluation, but it shows the leak is not hypothetical. The pooled-residue "
            "figures came first; the macro figures below use the project's own "
            "aggregation (within-instance AUROC, mean within cluster, mean across "
            "clusters) on the 110 evaluated test interfaces, so they are the ones "
            "comparable to the published comparator numbers."
        ),
        "macro_auroc_leaked": 0.7487,
        "macro_auroc_clean": 0.6235,
        "macro_leaked_clusters": 7,
        "macro_clean_clusters": 28,
        "macro_leaked_interfaces": 15,
        "macro_clean_interfaces": 95,
        "macro_auroc_all_110": 0.6521,
        "headline": (
            "On the project's own macro aggregation, PeSTo scores 0.6521 over all 110 test "
            "interfaces but only 0.6235 on the 95 whose antigen chain is NOT in its "
            "training list, versus 0.7487 on the 15 that are. The clean figure is the "
            "honest comparator baseline; the all-interfaces figure is inflated by the "
            "leaked minority."
        ),
        "leaked_auroc": 0.8697,
        "leaked_epitope_mean": 0.6489,
        "leaked_nonepitope_mean": 0.1224,
        "clean_auroc": 0.6294,
        "clean_epitope_mean": 0.1431,
        "clean_nonepitope_mean": 0.1329,
        "interpretation": (
            "On the 14 test contexts whose antigen chain is in PeSTo's training list, "
            "AUROC is 0.870 and the epitope mean is 5x the non-epitope mean. On the 91 "
            "clean contexts, AUROC is 0.629 and the epitope/non-epitope separation is "
            "+0.010, i.e. almost nothing. The pooled number is inflated by the leaked "
            "13%; the clean-only figure is the honest comparator baseline."
        ),
    },
    "sources": [
        "Krapp, Abriata, Cortes Rodriguez & Dal Peraro, Nat Commun 14:2175 (2023), "
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10113261/",
        "upstream-pesto @ ba651aa29aaa839d0ee2c458dee90ca1f934d90a",
        "RCSB Data API (release dates, chain descriptions)",
    ],
}

#: Evidence that the key mapping is correct, rather than an assertion that it is.
#: Produced by two scripts kept out of tree (a falsification test and a whole-benchmark
#: divergence scan); the numbers are recorded here because "the assertions are present"
#: is not the same claim as "the assertions fire and the naive alternative was wrong".
ALIGNMENT_PROOF = {
    "naive_positional_would_be_wrong": True,
    "contexts_where_pesto_residue_count_differs_from_our_key_count": 262,
    "contexts_where_at_least_one_key_maps_to_a_row_not_equal_to_its_index": 60,
    "keys_whose_pesto_row_index_differs_from_their_key_index": 18179,
    "keys_total": 176842,
    "fraction_of_keys_naive_indexing_would_misassign": 0.1028,
    "note": (
        "Had the scores been read off positionally, 18,179 of 176,842 keys (10.3%) across "
        "60 of 561 contexts would have been given a different residue's score, silently. "
        "PeSTo parses the whole antigen including assembly copies of chains that are not "
        "declared antigen chains, and hetero groups, so its residue list is neither the "
        "same length nor the same order as our key list in 262 contexts."
    ),
    "falsification_tests": {
        "duplicate_owner_corruption_is_rejected": (
            "Mapping two distinct residue identities to one key index raises "
            "AssertionError('two residue rows claim the same key') -- the injectivity "
            "guard fires rather than silently keeping one."
        ),
        "unscorable_key_yields_null_in_place": (
            "A fabricated residue identity inserted at position 100 of the key list comes "
            "back as null at exactly position 100, with all 100 keys before it and all 207 "
            "keys after it bit-identical to the baseline run. The array is not shifted, "
            "which is the specific failure mode that would invalidate the comparison."
        ),
        "per_row_unanimity": (
            "Every residue row's atoms must agree on their provenance id or the run aborts; "
            "this held for all 561 contexts."
        ),
    },
}

PESTO_MODEL = "i_v4_1_2021-09-07_11-21"
PESTO_LICENCE = "CC BY-NC-SA 4.0 (Attribution-NonCommercial-ShareAlike 4.0 International)"
PPI_CHANNEL = 0
PPI_CHANNEL_NAME = "protein"

# PDB chain ids are one character. Six chains is the observed maximum across the 561
# contexts, so this pool is never close to exhausted; exhausting it raises rather than
# silently colliding two chains into one.
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _bootstrap():
    """Put our code and PeSTo's on the path and return the pieces we call.

    ``src`` is bound explicitly to ``upstream-pesto/src`` rather than left to sys.path
    order. Two other things on this interpreter's path answer to that name -- an unrelated
    ``olas-defi-agent/src`` package that wins outright, and the training-time snapshot at
    ``model/save/.../src`` -- so resolving it by search order would silently import the
    wrong module. Pinning it also reproduces what ``apply_model.ipynb`` effectively does:
    its ``src`` imports run in cell 1, before the ``sys.path.insert(0, save_path)`` in
    cell 4, so the notebook uses the live ``src``, not the snapshot.
    """
    import types

    for p in (str(PRINCE_ROOT / "src"), str(PRINCE_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from benchmark.structures import load_antigen  # noqa: E402  (our own code)

    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    pkg = types.ModuleType("src")
    pkg.__path__ = [str(UPSTREAM / "src")]
    sys.modules["src"] = pkg
    import src.data_encoding as de  # noqa: E402
    import src.dataset as ds  # noqa: E402
    import src.structure as stc  # noqa: E402
    import src.structure_io as sio  # noqa: E402

    # `config` and `model` are loaded by explicit file path, not by sys.path search, for
    # the same reason as `src` above: they are generic names, sys.path[0] is whatever
    # directory this script sits in, and a `config.py`/`model.py` belonging to someone
    # else would be imported instead -- silently giving a different architecture or a
    # different channel count. (A neighbouring scratch directory did contain exactly
    # such a file, which is how this was found.) Loading by path cannot be shadowed.
    config_model = _load_by_path("pesto_config", SAVE_PATH / "config.py").config_model
    Model = _load_by_path("pesto_model", SAVE_PATH / "model.py").Model
    return load_antigen, de, ds, stc, sio, config_model, Model


def _load_by_path(name, path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_model(config_model, Model, torch):
    model = Model(config_model)
    state = torch.load(str(SAVE_PATH / "model_ckpt.pt"), map_location=torch.device("cpu"))
    model.load_state_dict(state)
    return model.eval()


def write_antigen_pdb(gemmi, st, out_path):
    """Write model 0 of ``st`` with synthetic chain ids / residue numbers.

    Returns ``{(chain_letter, resseq): (auth_asym_id, auth_seq_id, icode)}``.
    """
    if len(st) != 1:
        raise ValueError(f"expected exactly 1 model, got {len(st)}")
    out = gemmi.Structure()
    out.name = "ANTIGEN"
    new_model = gemmi.Model("1")
    mapping = {}
    for ci, chain in enumerate(st[0]):
        if ci >= len(ALPHABET):
            raise ValueError(f"more chains ({len(st[0])}) than single-character ids")
        letter = ALPHABET[ci]
        new_chain = gemmi.Chain(letter)
        for ri, res in enumerate(chain):
            seq = ri + 1
            if seq > 9999:
                raise ValueError(f"chain {chain.name} exceeds the 4-digit PDB resseq field")
            new_res = gemmi.Residue()
            new_res.name = res.name
            new_res.seqid = gemmi.SeqId(seq, " ")
            new_res.het_flag = res.het_flag
            for atom in res:
                new_res.add_atom(atom)
            new_chain.add_residue(new_res)
            mapping[(letter, seq)] = (chain.name, res.seqid.num, res.seqid.icode.strip())
        new_model.add_chain(new_chain)
    out.add_model(new_model)
    out.setup_entities()
    out.write_pdb(str(out_path))
    return mapping


def pesto_scores(mods, torch, np, model, pdb_path, mapping, wanted):
    """Per-residue sigmoid(z) for the residues of ``pdb_path`` that we asked about.

    ``wanted`` maps ``(auth_asym_id, auth_seq_id, icode)`` -> index into our keys.
    Returns ``(probs, n_atoms, n_res)`` where ``probs[i]`` is the ``(5,)`` probability
    vector for our key ``i``, or ``None`` if PeSTo has no residue for it.
    """
    de, stc, sio = mods["de"], mods["stc"], mods["sio"]

    structure = sio.read_pdb(str(pdb_path))
    n_atoms_read = structure["xyz"].shape[0]

    # Per-atom provenance, injected before any PeSTo preprocessing runs. -1 means
    # "an atom of a residue we are not scoring" (hetero groups, assembly copies of a
    # chain that is not one of the declared antigen chains): still real physical
    # context for the model, just not something we report a number for.
    okey = np.full(n_atoms_read, -1, dtype=np.int64)
    for i, (cname, resid) in enumerate(zip(structure["chain_name"], structure["resid"])):
        src_res = mapping.get((cname.split(":")[0], int(resid)))
        if src_res is not None:
            okey[i] = wanted.get(src_res, -1)
    structure["okey"] = okey

    structure = stc.clean_structure(structure)
    structure = stc.tag_hetatm_chains(structure)
    subunits = stc.split_by_chain(structure)
    subunits = stc.filter_non_atomic_subunits(subunits)
    subunits = stc.remove_duplicate_tagged_subunits(subunits)
    if not subunits:
        raise ValueError("PeSTo preprocessing left no subunits")
    structure = stc.concatenate_chains(subunits)
    if "okey" not in structure:
        raise AssertionError("provenance field lost in PeSTo preprocessing")

    X, M = de.encode_structure(structure)
    # i_v4_1 is an element-only model: config_model["em"]["N0"] == 30 == len(std_elements)+1,
    # which is why apply_model.ipynb takes encode_features(...)[0] and not the concatenation.
    q = de.encode_features(structure)[0]
    ids_topk, _, _, _, _ = de.extract_topology(X, 64)

    # One row of M per residue, ordered by sorted renumbered resid, i.e. file order.
    # Resolve each row's owner from the atoms it contains and assert they agree --
    # this is the assertion that makes a silent shift impossible.
    atom_okey = structure["okey"]
    row_owner = np.full(M.shape[1], -1, dtype=np.int64)
    membership = M.numpy()
    for j in range(M.shape[1]):
        vals = np.unique(atom_okey[membership[:, j]])
        if vals.shape[0] != 1:
            raise AssertionError(
                f"residue row {j} spans provenance ids {vals.tolist()} -- "
                "PeSTo merged residues we treat as distinct"
            )
        row_owner[j] = vals[0]
    assigned = row_owner[row_owner >= 0]
    if np.unique(assigned).shape[0] != assigned.shape[0]:
        raise AssertionError("two residue rows claim the same key")

    Xc, ids_topk_c, qc, Mc = mods["ds"].collate_batch_features([[X, ids_topk, q, M]])
    with torch.no_grad():
        z = model(Xc, ids_topk_c, qc, Mc.float())
    if z.shape[0] != M.shape[1]:
        raise AssertionError(f"model returned {z.shape[0]} rows for {M.shape[1]} residues")
    if z.shape[1] != 5:
        raise AssertionError(f"expected 5 interface channels, got {z.shape[1]}")
    p = torch.sigmoid(z).numpy()

    probs = [None] * len(wanted)
    for j, owner in enumerate(row_owner):
        if owner >= 0:
            probs[owner] = p[j]
    return probs, n_atoms_read, int(M.shape[1])


def run_context(mods, torch, np, gemmi, model, cache_path, scratch):
    with gzip.open(check_readable(cache_path), "rt") as stream:
        cache = json.load(stream)
    keys = cache["keys"]

    # Our key strings are "auth_asym:auth_seq[:icode]" -- but build_cache.py's keystr
    # only appends the third field when the icode is truthy, and some keys carry a
    # single-space icode, so split on the LAST two colons rather than assuming a count.
    wanted = {}
    for i, k in enumerate(keys):
        parts = k.split(":")
        chain, seq = parts[0], int(parts[1])
        icode = parts[2].strip() if len(parts) > 2 else ""
        ident = (chain, seq, icode)
        if ident in wanted:
            raise ValueError(f"duplicate residue identity {ident} in {cache['context_id']}")
        wanted[ident] = i

    from benchmark.structures import locate_structure

    cif = locate_structure(CIF_DIR, cache["pdb"])
    if cif is not None:
        check_readable(cif)
    target, _ = mods["load_antigen"](CIF_DIR, cache["pdb"], cache["chains"])
    pdb_path = scratch / f"{cache['context_id']}.pdb"
    try:
        mapping = write_antigen_pdb(gemmi, target.st, pdb_path)
        probs, n_atoms, n_res = pesto_scores(
            mods, torch, np, model, pdb_path, mapping, wanted
        )
    finally:
        pdb_path.unlink(missing_ok=True)

    ppi = [None if v is None else float(v[PPI_CHANNEL]) for v in probs]
    any_iface = [None if v is None else float(max(v)) for v in probs]
    scored = sum(1 for v in ppi if v is not None)

    result = {
        "context_id": cache["context_id"],
        "pdb": cache["pdb"],
        "keys": keys,
        "pesto_ppi": ppi,
        "pesto_any": any_iface,
        "channel_index": PPI_CHANNEL,
        "channel_name": PPI_CHANNEL_NAME,
        "coverage": scored / len(keys) if keys else 0.0,
        "pesto_model": PESTO_MODEL,
        "coordinate_sha256": cache["coordinate_sha256"],
        "n_antigen_chains": len(cache["chains"]),
        "comparator_only": True,
    }
    out_path = OUT_DIR / f"{cache['context_id']}.json.gz"
    tmp_path = out_path.with_suffix(".tmp")
    with gzip.open(tmp_path, "wt") as stream:
        json.dump(result, stream, allow_nan=False)
    tmp_path.replace(out_path)
    return {
        "context": cache["context_id"],
        "pdb": cache["pdb"],
        "keys": len(keys),
        "scored": scored,
        "coverage": result["coverage"],
        "pesto_residues": n_res,
        "atoms": n_atoms,
        "n_antigen_chains": len(cache["chains"]),
    }


class DatalessInput(OSError):
    """An input file has a size but no allocated disk blocks, so it reads as empty.

    This volume ran to 98% full mid-run and the host started reclaiming the *contents*
    of files under it: ``ls`` still reports the size, ``stat -f %b`` reports 0 blocks,
    and a read returns zero bytes. ``gzip.open(...).read()`` returns ``b""`` for such a
    file **without raising**, which is the dangerous part -- a loop with a broad
    ``except`` would record an empty result as if it were data. Checked explicitly and
    raised as its own class so the receipt can separate "needs re-running once the file
    is restored" from "PeSTo genuinely failed on this structure".
    """


def check_readable(path):
    st = os.stat(path)
    if st.st_size > 0 and st.st_blocks == 0:
        raise DatalessInput(
            f"{path} has size {st.st_size} but 0 allocated blocks -- its contents are "
            f"not on disk and it reads as empty. Restore it and re-run this context."
        )
    return path


def already_done(context_id, cache):
    """A usable existing result for this context, or None to (re)compute it.

    Resumability is keyed on ``context_id`` alone -- the output directory is shared
    across cache directories, so pointing ``--cache-dir`` at a larger manifest
    recomputes nothing that is already done. ``context_id`` is a hash of
    ``[pdb_id, antigen_chains]``, so the same id always denotes the same antigen and
    therefore the same key list.

    The saved ``keys`` are still compared against the cache's, because that invariant is
    exactly what makes the scores meaningful: a stale file whose keys no longer match
    would be silently misaligned, which is the failure this whole script is built to
    make impossible. Matching ids give matching keys, so this never forces recomputation
    in practice -- it only catches the case where something is genuinely wrong.
    """
    path = OUT_DIR / f"{context_id}.json.gz"
    if not path.is_file():
        return None
    try:
        with gzip.open(check_readable(path), "rt") as stream:
            saved = json.load(stream)
    except Exception:
        return None
    if saved.get("pesto_model") != PESTO_MODEL or saved.get("channel_index") != PPI_CHANNEL:
        return None
    keys = cache["keys"]
    if saved.get("keys") != keys or len(saved.get("pesto_ppi", [])) != len(keys):
        return None
    scored = sum(1 for v in saved["pesto_ppi"] if v is not None)
    return {
        "context": context_id,
        "pdb": saved.get("pdb"),
        "keys": len(keys),
        "scored": scored,
        "coverage": scored / len(keys) if keys else 0.0,
        "pesto_residues": saved.get("pesto_residues"),
        "n_antigen_chains": len(cache["chains"]),
        "cached": True,
    }


_WORKER = {}


def _init_worker(threads):
    import numpy as np
    import torch
    import gemmi

    torch.set_num_threads(threads)
    load_antigen, de, ds, stc, sio, config_model, Model = _bootstrap()
    _WORKER.update(
        mods={"load_antigen": load_antigen, "de": de, "ds": ds, "stc": stc, "sio": sio},
        torch=torch,
        np=np,
        gemmi=gemmi,
        model=build_model(config_model, Model, torch),
    )


def _run_one(args):
    context_id, cache_path = args
    started = time.monotonic()
    try:
        out = run_context(
            _WORKER["mods"], _WORKER["torch"], _WORKER["np"], _WORKER["gemmi"],
            _WORKER["model"], Path(cache_path), SCRATCH,
        )
        out["seconds"] = round(time.monotonic() - started, 2)
        return out, None
    except Exception as exc:  # noqa: BLE001 -- one bad context must not kill the run
        return None, {
            "context": context_id,
            "error": repr(exc),
            # Separates "the input file's contents are not on disk" from a real PeSTo
            # failure, so the receipt says which contexts are merely pending a restore.
            "dataless_input": isinstance(exc, DatalessInput),
            "traceback": traceback.format_exc(limit=6),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=2, help="torch CPU threads per worker")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*", help="context ids to run")
    ap.add_argument("--receipt", default=str(RECEIPT))
    ap.add_argument(
        "--cache-dir", default=str(CACHE_DIR),
        help="directory of <context_id>.json.gz context files (absolute, or relative to "
             "this script). Outputs always go to the one shared pesto_cache/, so "
             "pointing this at a larger manifest recomputes nothing already done.",
    )
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = DATA / cache_dir
    if not cache_dir.is_dir():
        raise SystemExit(f"--cache-dir does not exist: {cache_dir}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    caches = sorted(cache_dir.glob("*.json.gz"))
    if args.only:
        wanted = set(args.only)
        caches = [p for p in caches if p.name.split(".")[0] in wanted]
    if args.limit:
        caches = caches[: args.limit]

    tasks, results, preflight_errors = [], [], []
    for path in caches:
        context_id = path.name.split(".")[0]
        # Guarded: a dataless cache file raises here, and an unguarded raise in this
        # enumeration loop would abort the whole run before a single context is scored.
        # It belongs in the receipt as a per-context error like any other.
        try:
            with gzip.open(check_readable(path), "rt") as stream:
                cache = json.load(stream)
        except Exception as exc:  # noqa: BLE001
            preflight_errors.append({
                "context": context_id,
                "error": repr(exc),
                "dataless_input": isinstance(exc, DatalessInput),
                "stage": "reading our own cache file",
            })
            continue
        done = already_done(context_id, cache)
        if done is not None:
            results.append(done)
        else:
            tasks.append((context_id, str(path)))

    print(
        f"{len(caches)} contexts: {len(results)} cached, {len(tasks)} to run, "
        f"{len(preflight_errors)} unreadable", flush=True
    )
    started = time.monotonic()
    errors = list(preflight_errors)

    if tasks:
        if args.workers > 1:
            import multiprocessing as mp

            ctx = mp.get_context("spawn")
            with ctx.Pool(args.workers, initializer=_init_worker, initargs=(args.threads,)) as pool:
                for n, (ok, err) in enumerate(pool.imap_unordered(_run_one, tasks), 1):
                    (results if ok else errors).append(ok or err)
                    print(f"{n}/{len(tasks)} " + json.dumps(ok or err), flush=True)
        else:
            _init_worker(args.threads)
            for n, task in enumerate(tasks, 1):
                ok, err = _run_one(task)
                (results if ok else errors).append(ok or err)
                print(f"{n}/{len(tasks)} " + json.dumps(ok or err), flush=True)

    total_keys = sum(r["keys"] for r in results)
    total_scored = sum(r["scored"] for r in results)
    import subprocess

    commit = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    # Coverage split by antigen chain count. Multi-chain targets are the known weak spot
    # -- a bug where only the first antigen chain was processed was recently fixed here --
    # so a pooled coverage number could hide a systematic hole on exactly those targets.
    def bucket(rows):
        keys = sum(r["keys"] for r in rows)
        scored = sum(r["scored"] for r in rows)
        return {
            "contexts": len(rows),
            "keys": keys,
            "keys_scored": scored,
            "key_coverage": scored / keys if keys else None,
            "contexts_below_full_coverage": sum(1 for r in rows if r["scored"] < r["keys"]),
        }

    single = [r for r in results if r.get("n_antigen_chains") == 1]
    multi = [r for r in results if (r.get("n_antigen_chains") or 0) > 1]
    by_chain_count = {
        str(n): bucket([r for r in results if r.get("n_antigen_chains") == n])
        for n in sorted({r.get("n_antigen_chains") for r in results if r.get("n_antigen_chains")})
    }

    dataless = [e for e in errors if e.get("dataless_input")]
    receipt = {
        "cache_dir": str(cache_dir),
        "contexts_attempted": len(caches),
        "contexts_completed": len(results),
        "complete": not errors,
        "errors": errors,
        "errors_total": len(errors),
        "errors_dataless_input": len(dataless),
        "errors_other": len(errors) - len(dataless),
        "dataless_input_contexts": sorted(e["context"] for e in dataless),
        "dataless_input_note": (
            "These contexts were NOT scored because an input file (our cache gz and/or the "
            "source cif) had a nonzero size but zero allocated disk blocks, i.e. its "
            "contents were not on disk and it read as empty. The volume hit 98% full "
            "mid-run and the host reclaimed file contents. They are pending a restore of "
            "those files, not a PeSTo failure; re-running this script resumes and fills "
            "only the gaps."
        ) if dataless else None,
        "total_keys": total_keys,
        "total_keys_scored": total_scored,
        "overall_key_coverage": total_scored / total_keys if total_keys else 0.0,
        "contexts_below_full_coverage": sorted(
            ({"context": r["context"], "pdb": r.get("pdb"), "coverage": r["coverage"],
              "missing": r["keys"] - r["scored"]}
             for r in results if r["scored"] < r["keys"]),
            key=lambda r: r["coverage"],
        ),
        "coverage_single_chain_antigen": bucket(single),
        "coverage_multi_chain_antigen": bucket(multi),
        "coverage_by_antigen_chain_count": by_chain_count,
        "channel_index": PPI_CHANNEL,
        "channel_name": PPI_CHANNEL_NAME,
        "channel_justification": (
            "config_model['dm']['N2']==5 output channels map 1:1 onto "
            "config_data['r_types']==[protein, dna+rna, ion, ligand, lipid], so channel 0 "
            "is the protein-protein interface. Confirmed against "
            "interface_type_evaluation.ipynb, which forms pc=cat([1-max(p), p], dim=1) and "
            "reads class i at pc[:, i+1] with class_names=['protein','DNA/RNA','ion',"
            "'ligand','lipid'] -- class 0 'protein' is therefore sigmoid(z[:,0]). z is "
            "logits; sigmoid is applied as in apply_model.ipynb. This model has no trained "
            "'any interface' channel, so pesto_any records the notebook's own stand-in, "
            "max_c sigmoid(z[:,c])."
        ),
        "pesto_model": PESTO_MODEL,
        "pesto_git_commit": commit,
        "pesto_licence": PESTO_LICENCE,
        "pesto_licence_note": (
            "Third-party comparator executed out-of-tree from its own clone. No PeSTo "
            "source is copied, vendored or redistributed by this script or its outputs; "
            "the outputs are per-residue numbers only."
        ),
        "alignment_proof": ALIGNMENT_PROOF,
        "comparator_only": True,
        "comparator_only_note": (
            "THESE OUTPUTS ARE COMPARATOR-ONLY. PeSTo is CC BY-NC-SA 4.0 (NonCommercial "
            "+ ShareAlike), which is not an OSI-approved licence, while our tool must "
            "ship under an OSI licence. These numbers may be reported as a third-party "
            "baseline for comparison ONLY. They must NOT be used as an input feature, "
            "training target, label, initialisation or selection signal for any model of "
            "ours, and nothing PeSTo-derived may be placed in hotspot-preflight/. Doing "
            "any of those would make our model a derivative work of a NonCommercial "
            "ShareAlike work and render the iGEM entry ineligible."
        ),
        "training_overlap": PESTO_TRAINING_OVERLAP,
        "antigen_only": True,
        "device": "cpu",
        "workers": args.workers,
        "torch_threads_per_worker": args.threads,
        "total_seconds": round(time.monotonic() - started, 1),
        "results": sorted(results, key=lambda r: r["context"]),
    }
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "results"}, indent=2)[:4000])
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    main()
