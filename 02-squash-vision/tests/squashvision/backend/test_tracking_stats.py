from __future__ import annotations

import hashlib
import json
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from squashvision.app import create_app
from squashvision.models import AnalysisJob, AssetKind, Calibration, JobChunk, JobStatus, Match, MediaAsset, ProcessingProfile, ReportRevision, Stage, StagePublication, StageStatus
from squashvision.settings import Settings
from squashvision.tracking_stats import FloorProjection, ball_speed_stats, contact_stats, movement_stats, court_scaled_image_speed_intervals

PROJECTION = FloorProjection(((.01, 0, 0), (0, .01, 0), (0, 0, 1)))

def test_live_speed_rejects_reacquisition_jump_and_changed_source_manifest():
    jump = [ball_row(0), ball_row(1, x=630, y=940), ball_row(2, x=620, y=930)]
    intervals = court_scaled_image_speed_intervals(jump, PROJECTION)
    assert len(intervals) == 1
    assert intervals[0][0]["source_frame_index"] == 1
    changed = [ball_row(0, source_manifest_id="a"), ball_row(1, source_manifest_id="b")]
    assert court_scaled_image_speed_intervals(changed, PROJECTION) == []


def player_row(frame, *, player="A", x=None, **changes):
    return {"player_id": player, "timestamp_us": frame*40_000, "source_timestamp_us": frame*40_000,
            "source_frame_index": frame, "feet_x": 100+frame*4 if x is None else x,
            "feet_y": 300., "feet_uncertainty_px": 1., "evidence": "observed",
            "ambiguous": False, "association_confidence": .9, **changes}


def ball_row(frame, **changes):
    return {"timestamp_us": frame*40_000, "source_timestamp_us": frame*40_000,
            "source_frame_index": frame, "source_width": 640, "source_height": 975,
            "x": 100+frame*20., "y": 300., "visible": True, "evidence": "observed",
            "probability": .9, "candidate_count": 1, "ambiguous": False, "segment_id": "s1", **changes}


def event(timestamp=400_000, hitter="A"):
    return {"contact_id": "contact-1", "timestamp_us": timestamp, "selected_type": "racket",
            "selected_hitter": hitter, "hitter_probabilities": {"A": .8, "B": .1, "unknown": .1},
            "confidence": .75, "review_required": True}


def test_movement_measures_known_path_and_real_stationary_zero():
    rows = [player_row(i) for i in range(26)] + [player_row(i, player="B", x=200.) for i in range(26)]
    a, b = movement_stats(rows, PROJECTION, 1_000_000, Counter(A=1))
    assert a.distance_m == pytest.approx(1)
    assert a.tracked_seconds == pytest.approx(1)
    assert a.coverage == pytest.approx(1)
    assert b.distance_m == 0
    assert a.contact_count == 1 and not a.identity_verified


def test_movement_does_not_bridge_occlusion_ambiguous_or_identity_jump():
    rows = [player_row(0), player_row(1), player_row(2, ambiguous=True),
            player_row(3, x=600), player_row(4, x=604), player_row(25, x=100),
            player_row(26, x=600)]
    a, _ = movement_stats(rows, PROJECTION, 1_040_000, Counter())
    assert a.distance_m == pytest.approx(.08)
    assert a.tracked_seconds == pytest.approx(.08)
    assert a.excluded_samples == 1
    assert a.coverage < .1


def test_floor_projection_scales_source_dimensions_and_rejects_unreliable_points():
    doubled_source = FloorProjection(PROJECTION.matrix, .5, .5)
    assert doubled_source.point(200, 600) == pytest.approx((1, 3))
    assert PROJECTION.point(-1, 300) is None
    assert PROJECTION.point(100, float("nan")) is None
    assert PROJECTION.point(100, 300, 1000) is None


