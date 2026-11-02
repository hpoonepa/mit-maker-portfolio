from __future__ import annotations

import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import URL, create_engine, func, inspect, select, text
from sqlalchemy.exc import DatabaseError

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.analytics import CanonicalState, _coaching_section, build_report
from squashvision.app import create_app
from squashvision.corrections import (
    CorrectionConflict,
    RevisionConflict,
    _conflict_candidate,
    apply_correction,
    list_conflicts,
    reapply_corrections,
    resolve_conflict,
)
from squashvision.db import Database
from squashvision.models import (
    AssetKind,
    Calibration,
    Correction,
    CorrectionStatus,
    ErrorCandidate,
    ErrorKind,
    MediaAsset,
    Match,
    PlayerSlot,
    PlayerTrack,
    Rally,
    ReportRevision,
    Shot,
    ShotKind,
)
from squashvision.schemas import ConflictResolution, CorrectionCommand
from squashvision.settings import Settings


def make_database(tmp_path: Path) -> Database:
    return Database.open(Settings(data_dir=tmp_path))


def migrate_legacy_database(tmp_path: Path) -> Database:
    settings = Settings(data_dir=tmp_path)
    assert settings.database_path is not None
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(settings.database_path))
    )
    Database._install_sqlite_pragmas(engine)
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        alembic_command.upgrade(config, "0005")
        connection.execute(
            text(
                "INSERT INTO matches "
                "(id, public_id, created_at, name) "
                "VALUES (1, '00000000-0000-4000-8000-000000000001', CURRENT_TIMESTAMP, 'legacy')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO rallies "
                "(id, public_id, created_at, match_id, ordinal, start_frame, end_frame) "
                "VALUES (1, '00000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP, 1, 1, 100, 200)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO corrections "
                "(id, public_id, created_at, match_id, kind, replacement_value) VALUES "
                "(1, '00000000-0000-4000-8000-000000000021', CURRENT_TIMESTAMP, 1, 'accept', NULL),"
                "(2, '00000000-0000-4000-8000-000000000022', CURRENT_TIMESTAMP, 1, 'replace', 'drop')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO report_revisions "
                "(id, public_id, created_at, match_id, revision) "
                "VALUES (1, '00000000-0000-4000-8000-000000000031', CURRENT_TIMESTAMP, 1, 1)"
            )
        )
        alembic_command.upgrade(config, "head")
    return Database(engine)


def seed_match(database: Database, *, prediction_revision: int = 1) -> str:
    with database.session() as session:
        match = Match(name="Analytics", player_a_name="A", player_b_name="B")
        session.add(match)
        session.flush()
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=f"videos/original/{match.public_id}.mp4",
        )
        session.add(
            Calibration(
                match=match,
                media_asset=asset,
                revision=1,
                keypoints=[],
                result={},
                confidence=1.0,
                capabilities={},
            )
        )
        rallies = [
            Rally(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="rally-1",
                ordinal=1,
                start_frame=0,
                end_frame=500,
                start_timestamp_us=0,
                end_timestamp_us=5_000_000,
                source_evidence_ids=["r1-start", "r1-end"],
            ),
            Rally(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="rally-2",
                ordinal=2,
                start_frame=700,
                end_frame=1_500,
                start_timestamp_us=7_000_000,
                end_timestamp_us=15_000_000,
                source_evidence_ids=["r2-start", "r2-end"],
            ),
        ]
        session.add_all(rallies)
        session.flush()
        kinds = [ShotKind.BOAST] * 4 + [ShotKind.DRIVE] * 8
        shots: list[Shot] = []
        for index, kind in enumerate(kinds):
            source_us = (
                10_000_000
                if index == 8
                else 500_000 + index * 900_000
                if index < 5
                else 7_100_000 + (index - 5) * 1_100_000
            )
            rally = rallies[0] if source_us < 5_000_000 else rallies[1]
            shots.append(
                Shot(
                    match=match,
                    rally=rally,
                    prediction_revision=prediction_revision,
                    prediction_id=f"shot-{index + 1}",
                    frame_index=source_us // 10_000,
                    source_timestamp_us=source_us,
                    source_evidence_ids=[f"contact-{index + 1}"],
                    hitter=PlayerSlot.NEAR if index < 9 else PlayerSlot.FAR,
                    kind=kind,
                    is_volley=index in {0, 4},
                    outcome="error" if index in {1, 2, 3, 9, 10, 11} else "winner",
                    contact_x_m=1.0 + (index % 3),
                    contact_y_m=2.0 if kind is ShotKind.DRIVE and index < 8 else 6.0,
                    contact_x_px=320.0 + index,
                    contact_y_px=240.0 + index,
                    contact_covariance=[[4.0, 0.0], [0.0, 9.0]],
                    contact_provenance="observed",
                    contact_source_width=1920,
                    contact_source_height=1080,
                    speed_m_s=None if index < 2 else 30.0 + index,
                    speed_unavailable_reason="uncalibrated" if index < 2 else None,
                )
            )
        session.add_all(shots)
        session.flush()
        position_fields = {
            "position_covariance": [[0.01, 0.0], [0.0, 0.01]],
            "position_uncertainty_m": 0.1,
            "position_provenance": "measured",
            "position_unavailable_reason": None,
        }
        tracks = [
            PlayerTrack(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="track-a-1",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=0,
                source_evidence_ids=["track-a-1"],
                x_m=3.2,
                y_m=7.0,
                observed=True,
                calibration_revision=1,
                **position_fields,
            ),
            PlayerTrack(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="track-a-2",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=1_000_000,
                source_evidence_ids=["track-a-2"],
                x_m=3.2,
                y_m=5.49,
                observed=True,
                calibration_revision=1,
                **position_fields,
            ),
            PlayerTrack(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="track-a-3",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=2_000_000,
                source_evidence_ids=["track-a-3"],
                x_m=4.2,
                y_m=5.49,
                observed=True,
                calibration_revision=1,
                **position_fields,
            ),
            PlayerTrack(
                match=match,
                prediction_revision=prediction_revision,
                prediction_id="track-a-out",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=2_500_000,
                source_evidence_ids=["track-a-out"],
                x_m=8.0,
                y_m=5.0,
                observed=True,
                calibration_revision=1,
                **position_fields,
            ),
        ]
        session.add_all(tracks)
        for index in range(6):
            shot = shots[[1, 2, 3, 9, 10, 11][index]]
            session.add(
                ErrorCandidate(
                    match=match,
                    prediction_revision=prediction_revision,
                    prediction_id=f"error-{index + 1}",
                    kind=ErrorKind.SHOT,
                    target_type="shot",
                    target_prediction_id=shot.prediction_id,
                    source_timestamp_us=shot.source_timestamp_us,
                    source_evidence_ids=list(shot.source_evidence_ids),
                    evidence_version=1,
                    evidence_payload={"subjective": True},
                    review_status="accepted" if index < 5 else "pending",
                )
            )
        session.flush()
        return match.public_id


