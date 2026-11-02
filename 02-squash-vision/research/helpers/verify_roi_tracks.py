"""Validate image-mask eligibility and render actual timestamp-aligned detections."""
from collections import Counter
import json
from statistics import median

import av
import cv2
import numpy as np
from PIL import Image, ImageDraw
import pyarrow.parquet as pq

from prepare_demo import DATA, EVIDENCE, ROOT, save

manifest = json.loads((EVIDENCE / "demo.json").read_text())
region = manifest["playerRoi"]
envelopes = [path for path in (DATA / "storage/analysis-cache").glob("*/players/*/envelope.json")
             if json.loads(path.read_text()).get("player_roi") == region]
assert len(envelopes) == 1
envelope_path = envelopes[0]
envelope = json.loads(envelope_path.read_text())
rows = pq.read_table(envelope_path.parent / envelope["payload_name"]).to_pylist()
polygon = np.asarray([[point["x"], point["y"]] for point in region["points"]], dtype=np.float32)
tolerance = min(region["frameSize"].values()) * 0.01
outside = []
for row in rows:
    feet = (row["feet_x"], row["feet_y"])
    bottom = ((row["box_x1"] + row["box_x2"]) / 2, row["box_y2"])
    if not any(cv2.pointPolygonTest(polygon, point, True) >= -tolerance for point in (feet, bottom)):
        outside.append({"timestampUs": row["timestamp_us"], "playerId": row["player_id"]})
assert not outside, outside

times = [0.04, 3.0, 6.0, 9.0, 12.52, 15.0, 18.0, 21.0, 24.0]
sheet = Image.new("RGB", (1440, 882), "#141718")
draw_sheet = ImageDraw.Draw(sheet)
samples = []
with av.open(str(ROOT / "elshorbagy-farag-25s.mp4")) as container:
    stream = container.streams.video[0]
    for index, seconds in enumerate(times):
        timestamp = round(seconds * 1_000_000)
        container.seek(int(seconds / stream.time_base), stream=stream)
        frame = next(frame for frame in container.decode(stream) if frame.time >= seconds - 0.00001)
        picture = frame.to_image()
        draw = ImageDraw.Draw(picture)
        draw.line([tuple(point) for point in polygon.tolist()] + [tuple(polygon[0])], fill="#d8dc78", width=2)
        selected = [row for row in rows if abs(row["timestamp_us"] - timestamp) < 1]
        for row in selected:
            color = "#75caff" if row["player_id"] == "A" else "#ffad87"
            draw.rectangle([row["box_x1"], row["box_y1"], row["box_x2"], row["box_y2"]], outline=color, width=4)
            label = f"{row['player_id']} {row['detection_confidence']:.2f}"
            if row["ambiguous"] or row["evidence"] != "observed":
                label += " uncertain"
            draw.text((row["box_x1"] + 4, row["box_y1"] + 4), label, fill=color, stroke_width=1, stroke_fill="black")
        picture.save(EVIDENCE / f"roi-sample-{seconds:.2f}s.jpg")
        x, y = (index % 3) * 480, (index // 3) * 294
        sheet.paste(picture.resize((480, 270)), (x, y))
        draw_sheet.text((x + 8, y + 274), f"{seconds:.2f}s | {len(selected)} model tracks", fill="white")
        samples.append({"timestampSeconds": seconds, "playerIds": [row["player_id"] for row in selected],
                        "boxes": [[row["box_x1"], row["box_y1"], row["box_x2"], row["box_y2"]] for row in selected]})
sheet.save(EVIDENCE / "roi-tracking-contact-sheet.jpg")
result = {
    "reportRevision": manifest["reportRevision"], "rows": len(rows),
    "evidenceCounts": dict(Counter(row["evidence"] for row in rows)),
    "ambiguousRows": sum(row["ambiguous"] for row in rows),
    "medianDetectionConfidence": median(row["detection_confidence"] for row in rows),
    "outsidePlayingAreaRows": outside, "edgeTolerancePx": tolerance,
    "playerRoi": region, "samples": samples,
    "originalReportRevisionPreserved": manifest["originalReportRevisionPreserved"],
}
save("roi-tracking-verification.json", result)
print(json.dumps({key: result[key] for key in ("reportRevision", "rows", "evidenceCounts", "ambiguousRows", "outsidePlayingAreaRows")}, indent=2))
