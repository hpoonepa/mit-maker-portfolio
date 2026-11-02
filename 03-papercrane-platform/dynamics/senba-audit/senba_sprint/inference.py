"""Safe paired inference against frozen MarS-FM/SENBA checkpoints.

This is a new evaluator.  It uses the published Senba batch layout, but has
not been established as a bit-for-bit reproduction of any earlier evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import time
from pathlib import Path
from typing import Any

import numpy as np


VALIDATED_MAX_RESIDUES = 256
_RESTYPES = "ACDEFGHIKLMNPQRSTVWY"
# Number of real atom14 slots for the standard OpenFold residue ordering.  A
# zero triple in a real slot is the mdCATH atom14 missing-atom sentinel.
_ATOM14_COUNTS = {
    "A": 5, "C": 6, "D": 8, "E": 9, "F": 11, "G": 4, "H": 10,
    "I": 8, "K": 9, "L": 8, "M": 8, "N": 8, "P": 7, "Q": 9,
    "R": 11, "S": 6, "T": 7, "V": 7, "W": 14, "Y": 12,
}


def sha256_file(path: Path) -> str:
    """Return a checkpoint digest without loading its pickle payload."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_sha256(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a SHA-256 string")
    value = value.lower().removeprefix("sha256:")
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex string")
    return value


def _coordinates(value: Any, field: str, shape: tuple[int, ...]) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric coordinates") from exc
    if array.shape != shape:
        raise ValueError(f"{field} must have shape {shape}; got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{field} contains a non-finite coordinate")
    return array


def _validate_inputs(
    atom14_start: Any, target_ca: Any, sequence: str, samples: int, ode_steps: int,
    seed: int, ids: dict[str, str],
) -> tuple[np.ndarray, np.ndarray, str, dict[str, str]]:
    if not isinstance(sequence, str) or not sequence:
        raise ValueError("sequence must be a non-empty standard-amino-acid string")
    unsupported = sorted(set(sequence) - set(_RESTYPES))
    if unsupported:
        raise ValueError("sequence has unsupported residues: " + "".join(unsupported))
    n_res = len(sequence)
    if n_res > VALIDATED_MAX_RESIDUES:
        raise ValueError(f"sequence length must be at most {VALIDATED_MAX_RESIDUES}")
    atom14 = _coordinates(atom14_start, "atom14_start", (n_res, 14, 3))
    target = _coordinates(target_ca, "target_ca", (n_res, 3))
    # Absent atom14 slots are expected to be zero.  The input contract is a
    # complete mdCATH-converted structure, so reject that sentinel for atoms
    # that the residue actually contains.
    for index, residue in enumerate(sequence):
        missing = np.all(atom14[index, :_ATOM14_COUNTS[residue]] == 0, axis=1)
        if np.any(missing):
            raise ValueError(f"atom14_start residue {index + 1} ({residue}) has a missing real atom")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 2:
        raise ValueError("samples must be an integer of at least 2")
    if not isinstance(ode_steps, int) or isinstance(ode_steps, bool) or ode_steps < 1:
        raise ValueError("ode_steps must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    required_ids = ("protein_id", "replica_id", "start_id", "training_seed", "inference_seed")
    if not isinstance(ids, dict) or set(ids) != set(required_ids):
        raise ValueError("ids must contain exactly protein_id, replica_id, start_id, training_seed, inference_seed")
    if any(not isinstance(ids[name], str) or not ids[name] for name in required_ids):
        raise ValueError("all ids values must be non-empty strings")
    return atom14, target, sequence, dict(ids)


def kabsch_align(reference: Any, mobile: Any) -> np.ndarray:
    """Align one ``[N,3]`` or many ``[K,N,3]`` mobile structures to reference.

    Uses a proper row-vector rotation (determinant +1), never a reflection.
    """
    ref = np.asarray(reference, dtype=np.float64)
    mov = np.asarray(mobile, dtype=np.float64)
    if ref.ndim != 2 or ref.shape[1:] != (3,) or ref.shape[0] == 0:
        raise ValueError("reference must have shape [N, 3] with N at least 1")
    single = mov.ndim == 2
    if single:
        mov = mov[None, ...]
    if mov.ndim != 3 or mov.shape[1:] != ref.shape:
        raise ValueError("mobile must have shape [N, 3] or [K, N, 3] matching reference")
    if not np.all(np.isfinite(ref)) or not np.all(np.isfinite(mov)):
        raise ValueError("Kabsch coordinates must be finite")
    ref_center = ref.mean(axis=0)
    mov_centers = mov.mean(axis=1)
    ref_zero = ref - ref_center
    mov_zero = mov - mov_centers[:, None, :]
    aligned = np.empty_like(mov)
    for index, current in enumerate(mov_zero):
        left, _, right_t = np.linalg.svd(current.T @ ref_zero)
        correction = np.eye(3)
        correction[-1, -1] = 1.0 if np.linalg.det(left @ right_t) >= 0 else -1.0
        rotation = left @ correction @ right_t
        aligned[index] = current @ rotation + ref_center
    return aligned[0] if single else aligned


def _rng_digest(torch: Any, device: Any) -> str:
    state = torch.cuda.get_rng_state(device) if device.type == "cuda" else torch.get_rng_state()
    return hashlib.sha256(bytes(state.cpu().tolist())).hexdigest()


def _set_seed(torch: Any, seed: int, device: Any) -> None:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)


