"""Content-addressed frozen embeddings. No implicit model downloads."""

from __future__ import annotations

import fcntl
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .execution import ExecutionPolicy
from .io import atomic_write_json, content_hash, file_hash, read_json
from .schema import AMINO_ACIDS, require_hash, require_text


@dataclass(frozen=True)
class EmbeddingKey:
    sequence: str
    encoder: str
    checkpoint_sha256: str
    tokenizer_sha256: str
    implementation_sha256: str
    layer: int = 30
    width: int = 640
    preprocessing: str = "full_sequence_no_special_tokens_v1"

    def __post_init__(self) -> None:
        if not self.sequence or set(self.sequence) - AMINO_ACIDS:
            raise ValueError("Invalid embedding sequence")
        require_text(self.encoder, "encoder")
        for name in ("checkpoint_sha256", "tokenizer_sha256", "implementation_sha256"):
            require_hash(getattr(self, name), name)
        if self.width < 1 or self.layer < 1:
            raise ValueError("Embedding layer/width must be positive")

    @property
    def digest(self) -> str:
        return content_hash(self)


class EmbeddingCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def paths(self, key: EmbeddingKey) -> tuple[Path, Path]:
        base = self.root / key.digest[:2] / key.digest
        return base.with_suffix(".npy"), base.with_suffix(".json")

    def store(self, key: EmbeddingKey, values: np.ndarray) -> dict:
        array = np.asarray(values, dtype=np.float32)
        self._validate(key, array)
        path, meta_path = self.paths(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize same-key writers so an immutable receipt can never certify
        # another worker's bytes. Readers only accept a complete manifest.
        with path.with_suffix(".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._store_locked(key, array, path, meta_path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _store_locked(self, key, array, path, meta_path) -> dict:
        if meta_path.exists():
            existing = self.load(key)
            if not np.array_equal(existing, array):
                raise ValueError("Immutable cache key already exists with different embeddings")
            return read_json(meta_path)
        fd, name = tempfile.mkstemp(prefix=".embedding-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                np.save(handle, array, allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        metadata = {
            "key": asdict(key),
            "key_sha256": key.digest,
            "array_sha256": file_hash(path),
            "shape": list(array.shape),
            "dtype": "float32",
            "complete": True,
        }
        atomic_write_json(meta_path, metadata)
        return metadata

    @staticmethod
    def _validate(key: EmbeddingKey, array: np.ndarray) -> None:
        if array.shape != (len(key.sequence), key.width) or array.dtype != np.float32:
            raise ValueError("Embedding shape/dtype mismatch; one float32 row per sequence residue required")
        if not np.isfinite(array).all():
            raise ValueError("Embeddings contain non-finite values")

    def load(self, key: EmbeddingKey) -> np.ndarray:
        path, meta_path = self.paths(key)
        meta = read_json(meta_path)
        if (
            meta.get("key") != asdict(key)
            or meta.get("key_sha256") != key.digest
            or meta.get("complete") is not True
        ):
            raise ValueError("Embedding cache key/provenance mismatch")
        if file_hash(path) != meta.get("array_sha256"):
            raise ValueError("Embedding cache checksum mismatch")
        array = np.load(path, allow_pickle=False)
        self._validate(key, array)
        return array


def extract_local_esm2(
    sequence: str, model_directory: str | Path, *, policy: ExecutionPolicy, device: str = "cpu"
) -> np.ndarray:
    """Single-sequence convenience adapter. Reuse FrozenESM2Encoder for a cohort."""
    return FrozenESM2Encoder(model_directory, policy=policy, device=device).encode(sequence)


class FrozenESM2Encoder:
    """Future compute-stage adapter: load once, reuse, local safetensors only.

    Hash/audit the directory before constructing cache keys. No hub download or
    learned inference occurs until the explicit execution policy allows it.
    Single-sequence streaming bounds activation memory and avoids padding work.
    """

    def __init__(self, model_directory: str | Path, *, policy: ExecutionPolicy, device: str = "cpu"):
        policy.require_model_execution("ESM-2 embedding inference")
        from transformers import AutoModel, AutoTokenizer

        directory = Path(model_directory)
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(directory), local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModel.from_pretrained(
            str(directory), local_files_only=True, trust_remote_code=False, use_safetensors=True
        )
        if (
            self.model.config.model_type != "esm"
            or self.model.config.hidden_size != 640
            or self.model.config.num_hidden_layers != 30
        ):
            raise ValueError("Expected the ESM-2 150M, 30-layer, width-640 checkpoint")
        self.model.requires_grad_(False).eval().to(device)

    def encode(self, sequence: str) -> np.ndarray:
        import torch

        if not sequence or set(sequence) - AMINO_ACIDS:
            raise ValueError("Unsupported sequence")
        if len(sequence) + 2 > self.model.config.max_position_embeddings:
            raise ValueError("Sequence exceeds local checkpoint context length")
        tokens = self.tokenizer(
            " ".join(sequence),
            return_tensors="pt",
            return_special_tokens_mask=True,
            add_special_tokens=True,
            truncation=False,
        )
        special = tokens.pop("special_tokens_mask")[0].bool()
        if int((~special).sum()) != len(sequence):
            raise ValueError("Tokenizer did not produce exactly one token per residue")
        tokens = {name: value.to(self.device) for name, value in tokens.items()}
        with torch.inference_mode():
            output = self.model(**tokens).last_hidden_state[0]
        array = output[~special.to(self.device)].float().cpu().numpy()
        if array.shape != (len(sequence), 640) or not np.isfinite(array).all():
            raise ValueError("Invalid frozen feature output")
        return array
