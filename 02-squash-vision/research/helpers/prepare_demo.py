"""Prepare an isolated, reproducible demo using real local footage and cached weights.

No model downloads, fabricated observations, or writes to the installed app data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from squashvision.app import create_app
from squashvision.db import Database
from squashvision.media import probe_video, resolve_ffmpeg_binary
from squashvision.pipeline import AnalysisPipeline
from squashvision.settings import Settings
from squashvision.worker import Worker

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "demo-data"
EVIDENCE = ROOT / "evidence"
PRODUCTION = Path.home() / "Library/Application Support/Mosaic Squash"
SOURCE = ROOT / "source-match.mp4"
CLIP = ROOT / "elshorbagy-farag-25s.mp4"
MANIFEST = EVIDENCE / "demo.json"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def save(name: str, value: object) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(value, indent=2) + "\n")


def checked(response):
    if not response.is_success:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json()


def seed_cached_models() -> None:
    database = Database.open(Settings(data_dir=DATA))
    database.engine.dispose()
    source_db = sqlite3.connect(
        f"file:{PRODUCTION / 'squashvision.sqlite3'}?mode=ro&immutable=1", uri=True
    )
    source_db.row_factory = sqlite3.Row
    rows = source_db.execute("SELECT * FROM model_assets WHERE state = 'ready'").fetchall()
    source_db.close()
    assert len(rows) == 2, "Both production model assets must already be ready"
    with sqlite3.connect(DATA / "squashvision.sqlite3") as destination:
        for row in rows:
            relative = Path(row["relative_path"])
            assert not relative.is_absolute() and ".." not in relative.parts
            source_path = PRODUCTION / "storage" / relative
            destination_path = DATA / "storage" / relative
            assert digest(source_path) == row["sha256"]
            assert source_path.stat().st_size == row["byte_size"]
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if not destination_path.exists():
                shutil.copyfile(source_path, destination_path)
            assert digest(destination_path) == row["sha256"]
            columns = list(row.keys())
            placeholders = ",".join("?" for _ in columns)
            destination.execute(
                f"INSERT OR IGNORE INTO model_assets ({','.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )


def prepare() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    print("Preparing real 25-second full-court excerpt at source 250–275 seconds", flush=True)
    if not CLIP.exists():
        subprocess.run(
            [str(resolve_ffmpeg_binary()), "-hide_banner", "-loglevel", "error",
             "-ss", "250", "-i", str(SOURCE), "-t", "25", "-map", "0:v:0",
             "-map", "0:a:0?", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
             "-metadata", "comment=Excerpt from local ElShorbagy v Farag Free Game.mp4; source 250-275 seconds",
             str(CLIP)], check=True, timeout=180,
        )
    seed_cached_models()
    app = create_app(Settings(data_dir=DATA))
    with TestClient(app) as client:
        models = checked(client.get("/api/v1/models"))
        with CLIP.open("rb") as video:
            match = checked(client.post(
                "/api/v1/matches", data={"title": "ElShorbagy vs Farag · Canary Wharf rally"},
                files={"video": (CLIP.name, video, "video/mp4")},
            ))
        match_id = match["id"]
        proposal = checked(client.post(
            f"/api/v1/matches/{match_id}/calibration/propose", json={"timestampSeconds": 1.0},
        ))
        save("calibration-proposal.json", proposal)
        save("models.json", models)
        save("match-upload.json", match)
    manifest = {
        "matchId": match_id,
        "source": {"path": str(SOURCE), "originalFilename": "ElShorbagy v Farag Free Game.mp4",
                   "sha256": digest(SOURCE), "bytes": SOURCE.stat().st_size,
                   "probe": probe_video(SOURCE).model_dump(mode="json", by_alias=True)},
        "clip": {"path": str(CLIP), "sourceStartSeconds": 250, "sourceEndSeconds": 275,
                 "sha256": digest(CLIP), "bytes": CLIP.stat().st_size,
                 "probe": probe_video(CLIP).model_dump(mode="json", by_alias=True)},
        "dataDirectory": str(DATA), "profile": "maximum",
        "provenance": "Actual moving broadcast footage from the user's existing local file; no synthetic motion or detections.",
        "limitations": ["Player track IDs have not been manually matched to player names.",
                        "A 25-second excerpt does not describe the full match.",
                        "Detections and rule-based events are model estimates, not measured ground truth.",
                        "Footage is local demo material; redistribution rights have not been established."],
    }
    save("demo.json", manifest)
    return manifest


def analyze(manifest: dict) -> None:
    app = create_app(Settings(data_dir=DATA))
    with TestClient(app) as client:
        if "jobId" not in manifest:
            job = checked(client.post(
                f"/api/v1/matches/{manifest['matchId']}/jobs", json={"profile": "maximum"},
            ))
            manifest["jobId"] = job["id"]
            save("demo.json", manifest)
        worker = Worker(
            app.state.job_queue, "portfolio-real-footage",
            AnalysisPipeline(storage_root=app.state.storage.root,
                             database=app.state.database,
                             model_manifest=app.state.model_manifest),
        )
        started = time.monotonic()
        while True:
            snapshot = checked(client.get(f"/api/v1/jobs/{manifest['jobId']}"))
            save("job.json", snapshot)
            print(json.dumps({"elapsedSeconds": round(time.monotonic() - started, 2),
                              "state": snapshot["state"], "stage": snapshot["stage"],
                              "progress": snapshot["progress"]}), flush=True)
            if snapshot["state"] in {"completed", "failed", "cancelled"}:
                if snapshot["state"] != "completed":
                    raise RuntimeError(f"Analysis ended with {snapshot}")
                break
            worker.run_once()
        manifest.setdefault("analysisWallSeconds", round(time.monotonic() - started, 2))
        save("demo.json", manifest)


def collect(manifest: dict) -> None:
    app = create_app(Settings(data_dir=DATA))
    with TestClient(app) as client:
        match_id = manifest["matchId"]
        report = checked(client.get(f"/api/v1/matches/{match_id}/reports/latest"))
        save("report.json", report)
        revision = report["revision"]
        review = checked(client.get(f"/api/v1/matches/{match_id}/review-items", params={"revision": revision}))
        save("review-items.json", review)
        observations = {}
        for kind in ("players", "ball"):
            page = checked(client.get(f"/api/v1/matches/{match_id}/observations/{kind}",
                params={"revision": revision, "startUs": 0, "endUs": 25_000_000, "limit": 500}))
            save(f"{kind}-observations-page.json", page)
            observations[kind] = {"firstPageCount": len(page["items"]), "hasNextPage": page["nextCursor"] is not None}
        export = checked(client.post(f"/api/v1/matches/{match_id}/exports", json={
            "revision": revision, "selection": {"formats": ["html", "json", "csv"]},
        }))
        save("export.json", export)
        download = client.get(f"/api/v1/matches/{match_id}/exports/{export['id']}/download")
        download.raise_for_status()
        assert hashlib.sha256(download.content).hexdigest() == export["sha256"]
        (EVIDENCE / "squashvision-report.zip").write_bytes(download.content)
        manifest["reportRevision"] = revision
        manifest["observations"] = observations
        manifest["exportId"] = export["id"]
        manifest["reviewItemCount"] = len(review["items"])
        save("demo.json", manifest)
        print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "analyze", "collect", "all"), default="all", nargs="?")
    phase = parser.parse_args().phase
    manifest = prepare()
    if phase in {"analyze", "all"}:
        analyze(manifest)
    if phase in {"collect", "all"}:
        collect(manifest)