def test_ball_speed_known_5_mps_and_no_interpolated_or_gap_bridge():
    rows = [ball_row(i) for i in range(10)]
    result = ball_speed_stats(rows, PROJECTION, 400_000)
    assert result.median_mps == pytest.approx(5)
    assert result.p90_mps == pytest.approx(5)
    assert result.sample_count == 9
    broken = [ball_row(0), ball_row(1, evidence="interpolated"), ball_row(2), ball_row(4)]
    assert ball_speed_stats(broken, PROJECTION, 400_000).median_mps is None
    assert ball_speed_stats(rows, None, 400_000).reason == "calibration_unavailable"


def test_contacts_preserve_unknown_and_seek_exact_proxy_frame():
    rows = [player_row(10)]
    contacts = contact_stats([event(), {**event(hitter="unknown"), "contact_id": "unknown"}],
                             rows, [ball_row(10)], PROJECTION, {10: 366667})
    assert contacts[0].position == pytest.approx((1.4, 3))
    assert contacts[0].proxy_timestamp_us == 366667
    assert contacts[0].timestamp_us == 400000
    assert contacts[1].hitter is None and contacts[1].position is None
    assert contacts[1].reason == "unknown_hitter"


@pytest.fixture
def stats_client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    storage_root = app.state.storage.root
    with app.state.database.session() as session:
        match = Match(name="Known metric paths")
        source = MediaAsset(match=match, kind=AssetKind.ORIGINAL, relative_path="videos/original/test.mp4",
                            probe_metadata={"width":640, "height":975, "rotation":0})
        proxy = MediaAsset(match=match, kind=AssetKind.PROXY, relative_path="videos/proxy/test.mp4", duration_us=1_040_000)
        session.add_all([source, proxy]); session.flush()
        calibration = Calibration(match=match, media_asset=proxy, revision=1, frame_width=640, frame_height=975,
            keypoints=[], result={"calibrated":True, "imageToCourt":PROJECTION.matrix}, confidence=.9,
            capabilities={"floorPosition":True, "movementDistance":True})
        job = AnalysisJob(match=match, source_media_asset=source, processing_profile=ProcessingProfile.BALANCED, status=JobStatus.COMPLETED)
        session.add_all([calibration, job]); session.flush()
        session.add(StagePublication(match_id=match.id, analysis_job_id=job.id, stage=Stage.CLASSIFICATION,
            input_hash="a"*64, worker_id="test", claim_token="test", prediction_revision=2))
        session.add(ReportRevision(match=match, revision=2, prediction_revision=2, sections={}, section_hashes={}, dependency_hashes={}))
        for chunk_index, (stage, payload) in enumerate([(Stage.PLAYERS,[player_row(i) for i in range(26)]),
                               (Stage.BALL,[ball_row(i) for i in range(10)]),
                               (Stage.EVENTS,{"contacts":[event(320_000)]})]):
            relative = f"checkpoints/test/{stage.value}." + ("json" if stage==Stage.EVENTS else "parquet")
            path = storage_root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            if stage==Stage.EVENTS:
                path.write_text(json.dumps(payload))
            else:
                pq.write_table(pa.Table.from_pylist(payload), path)
            data = path.read_bytes()
            session.add(JobChunk(analysis_job_id=job.id, chunk_index=chunk_index, stage=stage, start_us=0, end_us=1_000_001,
                status=StageStatus.COMPLETED, artifact_payload_path=relative, artifact_payload_size=len(data),
                artifact_payload_sha256=hashlib.sha256(data).hexdigest()))
        index = app.state.storage.allocate_timestamp_index()
        pq.write_table(pa.table({"proxy_timestamp_us":[round(k*1_000_000/30) for k in range(32)],
                                "source_frame_index":[round(k*25/30) for k in range(32)]}), index.absolute)
        data = index.absolute.read_bytes()
        proxy.timestamp_index_path=str(index.relative); proxy.timestamp_index_size=len(data)
        proxy.timestamp_index_sha256=hashlib.sha256(data).hexdigest()
        match_id = match.public_id
    with TestClient(app) as client:
        yield client, app, match_id


