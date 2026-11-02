"""Inspect raw pose candidates at the observed spectator-association failure."""
import json
import os
from pathlib import Path

import av

from squashvision.db import Database
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.observations import Frame, FrameBatch
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.vision.players import PlayerDetector

root = Path(__file__).resolve().parent
(root / "yolo-config/Ultralytics").mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(root / "yolo-config")
settings = Settings(data_dir=root / "demo-data")
database = Database.open(settings, migrate=False)
storage = LocalStorage(settings.storage_root)
manifest = ModelManifest(ModelAssetManager(database, storage))
asset = next(item for item in manifest.states() if item.name == "pose")
with av.open(str(root / "elshorbagy-farag-25s.mp4")) as container:
    stream = container.streams.video[0]
    container.seek(int(12.52 / stream.time_base), stream=stream)
    frame = next(frame for frame in container.decode(stream) if frame.time >= 12.52)
    frame.to_image().save(root / "evidence/tracking-failure-source.jpg")
    batch = FrameBatch((Frame(timestamp_us=12_520_000, source_frame_index=313,
                              image=frame.to_ndarray(format="bgr24")),))
result = PlayerDetector(asset, storage_root=storage.root).detect(batch)[0]
summary = [
    {"box": [item.box.x1, item.box.y1, item.box.x2, item.box.y2],
     "confidence": item.confidence, "feet": item.feet,
     "courtOverlap": item.court_overlap, "poseCompleteness": item.pose_completeness}
    for item in result.detections
]
(root / "evidence/tracking-failure-candidates.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
