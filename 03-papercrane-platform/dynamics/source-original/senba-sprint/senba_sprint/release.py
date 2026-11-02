"""Pinned, bounded downloader and integrity auditor for the public SENBA release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import urlopen


REPOSITORY = "vkali08/senba"
REVISION = "90cce9e822d511459a206ae3a06cbd8dbb243b09"
CHECKPOINT_SHA256 = "f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c"
CHECKPOINT_SIZE = 136_711_098
TIMEOUT_SECONDS = 30
MAX_FILES = 100
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_WEIGHT_BYTES = 200 * 1024 * 1024
SNAPSHOT_NAME = "release-snapshot.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _url(path: str) -> str:
    return (
        f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/"
        f"{quote(path, safe='/')}?download=true"
    )


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("manifest file paths must be non-empty POSIX relative paths")
    parsed = urlsplit(value)
    parts = value.split("/")
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError(f"unsafe manifest file path: {value!r}")
    return value


def _expected(entry: dict[str, Any], index: int) -> tuple[str, int]:
    sha256 = entry.get("sha256")
    size = entry.get("size", entry.get("size_bytes"))
    if isinstance(sha256, str) and sha256.startswith("sha256:"):
        sha256 = sha256[len("sha256:"):]
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ValueError(
            f"files[{index}].sha256 must be lowercase SHA-256 hex, optionally prefixed by 'sha256:'"
        )
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"files[{index}].size must be a non-negative integer")
    return sha256, size


def _validate_manifest(raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("release-manifest.json exceeds the 2 MiB metadata cap")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"release-manifest.json is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("release manifest must be an object with a files array")
    if len(manifest["files"]) > MAX_FILES:
        raise ValueError(f"release manifest exceeds the {MAX_FILES}-file cap")

    checked = []
    seen = set()
    for index, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict):
            raise ValueError(f"files[{index}] must be an object")
        path = _safe_path(entry.get("path"))
        if path in seen or path in ("release-manifest.json", SNAPSHOT_NAME):
            raise ValueError(f"duplicate or reserved manifest path: {path}")
        seen.add(path)
        sha256, size = _expected(entry, index)
        is_checkpoint = path.lower().endswith(".ckpt")
        cap = MAX_WEIGHT_BYTES if is_checkpoint else MAX_TEXT_BYTES
        if size > cap:
            kind = "checkpoint" if is_checkpoint else "metadata"
            raise ValueError(f"{path} exceeds the {kind} size cap")
        checked.append(
            {"path": path, "sha256": sha256, "size": size, "checkpoint": is_checkpoint}
        )
    return manifest, checked


def _read_manifest() -> bytes:
    with urlopen(_url("release-manifest.json"), timeout=TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_TEXT_BYTES + 1)
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("release-manifest.json exceeds the 2 MiB metadata cap")
    return raw


def _download(path: str, directory: Path, cap: int) -> tuple[Path, dict[str, Any], bytes | None]:
    digest = hashlib.sha256()
    size = 0
    preview = bytearray() if cap == MAX_TEXT_BYTES else None
    fd, temporary_name = tempfile.mkstemp(prefix=".senba-download-", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, urlopen(
            _url(path), timeout=TIMEOUT_SECONDS
        ) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    raise ValueError(f"download exceeded size cap for {path}")
                digest.update(chunk)
                output.write(chunk)
                if preview is not None:
                    preview.extend(chunk)
            output.flush()
            os.fsync(output.fileno())
        return temporary, {"sha256": digest.hexdigest(), "size": size}, bytes(preview) if preview is not None else None
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _file_receipt(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size": size}


def _place_exclusive(temporary: Path, destination: Path, observed: dict[str, Any]) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(temporary, destination)
        return "downloaded"
    except FileExistsError:
        if not destination.is_file() or _file_receipt(destination) != observed:
            return "existing_cache_conflict"
        return "reused_identical"
    finally:
        temporary.unlink(missing_ok=True)


def _store_bytes(data: bytes, destination: Path) -> str:
    fd, name = tempfile.mkstemp(prefix=".senba-metadata-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        observed = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        return _place_exclusive(temporary, destination, observed)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _local_target(root: Path, relative: str) -> Path:
    target = root.joinpath(*PurePosixPath(relative).parts)
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest path escapes destination through a symlink: {relative}") from exc
    return target


def fetch_release(destination: str | os.PathLike[str], include_checkpoint: bool = False) -> dict[str, Any]:
    """Fetch the pinned release, retaining mismatches as auditable local artifacts."""
    if not isinstance(include_checkpoint, bool):
        raise ValueError("include_checkpoint must be boolean")
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("destination must be a directory")

    manifest_raw = _read_manifest()
    manifest, entries = _validate_manifest(manifest_raw)
    for entry in entries:
        _local_target(root, entry["path"])
    manifest_observed = {
        "sha256": hashlib.sha256(manifest_raw).hexdigest(), "size": len(manifest_raw)
    }
    manifest_disposition = _store_bytes(manifest_raw, root / "release-manifest.json")
    warnings = []
    if manifest_disposition == "existing_cache_conflict":
        warnings.append("existing release-manifest.json differs; it was not overwritten")
    if manifest.get("repository") != REPOSITORY:
        warnings.append(
            f"manifest repository {manifest.get('repository')!r} differs from pinned {REPOSITORY!r}; no redirect was followed"
        )
    if manifest.get("revision") not in (None, REVISION):
        warnings.append("manifest revision differs from the pinned revision; no redirect was followed")

    files = []
    for entry in entries:
        expected = {"sha256": entry["sha256"], "size": entry["size"]}
        item: dict[str, Any] = {
            "path": entry["path"], "selected": include_checkpoint or not entry["checkpoint"],
            "expected": expected, "observed": None, "matched": None,
            "available": False, "disposition": "excluded_checkpoint",
        }
        if entry["checkpoint"]:
            item["pinned_expected"] = {
                "sha256": CHECKPOINT_SHA256, "size": CHECKPOINT_SIZE
            }
            if expected != item["pinned_expected"]:
                warnings.append(f"checkpoint manifest expectation differs from pinned expectation: {entry['path']}")
        if not item["selected"]:
            files.append(item)
            continue
        cap = MAX_WEIGHT_BYTES if entry["checkpoint"] else MAX_TEXT_BYTES
        try:
            temporary, observed, text = _download(entry["path"], root, cap)
            item["observed"] = observed
            item["matched"] = observed == expected and (
                not entry["checkpoint"] or observed == item["pinned_expected"]
            )
            item["disposition"] = _place_exclusive(
                temporary, _local_target(root, entry["path"]), observed
            )
            item["available"] = item["disposition"] in ("downloaded", "reused_identical")
            if text is not None and b"pikachuandme1/senba" in text:
                warnings.append(f"stale repository reference found in {entry['path']}: pikachuandme1/senba")
        except Exception as exc:  # Per-file failures must not suppress the remaining audit.
            item["matched"] = False
            item["disposition"] = "fetch_failed"
            item["error"] = f"{type(exc).__name__}: {exc}"
        files.append(item)

    report = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "include_checkpoint": include_checkpoint,
        "manifest": {"observed": manifest_observed, "disposition": manifest_disposition},
        "warnings": warnings,
        "files": files,
    }
    selected = [item for item in files if item["selected"]]
    report["ok"] = manifest_disposition != "existing_cache_conflict" and all(
        item["matched"] and item["available"] for item in selected
    )
    snapshot_report = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "include_checkpoint": include_checkpoint,
        "manifest_observed": manifest_observed,
        "warnings": warnings,
        "files": [
            {
                key: item[key]
                for key in (
                    "path", "selected", "expected", "pinned_expected", "observed", "matched", "available"
                )
                if key in item
            }
            for item in files
        ],
    }
    snapshot = json.dumps(snapshot_report, indent=2, sort_keys=True).encode() + b"\n"
    report["snapshot_disposition"] = _store_bytes(snapshot, root / SNAPSHOT_NAME)
    if report["snapshot_disposition"] == "existing_cache_conflict":
        report["warnings"].append("existing release-snapshot.json differs; it was not overwritten")
        report["ok"] = False
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--with-checkpoint", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = fetch_release(args.destination, args.with_checkpoint)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