def test_stats_api_uses_selected_publication_and_exact_proxy_time(stats_client):
    client, app, match_id = stats_client
    response = client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["reportRevision"] == 2 and data["predictionRevision"] == 2
    assert data["calibrationRevision"] == 1 and data["calibrationAvailable"]
    assert data["players"][0]["distanceM"] == pytest.approx(1)
    assert data["ballSpeed"]["medianMps"] == pytest.approx(5)
    assert data["contacts"][0]["proxyTimestampUs"] == 300000
    assert data["contacts"][0]["timestampUs"] == 320000
    # Saving a new calibration may invalidate chunks; the selected report stays readable.
    with app.state.database.session() as session:
        for chunk in session.scalars(select(JobChunk)):
            chunk.status=StageStatus.INVALIDATED
    assert client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats").status_code == 200


def test_stats_api_no_calibration_returns_unavailable_not_fabricated_zero(stats_client):
    client, app, match_id = stats_client
    with app.state.database.session() as session:
        session.delete(session.scalar(select(Calibration)))
    response = client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 200, response.text
    data=response.json()
    assert not data["calibrationAvailable"] and data["calibrationRevision"] is None
    assert data["players"][0]["distanceM"] is None
    assert data["ballSpeed"]["medianMps"] is None
    assert data["contacts"][0]["position"] is None


def test_stats_uses_actual_inference_image_dimensions_for_high_resolution_source(stats_client):
    client, app, match_id = stats_client
    with app.state.database.session() as session:
        source=session.scalar(select(MediaAsset).where(MediaAsset.kind==AssetKind.ORIGINAL))
        source.probe_metadata={"width":3840, "height":2160, "rotation":90}
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 200, response.text
    # Saved rows remain 640×975 inference pixels, even when source metadata is 4K/rotated.
    assert response.json()["players"][0]["distanceM"] == pytest.approx(1)
    assert response.json()["ballSpeed"]["medianMps"] == pytest.approx(5)


def test_player_only_balanced_report_uses_saved_proxy_calibration_dimensions(stats_client):
    client, app, match_id = stats_client
    with app.state.database.session() as session:
        source=session.scalar(select(MediaAsset).where(MediaAsset.kind==AssetKind.ORIGINAL))
        source.probe_metadata={"width":3840, "height":2160, "rotation":90}
        session.delete(session.scalar(select(JobChunk).where(JobChunk.stage==Stage.BALL)))
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 200, response.text
    assert response.json()["calibrationAvailable"]
    assert response.json()["players"][0]["distanceM"] == pytest.approx(1)
    assert response.json()["ballSpeed"]["medianMps"] is None


def test_historical_high_resolution_maximum_player_only_report_does_not_guess_pixel_space(stats_client):
    client, app, match_id = stats_client
    with app.state.database.session() as session:
        source=session.scalar(select(MediaAsset).where(MediaAsset.kind==AssetKind.ORIGINAL))
        source.probe_metadata={"width":3840, "height":2160, "rotation":0}
        session.scalar(select(AnalysisJob)).processing_profile=ProcessingProfile.MAXIMUM
        session.delete(session.scalar(select(JobChunk).where(JobChunk.stage==Stage.BALL)))
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 200, response.text
    assert not response.json()["calibrationAvailable"]
    assert response.json()["players"][0]["distanceM"] is None


@pytest.mark.parametrize("suffix", ["/reports/99/tracking-stats", "/reports/2/tracking-stats?calibrationRevision=99"])
def test_stats_api_missing_revision_does_not_fall_back(stats_client, suffix):
    client, _, match_id = stats_client
    assert client.get(f"/api/v1/matches/{match_id}{suffix}").status_code == 404


def test_stats_api_rejects_corrupt_observation_file(stats_client):
    client, app, match_id = stats_client
    with app.state.database.session() as session:
        chunk=session.scalar(select(JobChunk).where(JobChunk.stage==Stage.PLAYERS))
        (app.state.storage.root/chunk.artifact_payload_path).write_bytes(b"tampered")
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats")
    assert response.status_code == 409
    assert response.json()["code"] == "tracking_stats_artifact_invalid"