def _torch_and_upstream() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Import the optional ML stack only when a real model run is requested."""
    try:
        torch = importlib.import_module("torch")
        geometry = importlib.import_module("mars.data.geometry")
        module = importlib.import_module("mars.model.module")
        constants = importlib.import_module("mars.vendored.openfold.residue_constants")
    except ImportError as exc:
        raise RuntimeError(
            "paired model inference requires the pinned MarS-FM checkout on PYTHONPATH and torch"
        ) from exc
    return (torch, geometry.atom14_to_atom37, geometry.atom14_to_frames,
            geometry.atom37_to_torsions, module.MarSModule, constants)


def build_batch(atom14: np.ndarray, sequence: str, samples: int, device: Any) -> dict[str, Any]:
    """Mirror the audited frozen Senba inference batch layout."""
    torch, atom14_to_atom37, atom14_to_frames, atom37_to_torsions, _, rc = _torch_and_upstream()
    seqres = torch.tensor([rc.restype_order[residue] for residue in sequence])
    seqres = seqres.unsqueeze(0).repeat(samples, 1)
    repeated = np.repeat(atom14[None], samples, axis=0).astype(np.float32, copy=False)
    frames = atom14_to_frames(torch.from_numpy(repeated))
    atom37 = torch.from_numpy(atom14_to_atom37(repeated, seqres)).float()
    torsions, torsion_mask = atom37_to_torsions(atom37, seqres)
    batch = {
        "torsions": torsions.unsqueeze(1), "torsion_mask": torsion_mask,
        "trans": frames._trans.unsqueeze(1), "rots": frames._rots._rot_mats.unsqueeze(1),
        "seqres": seqres, "mask": torch.ones_like(seqres, dtype=torch.float32),
    }
    return {key: value.to(device) for key, value in batch.items()}


def _load_model(path: Path, expected_sha256: str, device: Any, torch: Any, mar_s_module: Any) -> tuple[Any, str]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"checkpoint SHA-256 mismatch for {path}: expected {expected_sha256}, got {actual}")
    # The only non-tensor checkpoint value needed by this MarS-FM revision is
    # its argparse Namespace.  Never fall back to an unsafe pickle load.
    if not hasattr(torch.serialization, "add_safe_globals"):
        raise RuntimeError("this torch version cannot safely load the checkpoint with weights_only=True")
    torch.serialization.add_safe_globals([argparse.Namespace])
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError as exc:
        raise RuntimeError("this torch version does not support weights_only=True checkpoint loading") from exc
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be a mapping")
    try:
        args = checkpoint["hyper_parameters"]["args"]
        state_dict = checkpoint["state_dict"]
    except (KeyError, TypeError) as exc:
        raise ValueError("checkpoint lacks MarS-FM hyper_parameters.args or state_dict") from exc
    model = mar_s_module(args=args)
    model.on_load_checkpoint(checkpoint)
    model.load_state_dict(state_dict, strict=True)
    model.eval().to(device)
    return model, actual


def _generate(model: Any, batch: dict[str, Any], ode_steps: int, torch: Any, seed: int, device: Any) -> tuple[np.ndarray, str, str]:
    _set_seed(torch, seed, device)
    before = _rng_digest(torch, device)
    with torch.no_grad():
        atom14, _ = model.inference(batch, num_steps=ode_steps)
    after = _rng_digest(torch, device)
    result = atom14[:, 0].float().cpu().numpy()
    if result.ndim != 4 or result.shape[-2:] != (14, 3) or not np.all(np.isfinite(result)):
        raise RuntimeError("MarSModule.inference returned invalid atom14 coordinates")
    return result, before, after


def run_pair(
    atom14_start: Any, target_ca: Any, sequence: str, source_checkpoint: Path,
    candidate_checkpoint: Path, source_sha256: str, candidate_sha256: str,
    samples: int = 4, ode_steps: int = 10, seed: int = 0,
    ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate paired source/candidate endpoint ensembles and aligned record.

    Both models begin from the same fresh RNG state; the K samples inside each
    vectorized inference call remain independent normal draws.
    """
    if ids is None:
        ids = {}
    atom14, target, sequence, ids = _validate_inputs(atom14_start, target_ca, sequence, samples, ode_steps, seed, ids)
    source_path, candidate_path = Path(source_checkpoint), Path(candidate_checkpoint)
    source_expected = _normalized_sha256(source_sha256, "source_sha256")
    candidate_expected = _normalized_sha256(candidate_sha256, "candidate_sha256")
    if not source_path.is_file() or not candidate_path.is_file():
        raise ValueError("source_checkpoint and candidate_checkpoint must be existing files")
    torch, _, _, _, mar_s_module, _ = _torch_and_upstream()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    started = time.perf_counter()
    source_load_start = time.perf_counter()
    source_model, source_digest = _load_model(source_path, source_expected, device, torch, mar_s_module)
    source_load_seconds = time.perf_counter() - source_load_start
    batch = build_batch(atom14, sequence, samples, device)
    source_generate_start = time.perf_counter()
    source_atom14, source_before, source_after = _generate(source_model, batch, ode_steps, torch, seed, device)
    source_generate_seconds = time.perf_counter() - source_generate_start
    candidate_load_start = time.perf_counter()
    candidate_model, candidate_digest = _load_model(candidate_path, candidate_expected, device, torch, mar_s_module)
    candidate_load_seconds = time.perf_counter() - candidate_load_start
    candidate_generate_start = time.perf_counter()
    candidate_atom14, candidate_before, candidate_after = _generate(candidate_model, batch, ode_steps, torch, seed, device)
    candidate_generate_seconds = time.perf_counter() - candidate_generate_start
    if (source_before, source_after) != (candidate_before, candidate_after):
        raise RuntimeError("paired RNG states differ between source and candidate inference")
    reference = atom14[:, 1]
    aligned_target = kabsch_align(reference, target)
    aligned_source = kabsch_align(reference, source_atom14[:, :, 1])
    aligned_candidate = kabsch_align(reference, candidate_atom14[:, :, 1])
    record = {
        **ids, "units": "angstrom", "alignment": "start_aligned",
        "start": reference.tolist(), "target": aligned_target.tolist(),
        "source": aligned_source.tolist(), "candidate": aligned_candidate.tolist(),
        "raw_coordinates": {
            "target": target.tolist(),
            "source": source_atom14[:, :, 1].tolist(),
            "candidate": candidate_atom14[:, :, 1].tolist(),
        },
        "evaluator": "new_frozen_checkpoint_paired_evaluator_v1",
        "reproduction_status": "NEW_EVALUATOR_NOT_PROVEN_OLD_REPRODUCTION",
        "provenance": {
            "upstream_repository": "https://github.com/valence-labs/mars-fm",
            "upstream_revision": "4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946",
            "source_checkpoint_sha256": source_digest,
            "candidate_checkpoint_sha256": candidate_digest,
            "paired_seed": seed, "samples": samples, "ode_steps": ode_steps,
        },
    }
    return {
        "record": record,
        "runtime": {
            "device": str(device), "total_seconds": time.perf_counter() - started,
            "source": {"checkpoint_sha256": source_digest, "load_seconds": source_load_seconds,
                       "generation_seconds": source_generate_seconds, "rng_before_sha256": source_before,
                       "rng_after_sha256": source_after},
            "candidate": {"checkpoint_sha256": candidate_digest, "load_seconds": candidate_load_seconds,
                          "generation_seconds": candidate_generate_seconds, "rng_before_sha256": candidate_before,
                          "rng_after_sha256": candidate_after},
        },
    }
