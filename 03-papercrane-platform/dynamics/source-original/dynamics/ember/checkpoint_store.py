"""Atomic Unix checkpoint aliases, independent of the tensor serializer.

The alias is a relative symlink to a complete, content-addressed file. Replacing
one symlink commits data and checksum together; a crash cannot pair new data
with an old checksum sidecar. Keep the current and previous generation per alias.
Copy the directory with symlinks preserved when moving checkpoints.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .io import file_hash


@contextmanager
def _locked(alias: Path, *, exclusive: bool):
    with (alias.parent / ("." + alias.name + ".lock")).open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _resolve(alias: Path) -> tuple[Path, str]:
    if not alias.is_symlink():
        raise ValueError("Checkpoint must be an atomically published symlink alias")
    name = os.readlink(alias)
    prefix = "." + alias.name + "."
    if Path(name).name != name or not name.startswith(prefix) or not name.endswith(".blob"):
        raise ValueError("Checkpoint alias points outside its content store")
    digest = name[len(prefix) : -len(".blob")]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Checkpoint content address is invalid")
    path = alias.parent / name
    if path.is_symlink() or file_hash(path) != digest:
        raise ValueError("Checkpoint content checksum differs")
    return path, digest


@contextmanager
def checkpoint_reader(alias: str | Path):
    """Hold a reader lock until deserialization completes, preventing pruning."""
    alias = Path(alias)
    with _locked(alias, exclusive=False):
        path, digest = _resolve(alias)
        with path.open("rb") as handle:
            yield handle, digest


def publish_checkpoint(alias: str | Path, writer) -> str:
    """Serialize with writer(binary_handle); publish only after a durable write."""
    alias = Path(alias)
    alias.parent.mkdir(parents=True, exist_ok=True)
    with _locked(alias, exclusive=True):
        previous = _resolve(alias)[0] if alias.is_symlink() else None
        if alias.exists() and previous is None:
            raise ValueError("Refusing to overwrite a non-checkpoint file")
        fd, temporary = tempfile.mkstemp(prefix=".checkpoint-write-", dir=alias.parent)
        link = Path(temporary + ".link")
        try:
            with os.fdopen(fd, "wb") as handle:
                writer(handle)
                handle.flush()
                os.fsync(handle.fileno())
            digest = file_hash(temporary)
            blob = alias.parent / ("." + alias.name + "." + digest + ".blob")
            os.replace(temporary, blob)
            os.symlink(blob.name, link)
            os.replace(link, alias)
            directory_fd = os.open(alias.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            # Current plus prior complete checkpoint; unfinished writes are never
            # aliases. Readers of this alias hold a shared lock during loading.
            for stale in alias.parent.glob("." + alias.name + ".*.blob"):
                if stale not in {blob, previous}:
                    stale.unlink()
            return digest
        finally:
            Path(temporary).unlink(missing_ok=True)
            link.unlink(missing_ok=True)