def test_temporal_movement_is_progressive_matches_totals_and_keeps_window_baseline(stats_client, monkeypatch):
    import squashvision.routes.tracking_stats as routes
    monkeypatch.setattr(routes, "_derive_impacts", lambda *args: [])
    client, _, match_id = stats_client
    url=f"/api/v1/matches/{match_id}/reports/2/tracking-timeline"
    data=client.get(url, params={"startUs":0,"endUs":1_000_001}).json()
    a=[row for row in data["playerSamples"] if row["playerId"]=="A"]
    assert a[0]["cumulativeDistanceM"] is None
    assert a[5]["cumulativeDistanceM"] == pytest.approx(.2)
    assert a[-1]["cumulativeDistanceM"] == pytest.approx(1)
    assert all(r["timestampUs"]<1_000_001 for r in a)
    totals=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-stats").json()
    assert a[-1]["cumulativeDistanceM"] == totals["players"][0]["distanceM"]
    later=client.get(url,params={"startUs":600_000,"endUs":1_000_001}).json()
    assert later["players"][0]["baselineDistanceM"] == pytest.approx(.4)
    assert later["playerSamples"][0]["cumulativeDistanceM"] == pytest.approx(.6)
    assert later["playerSamples"][0]["timestampUs"]==600_000


def test_temporal_speed_ends_at_current_source_frame_with_exact_display_expiry(stats_client, monkeypatch):
    import squashvision.routes.tracking_stats as routes
    monkeypatch.setattr(routes, "_derive_impacts", lambda *args: [])
    client, _, match_id=stats_client
    data=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline").json()
    assert data["ballSpeedMethod"]=="court_scaled_image_speed"
    frame=next(item for item in data["ballSpeeds"] if item["sourceFrameIndex"]==8)
    assert frame["timestampUs"]==320_000 and frame["intervalStartUs"]==280_000
    assert frame["proxyTimestampUs"]==300_000
    assert frame["proxyEndTimestampUs"]==366_667
    assert frame["speedMps"] == pytest.approx(5)
    assert max(s["timestampUs"] for s in data["ballSpeeds"]) == 360_000


def test_temporal_ball_floor_and_wall_impacts_never_use_player_feet_as_ball_position(stats_client, monkeypatch):
    import squashvision.routes.tracking_stats as routes
    impacts=[{"id":"racket", "timestamp_us":320000,"kind":"racket","hitter":"A",
              "ball_image_position":[260,300],"floor_position":[4,5],"confidence":.8},
             {"id":"floor", "timestamp_us":360000,"kind":"floor","hitter":None,
              "ball_image_position":[280,300],"floor_position":[2.8,3],"confidence":.8},
             {"id":"wall", "timestamp_us":280000,"kind":"front_wall","hitter":None,
              "ball_image_position":[240,300],"floor_position":[4,5],"confidence":.7}]
    monkeypatch.setattr(routes, "_derive_impacts", lambda *args: impacts)
    client, _, match_id=stats_client
    data=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline").json()
    contacts={c["id"]:c for c in data["contacts"]}
    assert contacts["racket"]["playerPosition"] == pytest.approx([1.32,3])
    assert contacts["racket"]["ballImagePosition"] == [260,300]
    assert contacts["racket"]["floorPosition"] is None
    assert contacts["floor"]["floorPosition"] == [2.8,3]
    assert contacts["floor"]["playerPosition"] is None
    assert contacts["wall"]["floorPosition"] is None
    assert contacts["wall"]["wallPosition"] is None
    assert data["landingCount"]==1
    assert all(c["reviewRequired"] for c in contacts.values())


@pytest.mark.parametrize("params", [{"startUs":5,"endUs":5},{"startUs":0,"endUs":120000001},{"startUs":-1,"endUs":10}])
def test_temporal_api_rejects_invalid_or_unbounded_windows(stats_client, params):
    client, _, match_id=stats_client
    assert client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline",params=params).status_code==422


