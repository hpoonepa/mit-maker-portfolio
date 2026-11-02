> Archived local experiment note. Original data, output files and saved IDs are not included here. The measurements below describe the original run; they were not rerun for the portfolio source review.

# Personal footage ball diagnostic

These local experiments use the actual 1280×720 source pixels from `practice-rallies-176-241.mp4`. They do not alter the original video, published observations or report revisions.

The original checkpoint produced only seven distinct visible ball candidates across the 65-second recording. The independent 3–22-second classical experiment recovers some visible flight, but raw blobs also include moving glass reflections and racket heads. Candidate coverage is not detection accuracy.

The reviewed combination is **inverted TrackNet predictions plus original-pixel and temporal support**. Inversion changes both the four input frames and their median background. The guard keeps the exact model center only when a nearby measured dark-motion blob belongs to a unique trajectory of at least five observations. It does not publish classical centroids as neural predictions, fill missing centers, assign a hitter, or force an impact.

The guard uses original grayscale dark residuals, local contrast, adjacent-frame motion, limited morphological joining of motion-blurred pixels, size/shape bounds, automatic static glass-edge exclusion, and exact-frame player/racket/shadow masks. Both players must have observed poses. Missing poses, ambiguous trajectories, frame gaps and inconsistent timestamps/pixel dimensions remain unavailable. Rejected model candidates are removed before track repair; any later interpolation remains separately labeled interpolation.

## Actual bounded replay

- 570 model predictions from source3–22s;266 are visible under inversion alone.
- Raw spatial agreement initially retained67. Review found frame266 was still a false racket/glass-region match.
- The final five-observation trajectory guard retains60, rejecting both known false frames262 and266.
- The exact production callable and the201-sample original BGR median from0–30s reproduce those60 retained observations.
- One estimated floor event is derived at source8.241567s, frame247, image center(209.375,607.499). Personal calibration1 maps it to(0.6341,8.0404)m. Its hitter remains unknown. The neighboring observed frame248 is lower in the image; the event's supporting-frame uncertainty covers this one-frame difference. This is not an exact measured contact point.
- No supported racket event survives the conservative reach mask in this window. Per-player landing attribution is therefore unavailable; A0/B0/unknown1 describes this estimated event, not performance totals.

`production-guard-replay.json` is the final callable replay. `floor-calibration-input-check.json` records the calibration file digest, personal match ID and pixel dimensions. `floor-bounce-check.jpg` shows actual frames245–249. `wide-supported-crops.jpg` contains the earlier67 spatial-only candidates, including the rejected frame266, so it must not be mistaken for final accepted output. `trajectory-sheet.jpg` visualizes the independent classical trajectory experiment; its markers are not published model output.

Eight focused guard tests cover exact model/source preservation, false-jump removal, repair behavior, two competing trajectories, racket exclusion, missing poses, source gaps, frame dimensions/timestamps, and stationary background marks. The visual checks here are local diagnostic evidence, not a full accuracy benchmark or evidence of complete ball tracking.
