"""Benchmark actual cached local models on five seconds before scheduling a full match."""
import json
import os
from pathlib import Path
import resource
import time

import av
import torch

from squashvision.db import Database
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.observations import Frame, FrameBatch
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.vision.ball import BallTracker, TrackNetV3, median_background

root = Path(__file__).resolve().parent
settings = Settings(data_dir=root / "demo-data")
database = Database.open(settings, migrate=False)
storage = LocalStorage(settings.storage_root)
assets = {item.name: item for item in ModelManifest(ModelAssetManager(database, storage)).states()}
frames = []
with av.open(str(root / "elshorbagy-farag-25s.mp4")) as container:
    for index, frame in enumerate(container.decode(video=0)):
        if frame.time >= 5:
            break
        frames.append(Frame(timestamp_us=round(frame.time * 1_000_000), source_frame_index=index,
                            image=frame.to_ndarray(format="bgr24")))
batch = FrameBatch(tuple(frames))
background = median_background(batch)
device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
started = time.monotonic()
model = TrackNetV3.load(assets["ball"], device, storage_root=storage.root)
loaded = time.monotonic()
tracker = BallTracker(model=model, source_manifest_id="benchmark-source", model_manifest_id="ball",
                      device=device, inference_batch_size=16)
rows = tracker.track(batch, background)
elapsed = time.monotonic() - loaded
result = {"clipSeconds": 5, "sourceFrames": len(frames), "ballObservationRows": len(rows),
          "mpsAvailable": torch.backends.mps.is_available(), "requestedDevice": device.type,
          "actualDevice": tracker.device.type, "deviceFallback": tracker.device_fallback,
          "modelLoadSeconds": loaded-started, "inferenceSeconds": elapsed,
          "framesPerSecond": len(frames)/elapsed,
          "estimated1249SecondBallStageSeconds": elapsed * 1249 / 5,
          "maxResidentBytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
(root / "evidence/local-gpu-benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2), flush=True)
