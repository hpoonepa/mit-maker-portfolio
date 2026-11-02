"""Pause our isolated verification worker at a durable chunk boundary."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from squashvision.db import Database
from squashvision.jobs import JobQueue
from squashvision.models import JobStatus
from squashvision.settings import Settings
from squashvision.storage import LocalStorage

root = Path(__file__).resolve().parent
settings = Settings(data_dir=root / "fullmatch-data")
queue = JobQueue(Database.open(settings, migrate=False), LocalStorage(settings.storage_root))
job_id = "0cf0204f-612d-47fc-b4e2-4e45bff0f346"
queue.pause(job_id)
print("Requested pause after current chunk", flush=True)
while True:
    current = queue.get(job_id)
    if current.status is JobStatus.PAUSED:
        snapshot = {"status": "paused", "jobId": job_id,
                    "atEpochSeconds": time.time(),
                    "purpose": "Load bounded streaming decode while preserving compatible720p checkpoints"}
        (root / "fullmatch-verification" / "streaming-pause.json").write_text(json.dumps(snapshot, indent=2))
        # This PID is the worker launched by this verification task. Pause is
        # acknowledged only after its artifact and checkpoint commit.
        command = subprocess.run(["ps", "-p", "16988", "-o", "command="],
                                 capture_output=True, text=True, check=False).stdout
        if "python3.12 squash-vision/runtime/verify_full_match.py" not in command:
            raise SystemExit("Original verification worker is no longer present; nothing was terminated")
        os.kill(16988, signal.SIGTERM)
        print("Verified pause; stopped old worker16988", flush=True)
        break
    if current.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        print(f"Worker reached {current.status.value}; did not terminate", flush=True)
        break
    time.sleep(1)
