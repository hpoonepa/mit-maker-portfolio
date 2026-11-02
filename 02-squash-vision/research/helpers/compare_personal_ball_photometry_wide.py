"""Diagnostic only: bounded TrackNet inversion trial, no database mutations."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import av
import cv2
import torch

from squashvision.db import Database
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.observations import Frame, FrameBatch
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.vision.ball import BallTracker, TrackNetV3, median_background
from squashvision.vision.ball.tracker import _default_inference_runner, uniform_sample_indices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=('mps', 'cpu'), default='mps')
    parser.add_argument('--start', type=float, default=3.0)
    parser.add_argument('--end', type=float, default=22.0)
    args = parser.parse_args()
    if not 0 <= args.start < args.end <= 30:
        raise ValueError('This diagnostic uses the first 30-second primary chunk background')
    device = torch.device(args.device)
    if device.type == 'mps' and not torch.backends.mps.is_available():
        raise RuntimeError('MPS was requested but unavailable; refusing a silent long CPU run')
    root = Path(__file__).resolve().parent
    out = root / 'personal-rally/photometry-wide'
    out.mkdir(exist_ok=True)
    source = root / 'personal-rally/practice-rallies-176-241.mp4'
    sample_indices = set(uniform_sample_indices(900, 201))
    samples = []
    with av.open(str(source)) as container:
        for index, raw in enumerate(container.decode(video=0)):
            if raw.time >= 30:
                break
            if index in sample_indices:
                samples.append(Frame(timestamp_us=round(raw.time * 1e6), source_frame_index=index,
                                     image=raw.to_ndarray(format='bgr24')))
    assert len(samples) == 201
    background = 255 - median_background(FrameBatch(tuple(samples)))
    del samples
    settings = Settings(data_dir=root / 'demo-data')
    database = Database.open(settings, migrate=False)
    storage = LocalStorage(settings.storage_root)
    assets = {item.name: item for item in ModelManifest(ModelAssetManager(database, storage)).states()}
    model = TrackNetV3.load(assets['ball'], device, storage_root=storage.root)
    maxima = []

    def inference(mdl, batch, target):
        output = _default_inference_runner(mdl, batch, target)
        maxima.extend(float(value) for value in output.detach().cpu().flatten(1).max(dim=1).values)
        return output

    tracker = BallTracker(model=model, source_manifest_id='personal-photometry-diagnostic',
                          model_manifest_id='ball', device=device, inference_batch_size=8,
                          inference_runner=inference)
    rows = []
    buffer = []
    started = time.monotonic()

    def flush():
        if len(buffer) < 4:
            return
        before = len(maxima)
        tracked = tracker.track(FrameBatch(tuple(buffer)), background)
        rows.extend(dict(asdict(row), maxHeatmapValue=maximum)
                    for row, maximum in zip(tracked, maxima[before:], strict=True)
                    if args.start * 1e6 <= row.timestamp_us < args.end * 1e6)
        (out / 'progress.json').write_text(json.dumps({
            'rows': len(rows), 'visible': sum(row['visible'] for row in rows),
            'throughSeconds': rows[-1]['timestamp_us'] / 1e6 if rows else None,
            'elapsedSeconds': time.monotonic() - started,
        }) + '\n')
        buffer[:] = buffer[-3:]

    with av.open(str(source)) as container:
        for index, raw in enumerate(container.decode(video=0)):
            if raw.time >= args.end:
                break
            if raw.time < max(0, args.start - 0.11):
                continue
            buffer.append(Frame(timestamp_us=round(raw.time * 1e6), source_frame_index=index,
                                image=255 - raw.to_ndarray(format='bgr24')))
            if len(buffer) >= 35:
                flush()
        flush()
    result = {
        'purpose': 'Diagnostic only; published observations and pipeline are unchanged',
        'sourceSeconds': [args.start, args.end],
        'sourcePath': str(source),
        'sourceSha256': '2bb6f541ecbe51484cfd48d4657cfd090ebadf51d5b7fb1d72a2adab2d5cc54f',
        'modelSha256': assets['ball'].sha256,
        'methodVersion': 'tracknet-photometric-diagnostic-v1',
        'transform': 'uint8 BGR 255-image applied to all four frames and the 201-sample median',
        'requestedDevice': args.device,
        'background': 'Same201 uniform samples from original0–30s chunk',
        'variants': {'inverted': {'seconds': time.monotonic() - started,
                                  'visible': sum(row['visible'] for row in rows), 'rows': rows}},
    }
    (out / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'variants'}), flush=True)
    print(json.dumps({'rows': len(rows), 'visible': result['variants']['inverted']['visible'],
                      'seconds': result['variants']['inverted']['seconds']}), flush=True)


if __name__ == '__main__':
    main()
