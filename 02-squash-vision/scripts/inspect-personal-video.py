"""Read-only overview of the local squash recording; originals stay untouched."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

SOURCE = Path('/Users/harsha/Downloads/Sports_Squash/squashanalysisvideo/IMG_1314.mov')
OUT = Path(__file__).resolve().parents[1] / 'runtime/personal-rally'
OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--start', type=float, default=5)
parser.add_argument('--end', type=float)
parser.add_argument('--samples', type=int, default=12)
parser.add_argument('--output', default='overview.jpg')
args = parser.parse_args()
cap = cv2.VideoCapture(str(SOURCE))
if not cap.isOpened():
    raise RuntimeError('Cannot open squash recording')
fps = cap.get(cv2.CAP_PROP_FPS)
frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration = frames / fps
metadata = {'source': str(SOURCE), 'durationSeconds': duration, 'fps': fps,
            'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            'frames': frames, 'byteSize': SOURCE.stat().st_size}
tiles = []
for timestamp in np.linspace(args.start, args.end or max(5, duration - 5), args.samples):
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
    ok, frame = cap.read()
    if not ok:
        continue
    h, w = frame.shape[:2]
    scale = min(400/w, 225/h)
    resized = cv2.resize(frame, (round(w*scale), round(h*scale)))
    tile = np.zeros((251, 400, 3), dtype=np.uint8)
    y, x = (225-resized.shape[0])//2, (400-resized.shape[1])//2
    tile[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
    cv2.putText(tile, f'{timestamp:.2f}s', (8,244), cv2.FONT_HERSHEY_SIMPLEX,.55,(240,240,240),1)
    tiles.append(tile)
cap.release()
while len(tiles)%3:
    tiles.append(np.zeros_like(tiles[0]))
cv2.imwrite(str(OUT/args.output), np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
(OUT/'source.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(json.dumps(metadata))
