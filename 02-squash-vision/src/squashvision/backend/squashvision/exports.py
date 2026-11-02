from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Mapping, Sequence

import imageio_ffmpeg
from sqlalchemy import select
from sqlalchemy.orm import Session

from squashvision.analytics import CanonicalState, canonical_state_for_report
from squashvision.db import Database
from squashvision.models import (
    AssetKind,
    Calibration,
    Correction,
    CorrectionStatus,
    JobChunk,
    Match,
    MediaAsset,
    ReportRevision,
    Stage,
    StagePublication,
)
from squashvision.schemas import ExportSelection
from squashvision.settings import Settings
from squashvision.storage import LocalStorage

_SAFE_EVIDENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_UNSAFE_DISPLAY_TEXT = re.compile(r"(?:[<>`$|;&]|(?:^|[\\/])\.\.(?:[\\/]|$))")
_EXPORT_STAGE_NAME = re.compile(r"\.export-[A-Za-z0-9_-]+\Z")
EXPORT_SCHEMA_VERSION = 1
MAX_EXPORT_MEMBERS = 256
MAX_EXPORT_UNCOMPRESSED_BYTES = 25 * 1024 * 1024 * 1024
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_WINDOWS_DEVICE = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE
)
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_BUILD_LOCK = threading.RLock()

SHOT_COLUMNS = (
    "prediction_id", "timestamp_us", "rally_id", "hitter", "shot_type",
    "is_volley", "outcome", "contact_x_m", "contact_y_m",
    "contact_metric_unavailable_reason", "contact_x_px", "contact_y_px",
    "contact_covariance_json", "contact_provenance",
    "image_point_unavailable_reason", "speed_m_s", "speed_unavailable_reason",
    "review_status", "evidence_provenance", "source_evidence_ids",
)
RALLY_COLUMNS = (
    "prediction_id", "ordinal", "start_frame", "end_frame", "start_timestamp_us",
    "end_timestamp_us", "timing_available", "review_required", "review_status",
    "evidence_provenance", "review_reasons", "source_evidence_ids",
)
ERROR_COLUMNS = (
    "prediction_id", "kind", "target_type", "target_prediction_id",
    "source_timestamp_us", "review_status", "evidence_payload_json",
    "source_evidence_ids",
)
MOVEMENT_COLUMNS = (
    "prediction_id", "player", "source_timestamp_us", "x_m", "y_m",
    "position_covariance", "position_uncertainty_m", "position_provenance",
    "coordinate_unavailable_reason", "observed", "calibration_revision",
    "source_evidence_ids",
)
EVIDENCE_COLUMNS = (
    "evidence_id", "source_timestamp_us", "clip_member", "available",
    "unavailable_reason",
)


class ExportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ExportBundle:
    public_id: str
    match_id: str
    revision: int
    selection: ExportSelection
    relative_path: Path
    path: Path
    byte_size: int
    sha256: str
    created: bool


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _safe_json(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value


def _validate_public_metadata(match: Match) -> None:
    for value in (match.name, match.player_a_name, match.player_b_name):
        if value is None:
            continue
        stripped = value.strip()
        if (
            not stripped
            or stripped.startswith("-")
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
            or _UNSAFE_DISPLAY_TEXT.search(value) is not None
        ):
            raise ExportError(
                "unsafe_export_metadata",
                "match metadata cannot be exported safely",
                422,
            )


def _validate_evidence_identifiers(state: CanonicalState) -> None:
    for rows in (state.shots, state.rallies, state.errors, state.tracks):
        for row in rows:
            values = row.get("source_evidence_ids", [])
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(value, str)
                    or _SAFE_EVIDENCE_ID.fullmatch(value) is None
                    for value in values
                )
            ):
                raise ExportError(
                    "unsafe_evidence_identifier",
                    "report evidence identifiers cannot be exported safely",
                    422,
                )


def cleanup_export_staging(storage: LocalStorage) -> None:
    for entry in storage.root.iterdir():
        if _EXPORT_STAGE_NAME.fullmatch(entry.name) is None:
            continue
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            shutil.rmtree(entry)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _selection_key(match_id: str, revision: int, selection: ExportSelection) -> str:
    return hashlib.sha256(
        _json_bytes(
            {
                "matchId": match_id,
                "revision": revision,
                "selection": selection.model_dump(mode="json", by_alias=True),
            }
        )
    ).hexdigest()