def command(
    match_id: str,
    *,
    command_type: str = "change_shot_type",
    target_type: str | None = None,
    target_id: str = "shot-1",
    expected: int = 1,
    payload: dict[str, object] | None = None,
    source_evidence_ids: list[str] | None = None,
    source_timestamp_us: int | None = None,
    review_entity_type: str | None = None,
    review_entity_id: str | None = None,
) -> CorrectionCommand:
    inferred_target = (
        "error_candidate"
        if command_type in {"accept", "reject"}
        else "rally"
        if command_type in {"split_rally", "merge_rallies"}
        else "shot"
    )
    inferred_payload: dict[str, object] = (
        {"shot_type": "drop"} if payload is None else payload
    )
    return CorrectionCommand.model_validate(
        {
            "command_type": command_type,
            "match_id": match_id,
            "target_type": target_type or inferred_target,
            "target_id": target_id,
            "expected_report_revision": expected,
            "reason": "reviewed video",
            "payload": inferred_payload,
            "source_evidence_ids": source_evidence_ids,
            "source_timestamp_us": source_timestamp_us,
            "review_entity_type": review_entity_type,
            "review_entity_id": review_entity_id,
        }
    )


@pytest.mark.parametrize(
    "shot_type",
    ["unknown", "serve", "drive", "boast", "drop", "lob", "kill"],
)
def test_correction_schema_accepts_only_canonical_shot_taxonomy(
    shot_type: str,
) -> None:
    parsed = command("match", payload={"shot_type": shot_type})
    assert parsed.payload == {"shot_type": shot_type}


@pytest.mark.parametrize("shot_type", ["straight_drive", "crosscourt_drive", "return"])
def test_correction_schema_rejects_noncanonical_shot_taxonomy(
    shot_type: str,
) -> None:
    with pytest.raises(ValueError, match="canonical shot_type"):
        command("match", payload={"shot_type": shot_type})


@pytest.mark.parametrize(
    "outcome",
    ["unknown", "in_play", "winner", "error", "stroke", "let"],
)
def test_correction_schema_accepts_only_canonical_outcome_taxonomy(
    outcome: str,
) -> None:
    parsed = command(
        "match",
        command_type="change_outcome",
        payload={"outcome": outcome},
    )
    assert parsed.payload == {"outcome": outcome}


@pytest.mark.parametrize("outcome", ["continuation", "continues", "terminal"])
def test_correction_schema_rejects_classifier_internal_outcomes(
    outcome: str,
) -> None:
    with pytest.raises(ValueError, match="canonical outcome"):
        command(
            "match",
            command_type="change_outcome",
            payload={"outcome": outcome},
        )


def test_report_aggregates_are_typed_evidenced_and_deterministic(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)

    report = build_report(match_id, 1, database)
    sections = report.sections

    assert sections["overview"].payload["rally_count"] == 2
    assert sections["overview"].payload["active_duration_s"] == pytest.approx(13.0)
    assert sections["overview"].payload["rest_duration_s"] == pytest.approx(2.0)
    assert sections["overview"].payload["work_rest_ratio"] == {
        "available": True,
        "value": 6.5,
        "reason": None,
    }
    assert sections["shots"].payload["players"]["near"]["count"] == 9
    assert sections["shots"].payload["players"]["near"]["types"]["boast"]["count"] == 4
    assert sections["shots"].payload["players"]["near"]["types"]["boast"]["share"] == pytest.approx(4 / 9)
    assert sections["shots"].payload["players"]["near"]["volleys"] == 2
    assert "contact-1" in sections["shots"].evidence_ids
    assert sections["shots"].payload["players"]["near"]["sides"]
    assert sections["shots"].payload["aggregate_contract"] == "complete"
    assert sections["shots"].payload["players"]["near"]["types"]["boast"]["representative_event_id"]
    heatmap = sections["movement"].payload["heatmap"]
    assert heatmap["court_width_m"] == 6.4 and heatmap["court_length_m"] == 9.75
    assert sum(sum(row) for row in heatmap["counts"]) == 3
    assert heatmap["excluded"] == {"out_of_court": 1}
    assert sections["movement"].payload["distance_m"] == {
        "available": True,
        "value": pytest.approx(2.51),
        "reason": None,
    }
    assert sections["movement"].payload["t_recovery"]["sample_count"] >= 1
    assert sections["movement"].payload["players"]["near"]["sample_count"] >= 1
    assert sections["errors"].payload["objective_count"] == 6
    assert sections["errors"].payload["reviewed_subjective_count"] == 5
    assert sections["errors"].payload["unreviewed_candidate_count"] == 1
    assert any(item["status"] == "pending" and not item["counted"] for item in sections["errors"].payload["items"])
    assert sections["trajectory"].payload["average_speed_m_s"]["available"] is True
    assert sections["trajectory"].payload["image_trajectory"]["availability"]["available"] is True
    assert sections["trajectory"].payload["image_trajectory"]["items"][0]["provenance"] == "observed"
    assert sections["trajectory"].payload["court_trajectory"]["availability"]["available"] is True
    assert sections["head_to_head"].payload["near"]["volleys"] == 2
    assert sections["head_to_head"].payload["near"]["movement"]["sample_count"] >= 1
    boast = next(item for item in sections["coaching"].payload["findings"] if item["rule"] == "boast_overuse")
    assert boast["sample_count"] == 9
    assert boast["measured"] == pytest.approx(4 / 9)
    assert boast["supporting_event_ids"]
    assert "44.4%" in boast["evidence"]