def test_temporal_api_missing_calibration_preserves_image_contacts_but_no_metric_positions(stats_client,monkeypatch):
    import squashvision.routes.tracking_stats as routes
    monkeypatch.setattr(routes,"_derive_impacts",lambda *args:[{"id":"floor","timestamp_us":320000,"kind":"floor","ball_image_position":[260,300],"floor_position":[2.6,3]}])
    client,app,match_id=stats_client
    with app.state.database.session() as session:session.delete(session.scalar(select(Calibration)))
    data=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline").json()
    assert data["contacts"][0]["ballImagePosition"]==[260,300]
    assert data["contacts"][0]["floorPosition"] is None
    assert data["landingCount"]==0 and data["landingReason"]
    assert data["ballSpeeds"]==[]
    assert all(s["cumulativeDistanceM"] is None for s in data["playerSamples"])


def test_temporal_endpoint_integrates_real_detector_without_inventing_impacts_in_constant_motion(stats_client):
    client, _, match_id=stats_client
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline")
    assert response.status_code==200, response.text
    data=response.json()
    assert data["playerSamples"] and data["ballSpeeds"]
    assert data["contacts"]==[] and data["landingCount"]==0
    assert data["landingReason"]


def _perspective_projection(scale=1):
    import numpy as np
    # Front edge (300,200)–(700,200), rear edge (100,800)–(900,800).
    court_to_image=np.array([[62.5,-250/9.75,300],[0,200/9.75,200],[0,-.5/9.75,1.]])
    return FloorProjection(tuple(tuple(v for v in row) for row in np.linalg.inv(court_to_image)),scale,scale)


@pytest.mark.parametrize("image_y,expected",[(100.,16.),(500.,6.4/.6),(900.,8.)])
def test_live_2d_speed_uses_known_local_court_width_and_clamps_airborne_and_rear_y(image_y,expected):
    rows=[ball_row(0,x=400.,y=image_y,source_width=1000,source_height=1000),
          ball_row(1,x=440.,y=image_y,source_width=1000,source_height=1000)]
    intervals=court_scaled_image_speed_intervals(rows,_perspective_projection())
    assert len(intervals)==1 and intervals[0][2]==pytest.approx(expected)
    if image_y==100:
        # Live image speed is available above the floor; old static metric stays unchanged.
        assert ball_speed_stats(rows,_perspective_projection(),80_000).median_mps is None


def test_live_2d_speed_preserves_scale_for_larger_inference_image():
    rows=[ball_row(0,x=800.,y=200.,source_width=2000,source_height=2000),
          ball_row(1,x=880.,y=200.,source_width=2000,source_height=2000)]
    assert court_scaled_image_speed_intervals(rows,_perspective_projection(.5))[0][2]==pytest.approx(16)


def test_live_2d_speed_never_bridges_missing_ambiguous_or_interpolated_frames():
    assert len(court_scaled_image_speed_intervals([ball_row(0),ball_row(1),ball_row(4)],PROJECTION))==1
    rows=[ball_row(0),ball_row(1,ambiguous=True),ball_row(2),ball_row(4),ball_row(5,evidence="interpolated"),ball_row(6,probability=.1),ball_row(7,candidate_count=2)]
    assert court_scaled_image_speed_intervals(rows,PROJECTION)==[]
    assert court_scaled_image_speed_intervals([ball_row(0),ball_row(1)],None)==[]


def _impact(frame,kind,hitter=None,identifier=None):
    return {"id":identifier or f"{kind}-{frame}","timestamp_us":frame*40_000,
            "kind":kind,"hitter":hitter,"hitter_confidence":.8 if hitter else 0.,
            "confidence":.7,"ball_image_position":[100+frame,300]}


def test_shot_attribution_uses_only_prior_supported_racket_and_does_not_mutate_events():
    from squashvision.tracking_timeline import attribute_shot_impacts
    rows=[ball_row(i,x=100+i) for i in range(10)]
    events=[_impact(1,"floor"),_impact(3,"racket","A","hit-a"),_impact(5,"front_wall"),_impact(7,"floor")]
    output=attribute_shot_impacts(list(reversed(events)),rows)
    assert output[0]["shot_hitter"] is None
    assert all(e["shot_hitter"]=="A" and e["shot_contact_id"]=="hit-a" and e["shot_hitter_confidence"]==.8 for e in output[1:])
    assert all("shot_hitter" not in event for event in events)


