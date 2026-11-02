import pytest
from test_tracking_stats import stats_client

def shot(**patch):
    return {"id":"review-1", "contactUs":100000, "hitter":"A", "type":"drive", "origin":"reviewed", "confidence":1,
        "contactImage":[.3,.4], "playerPosition":[1,5], "opponentPosition":None,
        "wall":None, "landing":{"timeUs":900000,"image":None,"position":[.2,7.5]},"notes":"Tight length",**patch}

def test_review_round_trip_preserves_original_report_and_conflicts(stats_client):
    client, app, mid = stats_client
    path=f"/api/v1/matches/{mid}/reports/2/shot-review"
    first=client.get(path)
    assert first.status_code==200, first.text
    assert first.json()=={"version":0,"reportRevision":2,"shots":[],"wallCalibration":None}
    payload={"expectedVersion":0,"shots":[shot()],"wallCalibration":None}
    saved=client.put(path,json=payload,headers={"Origin":"http://127.0.0.1:8765"})
    assert saved.status_code==200, saved.text
    assert saved.json()["version"]==1
    assert client.get(path).json()["shots"][0]["notes"]=="Tight length"
    assert client.put(path,json=payload,headers={"Origin":"http://127.0.0.1:8765"}).status_code==409
    assert client.get(path).json()["version"]==1
    assert client.get(f"/api/v1/matches/{mid}/reports/999/shot-review").status_code==404

@pytest.mark.parametrize("changes",[
    {"contactImage":[2,.5]}, {"playerPosition":[7,4]},
    {"contactUs":2000000}, {"landing":{"timeUs":50000,"image":None,"position":[1,2]}},
    {"notes":"x"*1001}, {"id":"../outside"},
])
def test_review_rejects_invalid_geometry_times_and_fields(stats_client,changes):
    client,app,mid=stats_client
    result=client.put(f"/api/v1/matches/{mid}/reports/2/shot-review",json={"expectedVersion":0,"shots":[shot(**changes)],"wallCalibration":None},headers={"Origin":"http://127.0.0.1:8765"})
    assert result.status_code==422,result.text

def test_review_rejects_duplicate_ids_and_invalid_calibration(stats_client):
    client,app,mid=stats_client
    path=f"/api/v1/matches/{mid}/reports/2/shot-review"
    headers={"Origin":"http://127.0.0.1:8765"}
    assert client.put(path,json={"expectedVersion":0,"shots":[shot(),shot()],"wallCalibration":None},headers=headers).status_code==422
    assert client.put(path,json={"expectedVersion":0,"shots":[],"wallCalibration":{"points":[[0,0],[1,1],[0,1],[1,0]],"tinHeightM":.48}},headers=headers).status_code==422

def test_review_updates_version_and_keeps_saved_history(stats_client):
    client,app,mid=stats_client
    path=f"/api/v1/matches/{mid}/reports/2/shot-review"
    headers={"Origin":"http://127.0.0.1:8765"}
    assert client.put(path,json={"expectedVersion":0,"shots":[shot()],"wallCalibration":None},headers=headers).status_code==200
    result=client.put(path,json={"expectedVersion":1,"shots":[shot(notes="Corrected")],"wallCalibration":None},headers=headers)
    assert result.json()["version"]==2
    import sqlite3
    with sqlite3.connect(app.state.settings.data_dir/"shot-reviews.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM shot_reviews").fetchone()[0]==2

def test_review_accepts_distinct_crosscourt_type(stats_client):
    client,app,mid=stats_client
    response=client.put(f"/api/v1/matches/{mid}/reports/2/shot-review",json={"expectedVersion":0,"shots":[shot(type="crosscourt")],"wallCalibration":None},headers={"Origin":"http://127.0.0.1:8765"})
    assert response.status_code==200,response.text
    assert response.json()["shots"][0]["type"]=="crosscourt"