def test_unavailable_metrics_never_emit_nan_or_fake_zero(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    with database.session() as session:
        match = Match(name="Unavailable")
        session.add(match)
        session.flush()
        match_id = match.public_id
        session.add(
            Shot(
                match=match,
                prediction_revision=1,
                prediction_id="shot-1",
                frame_index=1,
                source_timestamp_us=1,
                source_evidence_ids=["e1"],
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.DRIVE,
                outcome="in_play",
                speed_m_s=None,
                speed_unavailable_reason="uncalibrated",
            )
        )
        session.add(
            PlayerTrack(
                match=match,
                prediction_revision=1,
                prediction_id="track-1",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=1,
                source_evidence_ids=["t1"],
                x_m=3.2,
                y_m=5.49,
                observed=True,
                calibration_revision=None,
            )
        )

    report = build_report(match_id, 1, database)
    assert report.sections["overview"].payload["work_rest_ratio"] == {
        "available": False,
        "value": None,
        "reason": "no_rest_duration",
    }
    assert report.sections["movement"].payload["distance_m"] == {
        "available": False,
        "value": None,
        "reason": "missing_calibration",
    }
    assert report.sections["trajectory"].payload["average_speed_m_s"] == {
        "available": False,
        "value": None,
        "reason": "uncalibrated",
    }
    dumped = report.model_dump_json()
    assert "NaN" not in dumped and all(math.isfinite(value) for value in [0.0])
    assert report.sections["coaching"].payload["findings"] == []


def test_every_coaching_rule_requires_thresholded_linked_evidence() -> None:
    shots: list[dict[str, object]] = []
    for index in range(12):
        rally_id = f"long-{index + 1}" if index < 6 else "short-1"
        shots.append(
            {
                "prediction_id": f"coaching-shot-{index + 1}",
                "source_timestamp_us": index * 1_000_000,
                "source_evidence_ids": [f"coaching-evidence-{index + 1}"],
                "hitter": "near",
                "shot_type": "boast" if index < 4 else "drive",
                "is_volley": False,
                "outcome": "error" if index < 6 else "in_play",
                "contact_x_m": 1.0 if index < 6 else 4.0,
                "contact_y_m": 2.0 if 4 <= index < 8 else 7.0,
                "speed_m_s": None,
                "speed_unavailable_reason": "uncalibrated",
                "rally_id": rally_id,
            }
        )
    rallies = [
        {
            "prediction_id": f"long-{index + 1}",
            "ordinal": index + 1,
            "start_frame": index * 2_000,
            "end_frame": index * 2_000 + 1_200,
            "start_timestamp_us": index * 20_000_000,
            "end_timestamp_us": index * 20_000_000 + 12_000_000,
            "timing_available": True,
            "source_evidence_ids": [f"long-evidence-{index + 1}"],
        }
        for index in range(6)
    ] + [
        {
            "prediction_id": "short-1",
            "ordinal": 7,
            "start_frame": 20_000,
            "end_frame": 20_500,
            "start_timestamp_us": 140_000_000,
            "end_timestamp_us": 145_000_000,
            "timing_available": True,
            "source_evidence_ids": ["short-evidence-1"],
        }
    ]
    errors = [
        {
            "prediction_id": f"reviewed-{index + 1}",
            "target_type": "shot",
            "target_prediction_id": f"coaching-shot-{index + 1}",
            "source_timestamp_us": index * 1_000_000,
            "source_evidence_ids": [f"reviewed-evidence-{index + 1}"],
            "review_status": "accepted",
            "evidence_payload": {},
        }
        for index in range(6)
    ]
    movement = {
        "t_recovery": {
            "sample_count": 5,
            "median_seconds": {"available": True, "value": 2.5, "reason": None},
            "samples": [
                {
                    "seconds": 2.5,
                    "shot_id": f"coaching-shot-{index + 1}",
                    "position_id": f"track-{index + 1}",
                }
                for index in range(5)
            ],
        }
    }

    payload, evidence_ids = _coaching_section(
        CanonicalState(shots, rallies, errors, []), movement
    )
    findings = {item["rule"]: item for item in payload["findings"]}

    assert set(findings) == {
        "boast_overuse",
        "one_side_error_concentration",
        "shallow_drive_pattern",
        "slow_t_recovery",
        "long_rally_error_concentration",
    }
    assert all(item["supporting_event_ids"] for item in findings.values())
    assert all(item["sample_count"] >= 5 for item in findings.values())
    assert all(item["evidence"] for item in findings.values())
    assert set(evidence_ids) >= set(findings["slow_t_recovery"]["supporting_event_ids"])
    long = findings["long_rally_error_concentration"]
    assert long["long_rate"] == 1.0
    assert long["short_rate"] == 0.0
    assert long["difference"] == 1.0
    assert long["threshold"] == 0.20


def test_coaching_emits_nothing_below_minimum_samples() -> None:
    shots = [
        {
            "prediction_id": f"small-{index}",
            "source_timestamp_us": index,
            "source_evidence_ids": [f"small-evidence-{index}"],
            "hitter": "near",
            "shot_type": "boast",
            "is_volley": False,
            "outcome": "error",
            "contact_x_m": 1.0,
            "contact_y_m": 2.0,
            "speed_m_s": None,
            "speed_unavailable_reason": "uncalibrated",
            "rally_id": None,
        }
        for index in range(5)
    ]
    movement = {
        "t_recovery": {
            "sample_count": 4,
            "median_seconds": {"available": True, "value": 4.0, "reason": None},
            "samples": [],
        }
    }

    payload, evidence_ids = _coaching_section(
        CanonicalState(shots, [], [], []), movement
    )

    assert payload == {"findings": []}
    assert evidence_ids == []


@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("change_hitter", {"hitter": "far"}),
        ("change_shot_type", {"shot_type": "drop"}),
        ("adjust_contact_time", {"source_timestamp_us": 650_000}),
        ("change_outcome", {"outcome": "error"}),
        ("ball_control_point", {"x_m": 2.1, "y_m": 3.1}),
    ],
)
def test_shot_corrections_fold_without_mutating_predictions(
    tmp_path: Path, command_type: str, payload: dict[str, object]
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    first = build_report(match_id, 1, database)

    revision = apply_correction(
        command(match_id, command_type=command_type, payload=payload), database
    )

    assert revision.revision == 2
    with database.session() as session:
        predicted = session.scalar(
            select(Shot).where(Shot.match.has(public_id=match_id), Shot.prediction_id == "shot-1")
        )
        audit = session.scalar(select(Correction).where(Correction.match.has(public_id=match_id)))
        assert predicted is not None and predicted.kind is ShotKind.BOAST
        assert audit is not None
        assert audit.before_payload["prediction_id"] == "shot-1"
        assert audit.after_payload != audit.before_payload
    second = build_report(match_id, 2, database)
    if command_type in {"change_hitter", "adjust_contact_time"}:
        assert (
            second.sections["movement"].dependency_hash
            != first.sections["movement"].dependency_hash
        )
        assert (
            second.sections["coaching"].dependency_hash
            != first.sections["coaching"].dependency_hash
        )
    else:
        assert second.sections["movement"].hash == first.sections["movement"].hash
    if command_type == "change_shot_type":
        assert second.sections["shots"].hash != first.sections["shots"].hash
        assert second.sections["rallies"].hash == first.sections["rallies"].hash
    if command_type == "ball_control_point":
        assert second.sections["trajectory"].hash != first.sections["trajectory"].hash


def test_predictions_corrections_and_reports_are_database_immutable(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    apply_correction(command(match_id), database)

    for statement in (
        "UPDATE shots SET outcome = 'winner'",
        "DELETE FROM corrections",
        "UPDATE report_revisions SET revision = 99",
    ):
        with pytest.raises(DatabaseError, match="immutable"):
            with database.session() as session:
                session.execute(text(statement))


def test_accept_reject_and_command_validation(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)

    accepted = apply_correction(
        command(
            match_id,
            command_type="accept",
            target_id="error-6",
            payload={},
        ).model_copy(update={"target_type": "error_candidate"}),
        database,
    )
    reject_database = make_database(tmp_path / "reject")
    reject_match_id = seed_match(reject_database)
    build_report(reject_match_id, 1, reject_database)
    rejected = apply_correction(
        command(
            reject_match_id,
            command_type="reject",
            target_id="error-6",
            payload={},
        ).model_copy(update={"target_type": "error_candidate"}),
        reject_database,
    )
    assert accepted.revision == 2 and rejected.revision == 2
    final = build_report(match_id, 2, database)
    assert final.sections["errors"].payload["reviewed_subjective_count"] == 6
    assert final.sections["overview"].payload["reviewed_error_count"] == 6
    with pytest.raises(ValidationError):
        command(match_id, command_type="change_hitter", payload={"hitter": "center"})


def test_split_merge_enforce_rally_invariants(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)

    split = command(
        match_id,
        command_type="split_rally",
        target_id="rally-2",
        payload={"split_timestamp_us": 10_000_000},
    ).model_copy(update={"target_type": "rally"})
    assert apply_correction(split, database).revision == 2
    rallies = build_report(match_id, 2, database).sections["rallies"].payload["items"]
    assert [(item["start_timestamp_us"], item["end_timestamp_us"]) for item in rallies] == [
        (0, 5_000_000),
        (7_000_000, 10_000_000),
        (10_000_000, 15_000_000),
    ]
    split_assigned = [
        shot_id for item in rallies for shot_id in item["shot_ids"]
    ]
    assert set(split_assigned) == {f"shot-{index}" for index in range(1, 13)}
    assert "shot-9" in rallies[2]["shot_ids"]
    split_child_id = rallies[2]["prediction_id"]
    merge = command(
        match_id,
        command_type="merge_rallies",
        target_id="rally-2",
        expected=2,
        payload={"other_target_id": split_child_id},
    ).model_copy(update={"target_type": "rally"})
    assert apply_correction(merge, database).revision == 3
    merged = build_report(match_id, 3, database).sections["rallies"].payload["items"]
    merged_assigned = [
        shot_id for item in merged for shot_id in item["shot_ids"]
    ]
    assert set(merged_assigned) == {f"shot-{index}" for index in range(1, 13)}
    merged_rally = next(item for item in merged if item["prediction_id"] == "rally-2")
    assert "shot-9" in merged_rally["shot_ids"]
    with pytest.raises(ValidationError):
        command(
            match_id,
            command_type="split_rally",
            target_id="rally-1",
            expected=3,
            payload={"split_timestamp_us": 0},
        )


def test_optimistic_revision_is_atomic_and_concurrent(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    commands = [
        command(match_id, target_id="shot-1"),
        command(match_id, target_id="shot-2"),
    ]

    def apply(item: CorrectionCommand) -> str:
        try:
            apply_correction(item, database)
            return "won"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, commands))

    assert sorted(results) == ["conflict", "won"]
    with database.session() as session:
        assert session.scalar(select(func.count(Correction.id))) == 1
        assert session.scalar(select(func.count(ReportRevision.id))) == 2


def add_reanalysis_shot(
    database: Database,
    match_id: str,
    *,
    prediction_id: str,
    source_timestamp_us: int,
    evidence_ids: list[str],
) -> None:
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            Shot(
                match=match,
                prediction_revision=2,
                prediction_id=prediction_id,
                frame_index=source_timestamp_us // 10_000,
                source_timestamp_us=source_timestamp_us,
                source_evidence_ids=evidence_ids,
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.BOAST,
                outcome="in_play",
            )
        )


