"""Re-run real inference with the reviewed image mask, preserving report revision 1."""
import json
import time

from fastapi.testclient import TestClient

from squashvision.app import create_app
from squashvision.pipeline import AnalysisPipeline
from squashvision.settings import Settings
from squashvision.worker import Worker
from prepare_demo import DATA, EVIDENCE, checked, collect, save

manifest = json.loads((EVIDENCE / "demo.json").read_text())
app = create_app(Settings(data_dir=DATA))
with TestClient(app) as client:
    match_id = manifest["matchId"]
    original = checked(client.get(f"/api/v1/matches/{match_id}/reports/1"))
    save("report-before-roi.json", original)
    current = checked(client.get(f"/api/v1/matches/{match_id}/player-roi"))
    if current["points"] is None:
        region = checked(client.put(f"/api/v1/matches/{match_id}/player-roi", json={
            "expectedRevision": current["revision"], "sourceSha256": current["sourceSha256"],
            "frameSize": current["frameSize"],
            "points": [{"x": x, "y": y} for x, y in [(374, 384), (902, 384), (1075, 719), (202, 719)]],
        }))
    else:
        region = current
    save("player-roi.json", region)
    if "roiJobId" not in manifest:
        job = checked(client.post(f"/api/v1/matches/{match_id}/reanalyze", json={"profile": "maximum"}))
        manifest["previousJobId"] = manifest["jobId"]
        manifest["jobId"] = manifest["roiJobId"] = job["id"]
        save("demo.json", manifest)
    worker = Worker(app.state.job_queue, "portfolio-reviewed-image-roi",
        AnalysisPipeline(storage_root=app.state.storage.root, database=app.state.database,
                         model_manifest=app.state.model_manifest))
    existing = checked(client.get(f"/api/v1/jobs/{manifest['roiJobId']}"))
    if existing["state"] == "failed":
        checked(client.post(f"/api/v1/jobs/{manifest['roiJobId']}/retry"))
    started = time.monotonic()
    while True:
        snapshot = checked(client.get(f"/api/v1/jobs/{manifest['roiJobId']}"))
        save("roi-job.json", snapshot)
        print(json.dumps({"seconds": round(time.monotonic()-started, 2), "state": snapshot["state"],
                          "stage": snapshot["stage"], "progress": snapshot["progress"]}), flush=True)
        if snapshot["state"] in {"completed", "failed", "cancelled"}:
            assert snapshot["state"] == "completed", snapshot
            break
        worker.run_once()
    assert checked(client.get(f"/api/v1/matches/{match_id}/reports/1")) == original
    manifest["roiReanalysisWallSeconds"] = round(time.monotonic()-started, 2)
    manifest["playerRoi"] = region
    manifest["originalReportRevisionPreserved"] = True
    save("demo.json", manifest)
collect(manifest)
