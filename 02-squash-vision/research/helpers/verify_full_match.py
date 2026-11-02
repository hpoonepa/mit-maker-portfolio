"""Run the complete 1,249-second local broadcast through the actual durable pipeline.

This isolated run verifies long-video mechanics. Its changing camera angles do not
meet the fixed-camera recording requirement for reliable court/player statistics.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import zipfile

from fastapi.testclient import TestClient
import torch
from sqlalchemy import select

from squashvision.app import create_app
from squashvision.models import AnalysisJob, JobChunk
from squashvision.pipeline import AnalysisPipeline
from squashvision.settings import Settings
from squashvision.worker import Worker
import prepare_demo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "fullmatch-data"
EVIDENCE = ROOT / "fullmatch-verification"
EVIDENCE.mkdir(exist_ok=True)
SOURCE = ROOT / "source-match.mp4"
STATE = EVIDENCE / "progress.json"
os.environ["YOLO_CONFIG_DIR"] = str(ROOT / "yolo-config")


def save(value):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(STATE)


def checked(response):
    if not response.is_success:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code}: {response.text[:1000]}")
    return response.json()


state = json.loads(STATE.read_text()) if STATE.exists() else {
    "status": "preparing", "source": str(SOURCE), "durationSeconds": 1249,
    "purpose": "Full broadcast pipeline verification; changing angles prevent accuracy claims.",
    "staticPlayerRoiApplied": False, "mpsAvailable": torch.backends.mps.is_available(),
    "startedAtEpochSeconds": time.time(),
}
save(state)
if "matchId" not in state:
    prepare_demo.DATA = DATA
    prepare_demo.seed_cached_models()
app = create_app(Settings(data_dir=DATA))
with TestClient(app) as client:
    if "matchId" not in state:
        print("Preparing all 1,249 seconds of the original recording", flush=True)
        with SOURCE.open("rb") as video:
            match = checked(client.post("/api/v1/matches", data={"title": "Full broadcast · 20:49 pipeline verification"},
                files={"video": ("ElShorbagy v Farag Free Game.mp4", video, "video/mp4")}))
        state["matchId"] = match["id"]
        state["ingestWallSeconds"] = time.time() - state["startedAtEpochSeconds"]
        save(state)
    if "jobId" not in state:
        job = checked(client.post(f"/api/v1/matches/{state['matchId']}/jobs", json={"profile": "maximum"}))
        state["jobId"] = job["id"]
        state["analysisStartedAtEpochSeconds"] = time.time()
        save(state)
    current = checked(client.get(f"/api/v1/jobs/{state['jobId']}"))
    if current["state"] == "failed":
        checked(client.post(f"/api/v1/jobs/{state['jobId']}/retry"))
    elif current["state"] == "paused":
        state.setdefault("resumes", []).append({"atEpochSeconds": time.time(),
            "completedChunks": current["progress"]["completedChunks"],
            "reason": "Resume compatible720p checkpoints with bounded streaming decode"})
        checked(client.post(f"/api/v1/jobs/{state['jobId']}/resume"))
        save(state)
    worker = Worker(app.state.job_queue, "full-match-verification-mps",
        AnalysisPipeline(storage_root=app.state.storage.root, database=app.state.database,
                         model_manifest=app.state.model_manifest))
    while True:
        current = checked(client.get(f"/api/v1/jobs/{state['jobId']}"))
        state.update(status=current["state"], job=current,
                     analysisElapsedSeconds=time.time() - state["analysisStartedAtEpochSeconds"])
        save(state)
        print(json.dumps({"seconds": round(state["analysisElapsedSeconds"], 1),
                          "state": current["state"], "stage": current["stage"],
                          "rangeStartUs": current["currentRangeStartUs"],
                          "rangeEndUs": current["currentRangeEndUs"],
                          "progress": current["progress"]}), flush=True)
        if current["state"] == "paused":
            print("Paused at a verified chunk boundary", flush=True)
            raise SystemExit(0)
        if current["state"] in {"completed", "failed", "cancelled"}:
            if current["state"] != "completed":
                raise RuntimeError(current)
            break
        try:
            worker.run_once()
        except BaseException as error:
            current = checked(client.get(f"/api/v1/jobs/{state['jobId']}"))
            state.update(status=current["state"], job=current,
                         analysisElapsedSeconds=time.time() - state["analysisStartedAtEpochSeconds"],
                         verificationError=f"{type(error).__name__}: {error}")
            save(state)
            raise
    report = checked(client.get(f"/api/v1/matches/{state['matchId']}/reports/latest"))
    (EVIDENCE / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    state["reportRevision"] = report["revision"]
    state["observationWindows"] = {}
    for start in (0, 58_000_000, 116_000_000, 600_000_000, 1_219_000_000):
        end = min(start + 30_000_000, 1_249_000_000)
        for kind in ("players", "ball"):
            rows = []
            cursor = None
            pages = 0
            while True:
                parameters = {"startUs": start, "endUs": end, "revision": report["revision"], "limit": 500}
                if cursor:
                    parameters["cursor"] = cursor
                page = checked(client.get(f"/api/v1/matches/{state['matchId']}/observations/{kind}", params=parameters))
                rows.extend(page["items"])
                pages += 1
                cursor = page["nextCursor"]
                if cursor is None:
                    break
            keys = [(row.get("playerId"), row["timestampUs"]) for row in rows]
            assert len(keys) == len(set(keys))
            state["observationWindows"][f"{kind}:{start}-{end}"] = {"rows": len(rows), "pages": pages, "duplicates": 0}
    export = checked(client.post(f"/api/v1/matches/{state['matchId']}/exports", json={
        "revision": report["revision"], "selection": {"formats": ["html", "json", "csv"]}}))
    download = client.get(f"/api/v1/matches/{state['matchId']}/exports/{export['id']}/download")
    download.raise_for_status()
    assert hashlib.sha256(download.content).hexdigest() == export["sha256"]
    (EVIDENCE / "full-match-report.zip").write_bytes(download.content)
    state["export"] = export
    state["exportChecksumVerified"] = True
    with app.state.database.session() as session:
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.public_id == state["jobId"]))
        chunks = session.scalars(select(JobChunk).where(JobChunk.analysis_job_id == job.id).order_by(JobChunk.chunk_index)).all()
        state["chunks"] = [{"stage": row.stage.value, "state": row.status.value,
                            "startUs": row.start_us, "endUs": row.end_us} for row in chunks]
    state["status"] = "verified"
    state.pop("verificationError", None)
    save(state)
    print("FULL MATCH VERIFIED", flush=True)