@pytest.mark.parametrize("interruption",["racket","unknown"])
def test_unknown_racket_or_impact_clears_prior_shot_owner(interruption):
    from squashvision.tracking_timeline import attribute_shot_impacts
    rows=[ball_row(i,x=100+i) for i in range(10)]
    output=attribute_shot_impacts([_impact(0,"racket","A"),_impact(2,interruption),_impact(3,"floor"),_impact(5,"racket","B"),_impact(7,"front_wall")],rows)
    assert output[2]["shot_hitter"] is None and output[2]["shot_contact_id"] is None
    assert output[4]["shot_hitter"]=="B"


@pytest.mark.parametrize("break_kind",["missing","interpolated","jump","long_shot"])
def test_shot_owner_expires_across_observation_gaps_jumps_or_long_shots(break_kind):
    from squashvision.tracking_timeline import attribute_shot_impacts
    rows=[ball_row(i,x=100+i) for i in range(101)]
    target=8
    if break_kind=="missing": rows=[r for r in rows if not 1<=r["source_frame_index"]<=7]
    elif break_kind=="interpolated":
        for row in rows[1:8]: row["evidence"]="interpolated"
    elif break_kind=="jump": rows[4]["x"]=600
    else: target=80
    result=attribute_shot_impacts([_impact(0,"racket","A"),_impact(target,"floor")],rows)
    assert result[0]["shot_hitter"]=="A"
    assert result[1]["shot_hitter"] is None and result[1]["shot_contact_id"] is None
    assert result[1]["shot_hitter_confidence"]==0


def test_timeline_window_inherits_shot_from_before_window(stats_client,monkeypatch):
    import squashvision.routes.tracking_stats as routes
    def impacts(players,ball,*args):
        assert min(r["timestamp_us"] for r in players)==0
        return [_impact(4,"racket","A","earlier-hit"),{**_impact(8,"floor"),"floor_position":[2.6,3]}]
    monkeypatch.setattr(routes,"_derive_impacts",impacts)
    client,_,match_id=stats_client
    response=client.get(f"/api/v1/matches/{match_id}/reports/2/tracking-timeline",params={"startUs":300_000,"endUs":400_000})
    assert response.status_code==200,response.text
    contacts=response.json()["contacts"]
    assert len(contacts)==1 and contacts[0]["kind"]=="floor"
    assert contacts[0]["hitter"] is None
    assert contacts[0]["shotHitter"]=="A" and contacts[0]["shotContactId"]=="earlier-hit"
    assert contacts[0]["shotHitterConfidence"]==.8


@pytest.mark.parametrize("reverse",[False,True])
def test_overlap_stats_dedup_prefers_observed_to_higher_confidence_interpolation(stats_client,reverse):
    from types import SimpleNamespace
    import squashvision.routes.tracking_stats as routes
    _,app,_=stats_client
    observed=player_row(3)
    interpolated={**observed,"evidence":"interpolated","source_timestamp_us":None,
                  "source_frame_index":None,"association_confidence":1.,"feet_x":900.}
    chunks=[]
    for index,row in enumerate([observed,interpolated]):
        relative=f"checkpoints/test/overlap-{index}.parquet"
        path=app.state.storage.root/relative
        pq.write_table(pa.Table.from_pylist([row]),path)
        data=path.read_bytes()
        chunks.append(SimpleNamespace(artifact_payload_path=relative,artifact_payload_size=len(data),artifact_payload_sha256=hashlib.sha256(data).hexdigest()))
    rows=routes._rows(app.state.storage,list(reversed(chunks)) if reverse else chunks,routes._PLAYER_COLUMNS)
    assert len(rows)==1 and rows[0]["evidence"]=="observed"
    assert rows[0]["source_frame_index"]==3 and rows[0]["feet_x"]==observed["feet_x"]
