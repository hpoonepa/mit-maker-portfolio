"""Save the reviewed court-floor landmarks for the fixed-camera 25s demo."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from squashvision.calibration import (
    CourtCorrespondence, CourtKeypoints, CourtPoint, ImagePoint, Size, fit_calibration,
)

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8950/api/v1/matches/5ebf3351-5a26-48c0-839b-5da930aa7913/calibration"
# Coordinates reviewed on runtime/source-250s.jpg. The rear floor corners are
# outside this frame, so image-edge intersections must not stand in for them.
# WSF: 6.40m x 9.75m; short-line rear edge is 4.26m from the back wall.
# The painted 50mm line's CENTER is therefore y = 9.75 - 4.26 - .025.
LANDMARKS = [
    ("front_left_floor", 374, 384, 0.0, 0.0),
    ("front_right_floor", 902, 384, 6.4, 0.0),
    ("short_line_left_center", 281, 569, 0.0, 5.465),
    ("short_line_right_center", 998, 569, 6.4, 5.465),
    ("short_line_T_center", 640, 569, 3.2, 5.465),
    ("left_service_inner_center", 463, 569, 1.625, 5.465),
    ("right_service_inner_center", 816, 569, 4.775, 5.465),
    # Back service-box line centers: 5.49m + 1.60m clear box + .025m.
    ("left_service_back_wall_center", 237, 655, 0.0, 7.115),
    ("right_service_back_wall_center", 1043, 655, 6.4, 7.115),
]


def main() -> None:
    points = tuple(
        CourtCorrespondence(label, ImagePoint(x, y), CourtPoint(cx, cy))
        for label, x, y, cx, cy in LANDMARKS
    )
    fit = fit_calibration(CourtKeypoints(points), Size(1280, 720))
    if not fit.calibrated or not all(fit.inlier_mask) or fit.rms_error_px > 2:
        raise RuntimeError(f"Manual landmark fit failed: {fit}")
    try:
        with urlopen(URL, timeout=10) as response:
            previous = json.load(response)
    except HTTPError as error:
        if error.code != 404:
            raise
        previous = None
    keypoints = [
        {"label": label, "image": {"x": x, "y": y}, "court": {"xM": cx, "yM": cy}}
        for label, x, y, cx, cy in LANDMARKS
    ]
    payload = {
        "expectedRevision": previous["revision"] if previous else 0,
        "frameSize": {"width": 1280, "height": 720},
        "keypoints": keypoints,
    }
    if previous and previous["keypoints"] == keypoints:
        saved = previous
    else:
        request = Request(URL, data=json.dumps(payload).encode(), method="PUT",
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            saved = json.load(response)
    evidence = {
        "method": "Manual floor landmarks reviewed against the actual source frame",
        "sourceFrame": "runtime/source-250s.jpg",
        "geometrySource": "https://worldsquashofficiating.com/wp-content/uploads/2023/03/Rules-of-Singles-Squash-2020-V2.pdf#page=20",
        "coordinateOrigin": "front-left floor, x rightwards, y toward back wall, metres",
        "limitations": [
            "Manual pixel selection and lens distortion introduce scale error.",
            "Calibration applies to this fixed-camera excerpt only.",
            "A floor homography does not reconstruct airborne ball height or true 3D speed.",
        ],
        "calibration": saved,
    }
    (ROOT / "runtime/evidence/manual-calibration.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"revision": saved["revision"], "confidence": saved["result"]["confidence"],
                      "rmsErrorPx": saved["result"]["rmsErrorPx"], "inliers": saved["result"]["inlierMask"]}))


if __name__ == "__main__":
    main()