def _review_reanalysis_command(
    database: Database,
    match_id: str,
    case: str,
) -> tuple[CorrectionCommand, str, str]:
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        if case == "outcome":
            session.add_all(
                [
                    Shot(
                        match=match,
                        prediction_revision=1,
                        prediction_id="outcome-shot-old",
                        frame_index=2_000,
                        source_timestamp_us=20_000_000,
                        source_evidence_ids=["outcome-target"],
                        hitter=PlayerSlot.NEAR,
                        kind=ShotKind.DRIVE,
                        outcome="in_play",
                    ),
                    ErrorCandidate(
                        match=match,
                        prediction_revision=1,
                        prediction_id="outcome-review-old",
                        kind=ErrorKind.SHOT,
                        target_type="shot",
                        target_prediction_id="outcome-shot-old",
                        source_timestamp_us=20_010_000,
                        source_evidence_ids=["outcome-review-evidence"],
                        evidence_version=1,
                        evidence_payload={"subjective": True},
                        review_status="pending",
                    ),
                ]
            )
            return (
                command(
                    match_id,
                    command_type="change_outcome",
                    target_id="outcome-shot-old",
                    payload={"outcome": "winner"},
                    source_timestamp_us=20_000_000,
                    source_evidence_ids=["outcome-target"],
                    review_entity_type="error_candidate",
                    review_entity_id="outcome-review-old",
                ),
                "outcome-shot-new",
                "outcome-review-new",
            )
        if case == "type":
            session.add(
                Shot(
                    match=match,
                    prediction_revision=1,
                    prediction_id="type-shot-old",
                    frame_index=2_100,
                    source_timestamp_us=21_000_000,
                    source_evidence_ids=["type-target"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                    review_required=True,
                    review_status="pending",
                )
            )
            return (
                command(
                    match_id,
                    command_type="change_shot_type",
                    target_id="type-shot-old",
                    payload={"shot_type": "drop"},
                    source_timestamp_us=21_000_000,
                    source_evidence_ids=["type-target"],
                    review_entity_type="shot",
                    review_entity_id="type-shot-old",
                ),
                "type-shot-new",
                "type-shot-new",
            )
        session.add(
            Rally(
                match=match,
                prediction_revision=1,
                prediction_id="split-rally-old",
                ordinal=3,
                start_frame=2_200,
                end_frame=2_700,
                start_timestamp_us=22_000_000,
                end_timestamp_us=27_000_000,
                source_evidence_ids=["split-target"],
                review_required=True,
                review_status="pending",
            )
        )
        return (
            command(
                match_id,
                command_type="split_rally",
                target_id="split-rally-old",
                payload={"split_timestamp_us": 24_500_000},
                source_timestamp_us=22_000_000,
                source_evidence_ids=["split-target"],
                review_entity_type="rally",
                review_entity_id="split-rally-old",
            ),
            "split-rally-new",
            "split-rally-new",
        )


def _add_review_reanalysis_revision(
    database: Database, match_id: str, case: str
) -> None:
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        if case == "outcome":
            session.add_all(
                [
                    Shot(
                        match=match,
                        prediction_revision=2,
                        prediction_id="outcome-shot-new",
                        frame_index=2_001,
                        source_timestamp_us=20_010_000,
                        source_evidence_ids=["outcome-target"],
                        hitter=PlayerSlot.NEAR,
                        kind=ShotKind.DRIVE,
                        outcome="in_play",
                    ),
                    ErrorCandidate(
                        match=match,
                        prediction_revision=2,
                        prediction_id="outcome-review-new",
                        kind=ErrorKind.SHOT,
                        target_type="shot",
                        target_prediction_id="outcome-shot-new",
                        source_timestamp_us=20_020_000,
                        source_evidence_ids=["outcome-review-evidence"],
                        evidence_version=1,
                        evidence_payload={"subjective": True},
                        review_status="pending",
                    ),
                ]
            )
        elif case == "type":
            session.add(
                Shot(
                    match=match,
                    prediction_revision=2,
                    prediction_id="type-shot-new",
                    frame_index=2_101,
                    source_timestamp_us=21_010_000,
                    source_evidence_ids=["type-target"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                    review_required=True,
                    review_status="pending",
                )
            )
        else:
            session.add(
                Rally(
                    match=match,
                    prediction_revision=2,
                    prediction_id="split-rally-new",
                    ordinal=1,
                    start_frame=2_201,
                    end_frame=2_701,
                    start_timestamp_us=22_010_000,
                    end_timestamp_us=27_010_000,
                    source_evidence_ids=["split-target"],
                    review_required=True,
                    review_status="pending",
                )
            )


@pytest.mark.parametrize("case", ["outcome", "type", "split"])
def test_reapply_remaps_review_entity_and_resolves_new_revision(
    tmp_path: Path, case: str
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    correction_command, expected_target_id, expected_review_id = (
        _review_reanalysis_command(database, match_id, case)
    )
    build_report(match_id, 1, database)
    apply_correction(correction_command, database)
    _add_review_reanalysis_revision(database, match_id, case)

    result = reapply_corrections(1, 2, database, match_id=match_id)

    assert result.reapplied == 1
    assert result.conflicts == []
    with database.session() as session:
        reapplied = session.scalar(
            select(Correction).where(
                Correction.prediction_revision == 2,
                Correction.status == CorrectionStatus.ACTIVE,
            )
        )
        latest = session.scalar(
            select(ReportRevision).order_by(ReportRevision.revision.desc())
        )
        assert reapplied is not None
        assert reapplied.target_id == expected_target_id
        assert reapplied.review_entity_id == expected_review_id
        assert latest is not None
        assert latest.sections["review"]["reviewed_count"] == 1
        assert latest.sections["review"]["pending_ids"] == []


def test_reapply_corrections_is_scoped_to_one_match_when_revisions_overlap(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    first_match = seed_match(database)
    second_match = seed_match(database)
    for match_id in (first_match, second_match):
        build_report(match_id, 1, database)
        apply_correction(command(match_id), database)
        add_reanalysis_shot(
            database,
            match_id,
            prediction_id=f"new-{match_id}",
            source_timestamp_us=500_000,
            evidence_ids=["contact-1"],
        )

    result = reapply_corrections(
        1,
        2,
        database,
        match_id=first_match,
    )

    assert result.reapplied == 1
    with database.session() as session:
        first = session.scalar(
            select(Match).where(Match.public_id == first_match)
        )
        second = session.scalar(
            select(Match).where(Match.public_id == second_match)
        )
        assert first is not None and second is not None
        assert session.scalar(
            select(func.count(Correction.id)).where(
                Correction.match_id == first.id,
                Correction.prediction_revision == 2,
            )
        ) == 1
        assert session.scalar(
            select(func.count(Correction.id)).where(
                Correction.match_id == second.id,
                Correction.prediction_revision == 2,
            )
        ) == 0


def test_reapplied_active_decision_continues_to_next_prediction_revision(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    apply_correction(command(match_id), database)
    add_reanalysis_shot(
        database,
        match_id,
        prediction_id="revision-two-shot",
        source_timestamp_us=500_000,
        evidence_ids=["contact-1"],
    )
    first = reapply_corrections(1, 2, database, match_id=match_id)
    assert first.reapplied == 1

    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            Shot(
                match=match,
                prediction_revision=3,
                prediction_id="revision-three-shot",
                frame_index=50,
                source_timestamp_us=500_000,
                source_evidence_ids=["contact-1"],
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.BOAST,
                outcome="in_play",
            )
        )

    second = reapply_corrections(2, 3, database, match_id=match_id)

    assert second.reapplied == 1
    assert second.conflicts == []
    with database.session() as session:
        latest = session.scalar(
            select(Correction).where(
                Correction.prediction_revision == 3,
                Correction.status == CorrectionStatus.ACTIVE,
            )
        )
        assert latest is not None
        assert latest.target_id == "revision-three-shot"


@pytest.mark.parametrize(("review_count", "reason"), [(0, "no_matching_review_entity"), (2, "ambiguous_review_entity_match")])
def test_reapply_error_review_entity_zero_or_ambiguous_match_is_conflict(
    tmp_path: Path, review_count: int, reason: str
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add_all(
            [
                Shot(
                    match=match,
                    prediction_revision=1,
                    prediction_id="review-target-old",
                    frame_index=3_000,
                    source_timestamp_us=30_000_000,
                    source_evidence_ids=["review-target"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                ),
                ErrorCandidate(
                    match=match,
                    prediction_revision=1,
                    prediction_id="review-old",
                    kind=ErrorKind.SHOT,
                    target_type="shot",
                    target_prediction_id="review-target-old",
                    source_timestamp_us=30_000_000,
                    source_evidence_ids=["review-own-evidence"],
                    evidence_version=1,
                    evidence_payload={},
                    review_status="pending",
                ),
            ]
        )
    
    build_report(match_id, 1, database)
    apply_correction(
        command(
            match_id,
            command_type="change_outcome",
            target_id="review-target-old",
            payload={"outcome": "winner"},
            source_timestamp_us=30_000_000,
            source_evidence_ids=["review-target"],
            review_entity_type="error_candidate",
            review_entity_id="review-old",
        ),
        database,
    )
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            Shot(
                match=match,
                prediction_revision=2,
                prediction_id="review-target-new",
                frame_index=3_001,
                source_timestamp_us=30_010_000,
                source_evidence_ids=["review-target"],
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.DRIVE,
                outcome="in_play",
            )
        )
        session.add_all(
            [
                ErrorCandidate(
                    match=match,
                    prediction_revision=2,
                    prediction_id=f"review-new-{index}",
                    kind=ErrorKind.SHOT,
                    target_type="shot",
                    target_prediction_id="review-target-new",
                    source_timestamp_us=30_010_000,
                    source_evidence_ids=["review-own-evidence"],
                    evidence_version=1,
                    evidence_payload={},
                    review_status="pending",
                )
                for index in range(review_count)
            ]
        )

    result = reapply_corrections(1, 2, database, match_id=match_id)

    assert result.reapplied == 0
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == reason
    with database.session() as session:
        assert session.scalar(
            select(func.count(Correction.id)).where(
                Correction.prediction_revision == 2,
                Correction.status == CorrectionStatus.ACTIVE,
            )
        ) == 0
    if review_count == 2:
        assert result.conflicts[0].candidate_ids == [
            "review-new-0",
            "review-new-1",
        ]
        report = resolve_conflict(
            match_id,
            result.conflicts[0].correction_id,
            ConflictResolution(
                resolution="select",
                candidate_id="review-new-1",
                expected_report_revision=2,
                reason="review evidence identifies the accepted event",
            ),
            database,
        )
        assert report.revision == 3
        with database.session() as session:
            resolved = session.scalar(
                select(Correction).where(
                    Correction.prediction_revision == 2,
                    Correction.status == CorrectionStatus.ACTIVE,
                )
            )
            assert resolved is not None
            assert resolved.target_id == "review-target-new"
            assert resolved.review_entity_id == "review-new-1"


def test_conflict_resolution_remaps_error_review_entity_for_selected_target(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add_all(
            [
                Shot(
                    match=match,
                    prediction_revision=1,
                    prediction_id="selected-target-old",
                    frame_index=4_000,
                    source_timestamp_us=40_000_000,
                    source_evidence_ids=["selected-target"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                ),
                ErrorCandidate(
                    match=match,
                    prediction_revision=1,
                    prediction_id="selected-review-old",
                    kind=ErrorKind.SHOT,
                    target_type="shot",
                    target_prediction_id="selected-target-old",
                    source_timestamp_us=40_000_000,
                    source_evidence_ids=["selected-review"],
                    evidence_version=1,
                    evidence_payload={},
                    review_status="pending",
                ),
            ]
        )
    build_report(match_id, 1, database)
    apply_correction(
        command(
            match_id,
            command_type="change_outcome",
            target_id="selected-target-old",
            payload={"outcome": "winner"},
            source_timestamp_us=40_000_000,
            source_evidence_ids=["selected-target"],
            review_entity_type="error_candidate",
            review_entity_id="selected-review-old",
        ),
        database,
    )
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        for suffix in ("a", "b"):
            target_id = f"selected-target-{suffix}"
            session.add_all(
                [
                    Shot(
                        match=match,
                        prediction_revision=2,
                        prediction_id=target_id,
                        frame_index=4_001,
                        source_timestamp_us=40_010_000,
                        source_evidence_ids=["selected-target"],
                        hitter=PlayerSlot.NEAR,
                        kind=ShotKind.DRIVE,
                        outcome="in_play",
                    ),
                    ErrorCandidate(
                        match=match,
                        prediction_revision=2,
                        prediction_id=f"selected-review-{suffix}",
                        kind=ErrorKind.SHOT,
                        target_type="shot",
                        target_prediction_id=target_id,
                        source_timestamp_us=40_010_000,
                        source_evidence_ids=["selected-review"],
                        evidence_version=1,
                        evidence_payload={},
                        review_status="pending",
                    ),
                ]
            )
    reapply = reapply_corrections(1, 2, database, match_id=match_id)
    assert len(reapply.conflicts) == 1

    report = resolve_conflict(
        match_id,
        reapply.conflicts[0].correction_id,
        ConflictResolution(
            resolution="select",
            candidate_id="selected-target-b",
            expected_report_revision=2,
            reason="selected exact reanalysis target",
        ),
        database,
    )

    assert report.sections["review"].payload["reviewed_count"] == 1
    assert report.sections["review"].payload["pending_ids"] == ["selected-review-a"]
    with database.session() as session:
        selected = session.scalar(
            select(Correction).where(
                Correction.prediction_revision == 2,
                Correction.status == CorrectionStatus.ACTIVE,
            )
        )
        assert selected is not None
        assert selected.target_id == "selected-target-b"
        assert selected.review_entity_type == "error_candidate"
        assert selected.review_entity_id == "selected-review-b"


def test_conflict_candidates_publish_real_shot_frame_anchors() -> None:
    candidate = _conflict_candidate(
        "shot-1",
        {
            "prediction_id": "shot-1",
            "shot_type": "drive",
            "source_timestamp_us": 500_000,
            "frame_index": 15,
            "source_evidence_ids": ["contact-1"],
        },
    )
    assert candidate["evidence_start_timestamp_us"] == 500_000
    assert candidate["evidence_end_timestamp_us"] == 500_000
    assert candidate["evidence_start_frame_index"] == 15
    assert candidate["evidence_end_frame_index"] == 15


def test_reapply_exact_time_conflicts_and_resolution_route(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    correction = apply_correction(
        command(
            match_id,
            source_evidence_ids=["contact-1"],
            source_timestamp_us=500_000,
        ),
        database,
    )
    assert correction.revision == 2
    add_reanalysis_shot(
        database,
        match_id,
        prediction_id="new-shot-exact",
        source_timestamp_us=520_000,
        evidence_ids=["contact-1"],
    )
    exact = reapply_corrections(1, 2, database, match_id=match_id)
    assert exact.reapplied == 1 and exact.conflicts == []

    database_two = make_database(tmp_path / "two")
    match_two = seed_match(database_two)
    build_report(match_two, 1, database_two)
    apply_correction(
        command(
            match_two,
            source_evidence_ids=["contact-1"],
            source_timestamp_us=500_000,
        ),
        database_two,
    )
    add_reanalysis_shot(database_two, match_two, prediction_id="candidate-a", source_timestamp_us=525_000, evidence_ids=["contact-1", "new-a"])
    timed = reapply_corrections(1, 2, database_two, match_id=match_two)
    assert timed.reapplied == 1

    app = create_app(settings)
    app.state.database = database
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        original = session.scalar(select(Correction).where(Correction.match_id == match.id, Correction.status == CorrectionStatus.ACTIVE))
        assert original is not None
        session.add(
            Correction(
                match=match,
                command_type="change_shot_type",
                target_type="shot",
                target_id="missing-shot",
                prediction_revision=1,
                expected_report_revision=2,
                before_payload={},
                after_payload={"shot_type": "drop"},
                reason="conflict fixture",
                source_timestamp_us=9_000_000,
                source_evidence_ids=["missing"],
                status=CorrectionStatus.ACTIVE,
            )
        )
    result = reapply_corrections(1, 2, database, match_id=match_id)
    assert len(result.conflicts) == 1
    conflict_id = result.conflicts[0].correction_id

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listed = await client.get(f"/api/v1/matches/{match_id}/correction-conflicts")
            assert listed.status_code == 200
            assert any(item["correctionId"] == conflict_id for item in listed.json()["conflicts"])
            resolved = await client.post(
                f"/api/v1/matches/{match_id}/correction-conflicts/{conflict_id}/resolve",
                json={"resolution": "reject", "expected_report_revision": 3, "reason": "not present"},
            )
            assert resolved.status_code == 200

    import asyncio

    asyncio.run(exercise())
    with database.session() as session:
        conflict = session.scalar(select(Correction).where(Correction.public_id == conflict_id))
        assert conflict is not None and conflict.status is CorrectionStatus.CONFLICT
        resolution = session.scalar(
            select(Correction).where(Correction.supersedes_correction_id == conflict.id)
        )
        assert resolution is not None and resolution.status is CorrectionStatus.SUPERSEDED


def test_legacy_migration_preserves_corrections_reports_and_unknown_timing(
    tmp_path: Path,
) -> None:
    database = migrate_legacy_database(tmp_path)
    with database.session() as session:
        corrections = session.scalars(select(Correction).order_by(Correction.id)).all()
        rally = session.scalar(select(Rally))
        report_row = session.scalar(select(ReportRevision))
        assert corrections[0].command_type == "accept"
        assert corrections[0].status is CorrectionStatus.ACTIVE
        assert corrections[0].before_payload["legacy_kind"] == "accept"
        assert corrections[1].status is CorrectionStatus.CONFLICT
        assert corrections[1].conflict_details["reason"] == "legacy_unmappable"
        assert corrections[1].before_payload == {
            "legacy_kind": "replace",
            "legacy_replacement_value": "drop",
        }
        assert rally is not None
        assert rally.start_timestamp_us is None and rally.end_timestamp_us is None
        assert rally.timing_available is False
        assert report_row is not None and report_row.schema_version == 0

    report = build_report("00000000-0000-4000-8000-000000000001", 1, database)
    assert set(report.sections) == {
        "overview",
        "shots",
        "rallies",
        "movement",
        "errors",
        "trajectory",
        "head_to_head",
        "coaching",
        "review",
    }
    assert report.sections["overview"].payload["availability"] == {
        "available": False,
        "reason": "legacy_schema_incompatible",
    }


def test_latest_match_calibration_controls_stale_movement(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path="videos/original/calibration.mp4",
        )
        session.add(
            Calibration(
                match=match,
                media_asset=asset,
                revision=2,
                keypoints=[],
                result={},
                confidence=1.0,
                capabilities={},
            )
        )

    report = build_report(match_id, 1, database)
    movement = report.sections["movement"].payload
    assert movement["active_calibration_revision"] == 2
    assert movement["distance_m"] == {
        "available": False,
        "value": None,
        "reason": "no_valid_observed_intervals",
    }
    assert movement["heatmap"]["excluded"]["stale_calibration"] == 4


def test_latest_prediction_revision_uses_every_prediction_table(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            PlayerTrack(
                match=match,
                prediction_revision=2,
                prediction_id="revision-2-track",
                slot=PlayerSlot.NEAR,
                source_timestamp_us=100,
                source_evidence_ids=["revision-2-track"],
                x_m=3.2,
                y_m=5.49,
                observed=True,
                calibration_revision=1,
                position_covariance=[[0.01, 0.0], [0.0, 0.01]],
                position_uncertainty_m=0.1,
                position_provenance="measured",
            )
        )

    report = build_report(match_id, 1, database)
    assert report.prediction_revision == 2
    assert report.sections["shots"].payload["total_count"] == 0
    assert sum(sum(row) for row in report.sections["movement"].payload["heatmap"]["counts"]) == 1


def test_concurrent_initial_report_builders_reload_one_revision(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: build_report(match_id, 1, database), range(2)))

    assert [report.revision for report in reports] == [1, 1]
    with database.session() as session:
        assert session.scalar(select(func.count(ReportRevision.id))) == 1


def test_repeated_splits_use_correction_derived_unique_ids_and_exact_reassignment(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    apply_correction(
        command(
            match_id,
            command_type="split_rally",
            target_id="rally-2",
            payload={"split_timestamp_us": 10_000_000},
        ),
        database,
    )
    first_split = build_report(
        match_id, 2, database
    ).sections["rallies"].payload["items"]
    first_child_id = first_split[2]["prediction_id"]
    apply_correction(
        command(
            match_id,
            command_type="split_rally",
            target_id=first_child_id,
            expected=2,
            payload={"split_timestamp_us": 12_000_000},
        ),
        database,
    )
    report = build_report(match_id, 3, database)
    items = report.sections["rallies"].payload["items"]
    ids = [item["prediction_id"] for item in items]
    with database.session() as session:
        second = session.scalars(select(Correction).order_by(Correction.id)).all()[1]
    assert len(ids) == len(set(ids))
    assert any(second.public_id in prediction_id for prediction_id in ids)
    assigned = [shot_id for item in items for shot_id in item["shot_ids"]]
    assert set(assigned) == {f"shot-{index}" for index in range(1, 13)}


def test_corrected_inputs_change_dependency_hashes_for_movement_dependents(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    first = build_report(match_id, 1, database)
    second = apply_correction(
        command(
            match_id,
            command_type="change_hitter",
            payload={"hitter": "far"},
        ),
        database,
    )
    for name in ("movement", "coaching", "overview", "shots"):
        assert (
            second.sections[name].dependency_hash
            != first.sections[name].dependency_hash
        )


@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("adjust_contact_time", {"source_timestamp_us": True}),
        ("split_rally", {"split_timestamp_us": False}),
        ("ball_control_point", {"x_m": math.nan, "y_m": 1.0}),
        ("ball_control_point", {"x_m": 1.0, "y_m": math.inf}),
    ],
)
def test_numeric_correction_payloads_reject_bool_and_nonfinite(
    command_type: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        command(
            "match",
            command_type=command_type,
            target_id="rally" if command_type == "split_rally" else "shot",
            payload=payload,
        )


def test_nonfinite_trajectory_values_are_explicitly_unavailable(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    with database.session() as session:
        match = Match(name="Nonfinite")
        session.add(
            Shot(
                match=match,
                prediction_revision=1,
                prediction_id="nonfinite-shot",
                frame_index=1,
                source_timestamp_us=1,
                source_evidence_ids=["nonfinite-evidence"],
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.DRIVE,
                outcome="in_play",
                speed_m_s=math.inf,
                contact_x_m=math.inf,
                contact_y_m=1.0,
            )
        )
        session.flush()
        match_id = match.public_id
    report = build_report(match_id, 1, database)
    trajectory = report.sections["trajectory"].payload
    assert trajectory["unavailable_reasons"]["nonfinite_speed"] == 1
    assert trajectory["control_point_exclusions"]["nonfinite_coordinate"] == 1
    assert "NaN" not in report.model_dump_json()


def test_ambiguous_reapply_persists_candidates_and_selects_one_atomically(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    apply_correction(
        command(
            match_id,
            source_evidence_ids=["contact-1"],
            source_timestamp_us=500_000,
        ),
        database,
    )
    add_reanalysis_shot(
        database,
        match_id,
        prediction_id="candidate-one",
        source_timestamp_us=500_000,
        evidence_ids=["contact-1"],
    )
    add_reanalysis_shot(
        database,
        match_id,
        prediction_id="candidate-two",
        source_timestamp_us=500_000,
        evidence_ids=["contact-1"],
    )

    result = reapply_corrections(1, 2, database, match_id=match_id)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].candidate_ids == ["candidate-one", "candidate-two"]
    assert [
        candidate["evidence_start_frame_index"]
        for candidate in result.conflicts[0].candidates
    ] == [50, 50]
    report = resolve_conflict(
        match_id,
        result.conflicts[0].correction_id,
        ConflictResolution(
            resolution="select",
            candidate_id="candidate-two",
            expected_report_revision=2,
            reason="visible contact",
        ),
        database,
    )
    assert report.revision == 3
    with database.session() as session:
        mapped = session.scalar(
            select(Correction).where(
                Correction.target_id == "candidate-two",
                Correction.status == CorrectionStatus.ACTIVE,
            )
        )
        assert mapped is not None and mapped.supersedes_correction_id is not None


def test_stale_conflict_cannot_rewind_current_prediction_revision(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    match_id = seed_match(database)
    build_report(match_id, 1, database)
    apply_correction(
        command(
            match_id,
            source_evidence_ids=["contact-1"],
            source_timestamp_us=500_000,
        ),
        database,
    )
    for prediction_id in ("stale-candidate-one", "stale-candidate-two"):
        add_reanalysis_shot(
            database,
            match_id,
            prediction_id=prediction_id,
            source_timestamp_us=500_000,
            evidence_ids=["contact-1"],
        )
    result = reapply_corrections(1, 2, database, match_id=match_id)
    assert len(result.conflicts) == 1
    conflict_id = result.conflicts[0].correction_id
    assert [
        conflict.correction_id for conflict in list_conflicts(match_id, database)
    ] == [conflict_id]

    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            Shot(
                match=match,
                prediction_revision=3,
                prediction_id="current-revision-three-shot",
                frame_index=51,
                source_timestamp_us=510_000,
                source_evidence_ids=["revision-three"],
                hitter=PlayerSlot.NEAR,
                kind=ShotKind.BOAST,
                outcome="in_play",
            )
        )
    current_report = build_report(match_id, 3, database)
    assert current_report.revision == 3
    stale_conflicts = list_conflicts(match_id, database)
    caught_error: CorrectionConflict | None = None
    try:
        resolve_conflict(
            match_id,
            conflict_id,
            ConflictResolution(
                resolution="select",
                candidate_id="stale-candidate-two",
                expected_report_revision=current_report.revision,
                reason="visible contact",
            ),
            database,
        )
    except CorrectionConflict as error:
        caught_error = error

    with database.session() as session:
        conflict = session.scalar(
            select(Correction).where(Correction.public_id == conflict_id)
        )
        assert conflict is not None
        assert conflict.status is CorrectionStatus.CONFLICT
        latest = session.scalar(
            select(ReportRevision).order_by(ReportRevision.revision.desc())
        )
        assert latest is not None
        assert latest.revision == current_report.revision
        assert latest.prediction_revision == 3
        assert session.scalar(
            select(Correction).where(
                Correction.supersedes_correction_id == conflict.id
            )
        ) is None
    assert stale_conflicts == []
    assert caught_error is not None
    assert caught_error.status_code == 409
    assert "stale" in caught_error.message
    assert "reload" in caught_error.message