def validate_archive_members(names: Iterable[str]) -> tuple[str, ...]:
    result = tuple(names)
    if not result or len(result) > MAX_EXPORT_MEMBERS:
        raise ValueError("archive member count is outside the supported bound")
    identities: set[str] = set()
    for name in result:
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError("archive members must be non-empty POSIX paths")
        if any(ord(character) < 32 or ord(character) == 127 for character in name):
            raise ValueError("archive member contains a control character")
        if name.startswith("/") or _DRIVE_PREFIX.match(name):
            raise ValueError("archive member must be relative")
        raw_parts = name.split("/")
        if any(part in {"", ".", ".."} for part in raw_parts):
            raise ValueError("archive member contains an unsafe component")
        path = PurePosixPath(name)
        if path.is_absolute() or path.as_posix() != name:
            raise ValueError("archive member is not a normalized POSIX path")
        for part in raw_parts:
            if part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part):
                raise ValueError("archive member is unsafe on common filesystems")
        identity = unicodedata.normalize("NFKC", name).casefold()
        if identity in identities:
            raise ValueError("archive members contain duplicate or confusable targets")
        identities.add(identity)
    return result


def validate_staging_tree(stage: Path, members: Iterable[str]) -> int:
    names = validate_archive_members(members)
    root = Path(stage).resolve(strict=True)
    total = 0
    for name in names:
        candidate = root.joinpath(*PurePosixPath(name).parts)
        current = root
        for part in PurePosixPath(name).parts[:-1]:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("archive staging parent must be a real directory")
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("archive staging members must be regular files")
        try:
            candidate.resolve(strict=True).relative_to(root)
        except ValueError as error:
            raise ValueError("archive staging member escapes its private directory") from error
        total += info.st_size
        if total > MAX_EXPORT_UNCOMPRESSED_BYTES:
            raise ValueError("archive uncompressed bytes exceed the supported bound")
    return total


