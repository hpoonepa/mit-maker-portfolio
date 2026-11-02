"""Diagnostic only: same real TrackNet weights/geometry, original vs inverted pixels."""
import json
from dataclasses import asdict
from pathlib import Path
import time
import av
import cv2
import numpy as np
import torch
from squashvision.db import Database
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.observations import Frame, FrameBatch
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.vision.ball import BallTracker, TrackNetV3, median_background
from squashvision.vision.ball.tracker import uniform_sample_indices, _default_inference_runner

root = Path(__file__).resolve().parent
out = root / 'personal-rally/photometry-experiment'
out.mkdir(exist_ok=True)
source = root / 'personal-rally/practice-rallies-176-241.mp4'
sample_indices = set(uniform_sample_indices(900, 201))
samples, selected = [], []
decoded_count = 0
with av.open(str(source)) as container:
    for index, raw in enumerate(container.decode(video=0)):
        if raw.time >= 30:
            break
        decoded_count += 1
        if index in sample_indices or 234 <= index <= 263:
            frame = Frame(timestamp_us=round(raw.time*1_000_000), source_frame_index=index,
                          image=raw.to_ndarray(format='bgr24'))
            if index in sample_indices:
                samples.append(frame)
            if 234 <= index <= 263:
                selected.append(frame)
assert decoded_count == 900 and len(samples) == 201 and len(selected) == 30
background = median_background(FrameBatch(tuple(samples)))
del samples
settings = Settings(data_dir=root/'demo-data')
database = Database.open(settings, migrate=False)
storage = LocalStorage(settings.storage_root)
assets = {item.name: item for item in ModelManifest(ModelAssetManager(database, storage)).states()}
device = torch.device('cpu')
model = TrackNetV3.load(assets['ball'], device, storage_root=storage.root)
result = {'purpose': 'Diagnostic only; published observations and pipeline are unchanged',
          'sourceFrameRange': [234, 263], 'sourceSeconds': [selected[0].timestamp_us/1e6, selected[-1].timestamp_us/1e6],
          'referenceFrame': {'index':255, 'timestampSeconds':8.5085, 'visuallyReviewedApproximateCenter':[166,515]},
          'background': 'Same201 uniform samples from original0–30s chunk; inversion transforms median and frames together',
          'methodVersion':'tracknet-photometric-diagnostic-v1', 'requestedDevice':'cpu', 'variants':{}}
for name, inverted in [('original', False), ('inverted', True)]:
    maxima = []
    def inference(mdl, batch, target):
        output = _default_inference_runner(mdl, batch, target)
        maxima.extend(float(value) for value in output.detach().cpu().flatten(1).max(dim=1).values)
        return output
    frames = FrameBatch(tuple(Frame(timestamp_us=f.timestamp_us, source_frame_index=f.source_frame_index,
        image=255-f.image if inverted else f.image) for f in selected))
    tracker = BallTracker(model=model, source_manifest_id='personal-photometry-diagnostic',
        model_manifest_id='ball', device=device, inference_batch_size=8, inference_runner=inference)
    started=time.monotonic()
    rows=tracker.track(frames, 255-background if inverted else background)
    result['variants'][name]={'seconds':time.monotonic()-started,'visible':sum(row.visible for row in rows),
        'rows':[dict(asdict(row), maxHeatmapValue=maximum) for row,maximum in zip(rows,maxima,strict=True)]}
    frame=next(f for f in selected if f.source_frame_index==255).image.copy()
    point=next(row for row in rows if row.source_frame_index==255)
    cv2.drawMarker(frame,(166,515),(255,255,255),cv2.MARKER_CROSS,20,1)
    if point.visible:
        cv2.circle(frame,(round(point.x),round(point.y)),10,(0,255,255),2)
    cv2.putText(frame,f'{name}: visible={point.visible}; max={maxima[[r.source_frame_index for r in rows].index(255)]:.4f}',
                (20,35),cv2.FONT_HERSHEY_SIMPLEX,0.7,(20,20,220),2)
    cv2.imwrite(str(out/f'{name}-frame255.jpg'),frame)
    print(json.dumps({'variant':name,'seconds':result['variants'][name]['seconds'],
        'visible':result['variants'][name]['visible'],'frame255':asdict(point)}),flush=True)
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
