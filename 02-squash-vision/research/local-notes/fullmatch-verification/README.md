> Archived local experiment note. Original data, output files and saved IDs are not included here. The measurements below describe the original run; they were not rerun for the portfolio source review.

# Complete recording verification

The original **1,249-second (20:49), 1280×720, 25fps** local recording completed all **74 pipeline chunks**, published report revision1, and exported HTML, JSON, and CSV. This used the actual saved YOLO pose and TrackNet ball weights on the local Mac GPU.

- Match: `1a236bc4-9a7e-4973-b0a9-d916a6151370`
- Job: `0cf0204f-612d-47fc-b4e2-4e45bff0f346`
- Source SHA256: `7cd4c11cc13ee764b1f2153a12d1df030e7800fad45db2f734e63073c33c3acf`
- Data: `../fullmatch-data`; the calibrated25s demo remains separate in `../demo-data`.
- Export: `full-match-report.zip`, 2,526,431bytes, SHA256 `3ea35b29949d76c20590067b7cde222b45dd19a223fd89f5b290e27e7d21eb9a`.

`progress.json` records completed stages, the published revision, and ten paginated observation-window checks spanning the start, chunk overlaps, middle, and final30seconds. All ten returned real observations with no duplicate logical timestamps/player keys. The export checksum matched its database record.

There were22 pose chunks and47 ball chunks, all recording `device:mps` and no device fallback. Their raw totals include intentional overlap:33,419 player rows and34,534 ball rows. These are model outputs, not accuracy scores.

The run paused safely after32 chunks and resumed with bounded image decoding. Exact frame windows and median-background samples were checked for equivalence, and compatible720p checkpoints were preserved. `streaming-pause.json` and `progress.json.resumes` record this transition. Do not interpret total elapsed wall time as processing performance: the computer/turn was suspended for long intervals, and a tool approval remained pending. Initial active streamed ball chunks took approximately40–60seconds per30seconds of video, with slower intervals under load.

iCloud subsequently offloaded four analysis-cache files. Their byte-identical durable checkpoint copies were verified against saved SHA256 and restored; `cache-recovery.json` records this. Inference was not rerun. The full recording also exposed a genuine chunk-overlap bug: an observed player position and an interpolated position at the same timestamp could collide during publication. Logical overlap merging now prefers observed evidence; both chunk orders have regression coverage. Only derived stages were recomputed after that fix.

This verifies whole-recording ingestion, local inference, chunk processing, pause/resume, report publication, pagination, and export. It **does not validate squash analysis accuracy**. The source includes warmup, close-ups, replays, and camera changes; it does not meet the fixed full-court camera requirement. No static playing-area mask or metric calibration was transplanted onto those changing views. The report contains38 inferred rally segments and only5 classified shots, so it is incomplete as a match scorecard. Player identity, inferred contacts, and rally boundaries require review. Use the separately reviewed25s full-court demo for the portfolio walkthrough.