def _csv_bytes(columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        rendered: list[object] = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, (list, tuple, dict)):
                rendered.append(
                    json.dumps(
                        _safe_json(value),
                        ensure_ascii=True,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            elif value is None:
                rendered.append("")
            elif isinstance(value, bool):
                rendered.append("true" if value else "false")
            else:
                rendered.append(value)
        writer.writerow(rendered)
    return text.getvalue().encode("utf-8")


def _canonical_payload(state: CanonicalState) -> dict[str, object]:
    return {
        "shots": _safe_json(state.shots),
        "rallies": _safe_json(state.rallies),
        "errors": _safe_json(state.errors),
        "movement": _safe_json(state.tracks),
    }


def _report_sections(row: ReportRevision) -> dict[str, object]:
    sections: dict[str, object] = {}
    for name, raw in sorted((row.sections or {}).items()):
        payload = dict(raw) if isinstance(raw, dict) else {"availability": {"available": False, "reason": "invalid_stored_section"}}
        payload.pop("_evidence_ids", None)
        sections[name] = _safe_json(payload)
    return sections


def _model_snapshot_for_report(
    session: Session,
    match: Match,
    report: ReportRevision,
    storage: LocalStorage,
) -> tuple[list[dict[str, object]], str | None]:
    publication = session.scalar(
        select(StagePublication)
        .where(
            StagePublication.match_id == match.id,
            StagePublication.stage == Stage.REPORT,
            StagePublication.prediction_revision
            == report.prediction_revision,
        )
        .order_by(StagePublication.id)
    )
    if publication is None:
        return [], "immutable_pipeline_provenance_unavailable"
    chunks = session.scalars(
        select(JobChunk)
        .where(
            JobChunk.analysis_job_id == publication.analysis_job_id,
            JobChunk.stage == Stage.REPORT,
            JobChunk.artifact_path.is_not(None),
        )
        .order_by(JobChunk.id)
    ).all()
    for chunk in chunks:
        if (
            chunk.artifact_path is None
            or chunk.artifact_size is None
            or chunk.artifact_sha256 is None
        ):
            continue
        relative = Path(chunk.artifact_path)
        try:
            artifact = storage.resolve(
                relative,
                owned_paths={relative},
            ).absolute
            if _hash_file(artifact) != (
                chunk.artifact_size,
                chunk.artifact_sha256,
            ):
                continue
            raw = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        identities = raw.get("model_manifests") if isinstance(raw, dict) else None
        if not isinstance(identities, dict):
            continue
        snapshot: list[dict[str, object]] = []
        for name, candidate in sorted(identities.items()):
            if not isinstance(name, str) or not isinstance(candidate, dict):
                raise ExportError(
                    "model_provenance_invalid",
                    "immutable model provenance is invalid",
                    500,
                )
            snapshot.append(
                {
                    "name": name,
                    "manifestId": candidate.get("manifest_id"),
                    "sha256": candidate.get("digest"),
                    "requestedRevision": candidate.get(
                        "requested_revision"
                    ),
                    "resolvedRevision": candidate.get("revision"),
                    "compatibilityVersion": candidate.get(
                        "compatibility_version"
                    ),
                    "required": candidate.get("required"),
                    "state": candidate.get("state"),
                    "errorCode": candidate.get("error_code"),
                    **({"inputPreprocessing": _safe_json(raw["ball_preprocessing"])}
                       if name == "ball" and isinstance(raw.get("ball_preprocessing"), dict)
                       else {}),
                }
            )
        return snapshot, None
    raise ExportError(
        "model_provenance_unavailable",
        "immutable model provenance artifact is unavailable",
        500,
    )


def _report_document(
    match: Match,
    report: ReportRevision,
    state: CanonicalState,
    corrections: Sequence[Correction],
    calibration: Calibration | None,
    models: Sequence[Mapping[str, object]],
    model_unavailable_reason: str | None,
) -> dict[str, object]:
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "match": {
            "id": match.public_id,
            "name": match.name,
            "players": {"a": match.player_a_name, "b": match.player_b_name},
            "playedOn": match.played_on.isoformat() if match.played_on is not None else None,
            "score": match.score,
        },
        "report": {
            "revision": report.revision,
            "schemaVersion": report.schema_version,
            "sections": _report_sections(report),
            "sectionHashes": dict(sorted((report.section_hashes or {}).items())),
            "dependencyHashes": dict(sorted((report.dependency_hashes or {}).items())),
        },
        "canonicalEvidence": _canonical_payload(state),
        "calibration": None if calibration is None else {
            "revision": calibration.revision,
            "confidence": calibration.confidence,
            "capabilities": _safe_json(calibration.capabilities),
            "result": _safe_json(calibration.result),
        },
        "models": [dict(item) for item in models],
        "modelSnapshotAvailability": {
            "available": model_unavailable_reason is None,
            "reason": model_unavailable_reason,
        },
        "corrections": [
            {
                "id": row.public_id,
                "command": row.command_type,
                "targetType": row.target_type,
                "targetId": row.target_id,
                "before": _safe_json(row.before_payload),
                "after": _safe_json(row.after_payload),
                "reason": row.reason,
                "sourceTimestampUs": row.source_timestamp_us,
                "sourceEvidenceIds": list(row.source_evidence_ids),
            }
            for row in corrections
        ],
        "provenance": {
            "predictionRevision": report.prediction_revision,
            "calibrationRevision": report.calibration_revision,
            "correctionIds": [row.public_id for row in corrections],
            "reportSectionHashes": dict(sorted((report.section_hashes or {}).items())),
        },
    }


def _offline_html(document: Mapping[str, object]) -> bytes:
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = html.escape(str(document["match"]["name"]))  # type: ignore[index]
    body = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title} — SquashVision report</title><style>body{{font:16px system-ui,sans-serif;max-width:72rem;margin:auto;padding:2rem;color:#17211b;background:#f7f4ec}}h1,h2{{line-height:1.1}}pre{{white-space:pre-wrap;background:#fff;border:1px solid #ccd4ce;padding:1rem;overflow:auto}}.meta{{color:#526059}}</style></head><body><main><p class=\"meta\">SquashVision offline report · immutable revision {document['report']['revision']}</p><h1>{title}</h1><h2>Report data</h2><pre id=\"report\"></pre></main><script id=\"report-data\" type=\"application/json\">{encoded}</script><script>const d=JSON.parse(document.getElementById('report-data').textContent);document.getElementById('report').textContent=JSON.stringify(d,null,2);</script></body></html>\n"""  # type: ignore[index]
    return body.encode("utf-8")


def _evidence_timestamps(state: CanonicalState) -> dict[str, int]:
    timestamps: dict[str, int] = {}
    collections = (state.shots, state.rallies, state.errors, state.tracks)
    for rows in collections:
        for row in rows:
            raw_timestamp = row.get("source_timestamp_us")
            if raw_timestamp is None:
                raw_timestamp = row.get("start_timestamp_us")
            if not isinstance(raw_timestamp, int) or raw_timestamp < 0:
                continue
            for evidence_id in row.get("source_evidence_ids", []):
                if isinstance(evidence_id, str):
                    timestamps.setdefault(evidence_id, raw_timestamp)
    return timestamps


def _run_ffmpeg_clip(arguments: list[str], output: Path) -> None:
    command = [imageio_ffmpeg.get_ffmpeg_exe(), *arguments, str(output)]
    subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=180,
    )


def _write_evidence_clips(
    stage: Path,
    selection: ExportSelection,
    state: CanonicalState,
    original: Path,
    duration_us: int | None,
) -> list[dict[str, object]]:
    timestamps = _evidence_timestamps(state)
    missing = [evidence_id for evidence_id in selection.evidence_ids if evidence_id not in timestamps]
    if missing:
        raise ExportError("evidence_not_found", "selected evidence is unavailable in the requested report revision", 404)
    rows: list[dict[str, object]] = []
    clip_directory = stage / "evidence"
    if selection.evidence_ids:
        clip_directory.mkdir(mode=0o700)
    clip_duration_us = round(selection.evidence_duration_seconds * 1_000_000)
    for index, evidence_id in enumerate(selection.evidence_ids, start=1):
        timestamp_us = timestamps[evidence_id]
        start_us = max(0, timestamp_us - clip_duration_us // 2)
        if duration_us is not None:
            start_us = min(start_us, max(0, duration_us - clip_duration_us))
            actual_duration_us = min(clip_duration_us, duration_us - start_us)
        else:
            actual_duration_us = clip_duration_us
        if actual_duration_us <= 0:
            raise ExportError("evidence_unavailable", "selected evidence has no bounded source duration")
        member = f"evidence/clip-{index:03d}.mp4"
        output = stage.joinpath(*PurePosixPath(member).parts)
        arguments = [
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start_us / 1_000_000:.6f}",
            "-i", str(original),
            "-t", f"{actual_duration_us / 1_000_000:.6f}",
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", "-y",
        ]
        try:
            _run_ffmpeg_clip(arguments, output)
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            raise ExportError("clip_generation_failed", "evidence clip generation failed", 500) from error
        rows.append({
            "evidence_id": evidence_id,
            "source_timestamp_us": timestamp_us,
            "clip_member": member,
            "available": True,
            "unavailable_reason": None,
        })
    return rows


def _write_csv_members(stage: Path, state: CanonicalState, evidence_rows: Sequence[Mapping[str, object]]) -> None:
    directory = stage / "data"
    directory.mkdir(mode=0o700)
    shots = [
        {
            **row,
            "timestamp_us": row.get("source_timestamp_us"),
            "contact_metric_unavailable_reason": row.get(
                "control_point_unavailable_reason"
            ),
            "contact_covariance_json": row.get("contact_covariance"),
        }
        for row in state.shots
    ]
    errors = [
        {**row, "evidence_payload_json": row.get("evidence_payload")}
        for row in state.errors
    ]
    movement = [
        {
            **row,
            "player": row.get("slot"),
            "coordinate_unavailable_reason": (
                None
                if row.get("x_m") is not None
                and row.get("y_m") is not None
                and row.get("position_provenance") == "measured"
                else (
                    row.get("position_unavailable_reason")
                    or (
                        "not_observed"
                        if row.get("observed") is False
                        else "calibration_unavailable"
                        if row.get("calibration_revision") is None
                        else "floor_position_unavailable"
                    )
                )
            ),
        }
        for row in state.tracks
    ]
    payloads = {
        "canonical_shots.csv": _csv_bytes(SHOT_COLUMNS, shots),
        "rallies.csv": _csv_bytes(RALLY_COLUMNS, state.rallies),
        "errors_review.csv": _csv_bytes(ERROR_COLUMNS, errors),
        "movement.csv": _csv_bytes(MOVEMENT_COLUMNS, movement),
        "evidence.csv": _csv_bytes(EVIDENCE_COLUMNS, evidence_rows),
    }
    for name, payload in payloads.items():
        (directory / name).write_bytes(payload)


def _copy_original(stage: Path, source: Path) -> str:
    suffix = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ".bin"
    directory = stage / "original"
    directory.mkdir(mode=0o700)
    member = f"original/source{suffix}"
    destination = directory / f"source{suffix}"
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    return member

def _stage_verified_original(
    stage: Path,
    storage: LocalStorage,
    relative: Path,
    expected_size: int | None,
    expected_sha256: str | None,
) -> Path:
    if (
        expected_size is None
        or expected_size < 0
        or expected_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ExportError(
            "original_integrity_failed",
            "source media has no verified stored integrity",
            409,
        )
    suffix = relative.suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) is None:
        suffix = ".bin"
    destination = stage / f".verified-original{suffix}"
    digest = hashlib.sha256()
    size = 0
    try:
        descriptor = storage.open_owned(
            relative,
            owned_paths={relative},
        )
        with os.fdopen(descriptor, "rb") as source, destination.open(
            "xb"
        ) as output:
            while block := source.read(1024 * 1024):
                output.write(block)
                size += len(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, PermissionError, ValueError) as error:
        destination.unlink(missing_ok=True)
        raise ExportError(
            "original_integrity_failed",
            "source media failed secure integrity verification",
            409,
        ) from error
    if size != expected_size or digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ExportError(
            "original_integrity_failed",
            "source media failed stored integrity verification",
            409,
        )
    return destination


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.flag_bits |= 0x800
    return info


def _write_archive(stage: Path, member_names: Sequence[str], selection: ExportSelection, revision: int) -> Path:
    names = tuple(sorted(member_names))
    validate_staging_tree(stage, names)
    manifest_members: list[dict[str, object]] = []
    for name in names:
        size, digest = _hash_file(stage.joinpath(*PurePosixPath(name).parts))
        manifest_members.append({"name": name, "bytes": size, "sha256": digest})
    manifest = {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "createdRevision": revision,
        "selection": selection.model_dump(mode="json", by_alias=True),
        "members": manifest_members,
    }
    manifest_path = stage / "manifest.json"
    manifest_path.write_bytes(_json_bytes(manifest))
    ordered = (*names, "manifest.json")
    validate_staging_tree(stage, ordered)
    archive_path = stage / ".bundle.zip"
    with zipfile.ZipFile(
        archive_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for name in ordered:
            source = stage.joinpath(*PurePosixPath(name).parts)
            with source.open("rb") as stream, archive.open(_zip_info(name), "w", force_zip64=True) as destination:
                shutil.copyfileobj(stream, destination, length=1024 * 1024)
    return archive_path


def _bundle_from_asset(match_id: str, asset: MediaAsset, storage: LocalStorage, *, created: bool) -> ExportBundle:
    metadata = dict(asset.probe_metadata or {})
    selection = ExportSelection.model_validate(metadata["selection"])
    stored = storage.resolve(Path(asset.relative_path), owned_paths={Path(asset.relative_path)})
    if asset.byte_size is None or asset.checksum_sha256 is None:
        raise ExportError("export_corrupt", "completed export metadata is incomplete", 500)
    return ExportBundle(
        public_id=asset.public_id,
        match_id=match_id,
        revision=int(metadata["revision"]),
        selection=selection,
        relative_path=stored.relative,
        path=stored.absolute,
        byte_size=asset.byte_size,
        sha256=asset.checksum_sha256,
        created=created,
    )


def build_export(
    match_id: str,
    revision: int,
    selection: ExportSelection,
    *,
    database: Database | None = None,
    storage: LocalStorage | None = None,
) -> ExportBundle:
    if database is None or storage is None:
        settings = Settings()
        database = database or Database.open(settings)
        if settings.storage_root is None:
            raise RuntimeError("storage root is not configured")
        storage = storage or LocalStorage(settings.storage_root)
    key = _selection_key(match_id, revision, selection)
    with _BUILD_LOCK:
        with database.session() as session:
            match = session.scalar(select(Match).where(Match.public_id == match_id))
            if match is None or match.deletion_state != "active":
                raise ExportError("match_not_found", "match was not found", 404)
            _validate_public_metadata(match)
            existing = session.scalars(
                select(MediaAsset).where(
                    MediaAsset.match_id == match.id,
                    MediaAsset.kind == AssetKind.EXPORT,
                ).order_by(MediaAsset.id)
            ).all()
            for asset in existing:
                metadata = asset.probe_metadata or {}
                if metadata.get("selectionKey") != key or metadata.get("state") != "completed":
                    continue
                try:
                    bundle = _bundle_from_asset(
                        match_id, asset, storage, created=False
                    )
                    if _hash_file(bundle.path) == (
                        bundle.byte_size,
                        bundle.sha256,
                    ):
                        return bundle
                    bundle.path.unlink(missing_ok=True)
                    session.delete(asset)
                except FileNotFoundError:
                    session.delete(asset)
                except (PermissionError, ValueError, ExportError) as error:
                    raise ExportError(
                        "export_storage_unsafe",
                        "existing export storage failed ownership validation",
                        500,
                    ) from error
            report = session.scalar(
                select(ReportRevision).where(
                    ReportRevision.match_id == match.id,
                    ReportRevision.revision == revision,
                )
            )
            if report is None:
                raise ExportError("report_not_found", "report revision was not found", 404)
            state = canonical_state_for_report(session, match, report)
            models, model_unavailable_reason = _model_snapshot_for_report(
                session,
                match,
                report,
                storage,
            )
            corrections = session.scalars(
                select(Correction).where(
                    Correction.match_id == match.id,
                    Correction.prediction_revision == report.prediction_revision,
                    Correction.status == CorrectionStatus.ACTIVE,
                    Correction.expected_report_revision < report.revision,
                ).order_by(Correction.id)
            ).all()
            calibration = None
            if report.calibration_revision is not None:
                calibration = session.scalar(
                    select(Calibration).where(
                        Calibration.match_id == match.id,
                        Calibration.revision
                        == report.calibration_revision,
                    )
                )
            original_asset = session.scalar(
                select(MediaAsset).where(
                    MediaAsset.match_id == match.id,
                    MediaAsset.kind == AssetKind.ORIGINAL,
                ).order_by(MediaAsset.id)
            )
            if original_asset is None:
                raise ExportError(
                    "original_not_found",
                    "source media is unavailable",
                    404,
                )
            original_relative = Path(original_asset.relative_path)
            original_size = original_asset.byte_size
            original_sha256 = original_asset.checksum_sha256
            document = _report_document(
                match,
                report,
                state,
                corrections,
                calibration,
                models,
                model_unavailable_reason,
            )
            duration_us = original_asset.duration_us

        stage = Path(tempfile.mkdtemp(prefix=".export-", dir=storage.root))
        os.chmod(stage, 0o700)
        published: Path | None = None
        try:
            original = _stage_verified_original(
                stage,
                storage,
                original_relative,
                original_size,
                original_sha256,
            )
            member_names: list[str] = []
            evidence_rows = _write_evidence_clips(stage, selection, state, original, duration_us)
            member_names.extend(str(row["clip_member"]) for row in evidence_rows)
            if "json" in selection.formats:
                (stage / "report.json").write_bytes(_json_bytes(document))
                member_names.append("report.json")
            if "html" in selection.formats:
                (stage / "report.html").write_bytes(_offline_html(document))
                member_names.append("report.html")
            if "csv" in selection.formats:
                _write_csv_members(stage, state, evidence_rows)
                member_names.extend(
                    f"data/{name}" for name in (
                        "canonical_shots.csv", "errors_review.csv", "evidence.csv",
                        "movement.csv", "rallies.csv",
                    )
                )
            if selection.include_original:
                member_names.append(_copy_original(stage, original))
            archive_path = _write_archive(stage, member_names, selection, revision)
            byte_size, digest = _hash_file(archive_path)
            allocated = storage.allocate(AssetKind.EXPORT, ".zip")
            storage.publish(allocated, archive_path)
            published = allocated.absolute
            with database.session() as session:
                match = session.scalar(select(Match).where(Match.public_id == match_id))
                if match is None or match.deletion_state != "active":
                    raise ExportError("match_not_found", "match was not found", 404)
                asset = MediaAsset(
                    match=match,
                    kind=AssetKind.EXPORT,
                    relative_path=str(allocated.relative),
                    checksum_sha256=digest,
                    byte_size=byte_size,
                    duration_us=None,
                    probe_metadata={
                        "type": "export-bundle",
                        "schemaVersion": EXPORT_SCHEMA_VERSION,
                        "state": "completed",
                        "revision": revision,
                        "selection": selection.model_dump(mode="json", by_alias=True),
                        "selectionKey": key,
                    },
                )
                session.add(asset)
                session.flush()
                public_id = asset.public_id
            return ExportBundle(
                public_id=public_id,
                match_id=match_id,
                revision=revision,
                selection=selection,
                relative_path=allocated.relative,
                path=allocated.absolute,
                byte_size=byte_size,
                sha256=digest,
                created=True,
            )
        except ExportError:
            if published is not None:
                published.unlink(missing_ok=True)
            raise
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            if published is not None:
                published.unlink(missing_ok=True)
            raise ExportError("export_failed", "export bundle could not be published", 500) from error
        except BaseException:
            if published is not None:
                published.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _owned_export_bundle(
    match_id: str,
    export_id: str,
    *,
    database: Database,
    storage: LocalStorage,
) -> ExportBundle:
    with database.session() as session:
        row = session.scalar(
            select(MediaAsset)
            .join(Match, MediaAsset.match_id == Match.id)
            .where(
                Match.public_id == match_id,
                Match.deletion_state == "active",
                MediaAsset.public_id == export_id,
                MediaAsset.kind == AssetKind.EXPORT,
            )
        )
        if (
            row is None
            or (row.probe_metadata or {}).get("state") != "completed"
        ):
            raise ExportError(
                "export_not_found",
                "export was not found",
                404,
            )
        return _bundle_from_asset(
            match_id,
            row,
            storage,
            created=False,
        )


def get_export(
    match_id: str,
    export_id: str,
    *,
    database: Database,
    storage: LocalStorage,
) -> ExportBundle:
    bundle = _owned_export_bundle(
        match_id,
        export_id,
        database=database,
        storage=storage,
    )
    try:
        signature = _hash_file(bundle.path)
    except OSError as error:
        raise ExportError("export_unavailable", "completed export file is unavailable", 410) from error
    if signature != (bundle.byte_size, bundle.sha256):
        raise ExportError("export_corrupt", "completed export failed integrity validation", 410)
    return bundle


def open_export_download(
    match_id: str,
    export_id: str,
    *,
    database: Database,
    storage: LocalStorage,
) -> tuple[ExportBundle, Iterator[bytes]]:
    bundle = _owned_export_bundle(
        match_id,
        export_id,
        database=database,
        storage=storage,
    )
    try:
        descriptor = storage.open_owned(
            bundle.relative_path,
            owned_paths={bundle.relative_path},
        )
    except (OSError, PermissionError, ValueError) as error:
        raise ExportError(
            "export_unavailable",
            "completed export file is unavailable",
            410,
        ) from error
    try:
        digest = hashlib.sha256()
        size = 0
        while block := os.read(descriptor, 1024 * 1024):
            size += len(block)
            digest.update(block)
        if (size, digest.hexdigest()) != (
            bundle.byte_size,
            bundle.sha256,
        ):
            raise ExportError(
                "export_corrupt",
                "completed export failed integrity validation",
                410,
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
    except BaseException:
        os.close(descriptor)
        raise

    def stream() -> Iterator[bytes]:
        with os.fdopen(descriptor, "rb") as source:
            while block := source.read(1024 * 1024):
                yield block

    return bundle, stream()
