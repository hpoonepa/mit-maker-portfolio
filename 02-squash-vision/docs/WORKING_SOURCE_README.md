> Archived working-source README (source last modified 26 October 2026). Run results, pending work and setup assumptions below describe that development copy. Use [current setup](SETUP.md) and [fresh verification](VERIFICATION.md) for this portfolio. Data outputs referenced as literal paths are deliberately excluded.

# SquashVision

SquashVision analyzes a recorded squash match locally and lets you review the results against the video. This working copy is prepared for a portfolio demonstration, with a simpler match library, synchronized replay tools, court views, and an explicit review workflow.

## Run this copy

From this folder:

```sh
./start.sh
```

After the terminal prints `SquashVision ready`, open **http://127.0.0.1:8950/**. Stop the server and worker with **Ctrl+C** in that terminal.

The script builds this copy's frontend, then starts this copy's Python launcher. It uses `runtime/demo-data` for the match database, videos, models, and analysis artifacts. It does not launch or update the installed Mosaic Squash application. The default Python interpreter reuses the installed application's existing runtime dependencies; the application code comes from this folder.

Requirements are an existing Python 3.12+ environment with the backend dependencies and the web dependencies from `src/squashvision/web/package-lock.json`. The script does not install packages or download models. It chooses a native Node 22.12+ executable, falling back to a native Node 22 installation under `~/.nvm`. This avoids mixing Intel Node with Apple Silicon build dependencies.

Override the interpreter or server settings when needed:

```sh
SQUASHVISION_PYTHON="/path/to/venv/bin/python" ./start.sh
SQUASHVISION_NODE="/path/to/native/node" ./start.sh
./start.sh --api-port 8951 --data-dir ./runtime/another-demo
```

Additional arguments go to the launcher. `./start.sh --help` builds the frontend and then prints its available options. The wrapper clears inherited database/storage path overrides so its data directory stays isolated; use `--data-dir` to select another library.

## Demonstration workflow

1. Open an existing match, or choose **Import video**. Supported containers are MP4, MOV, M4V, and WebM, with limits of 3 hours and 20 GB per recording. Player names, match date, title, and score are optional. After the file transfers, the app prepares the playback video; it shows **Preparing your match** until that finishes.
2. Open **System status** to check video tools, the worker, and model readiness. **Install local models** retrieves missing model assets when required; this step needs network access. Video processing runs locally.
3. In **Setup**, pause on a clear court view, choose **Draw playing area**, and mark 3–16 corners around the court floor in order. Choose **Save playing area**, select a processing profile, then **Start tracking**. This starts tracking in image coordinates without requiring metric calibration. **Court calibration (optional)** is collapsed below; use it when you need court measurements and have enough visible geometry to validate them.
4. In **Processing**, follow the actual stages and use the available pause, resume, cancel, or retry controls.
5. In **Analysis**, press **Play**. The **On court** panel beside the video shows running A/B movement and current estimated ball speed. Separate courts show **A in blue** and **B in coral**, with one uniform mark per assigned floor landing. Marks appear as playback reaches them and disappear on rewind. Click a landing to seek its video frame; its tooltip gives the estimated X/Y coordinates and confidence. Unassigned landings stay off both player courts. **Overlay options** contains optional player boxes and ball trails. **Match summary** loads totals and coverage on first open; **Review tools** contains event review and corrections.

The report views cover overview, shots, rallies, movement, errors, trajectory, head-to-head comparisons, and coaching notes. Each section depends on the evidence produced for that match; unavailable information is surfaced rather than replaced with invented values. Previous report revisions and review corrections are retained by the backend.

The playing-area outline filters player detections to the court floor, helping exclude spectators. It is separate from metric calibration: saving an outline alone does not establish distances, speeds, or a three-dimensional trajectory.

For a full match, use a fixed full-court camera so the saved playing area stays in the same place throughout the recording. Broadcast close-ups, replays, and camera changes do not share that outline. Processing runs in sections and can be paused or resumed from the Processing page; leaving the browser does not stop the local worker.

The complete **20:49 source recording** has now passed processing: all **74 chunks**, report publication, paginated observations without duplicate entries in the checked windows, and a checksum-verified HTML/JSON/CSV export. This also exposed and fixed an observed/interpolated player collision at overlapping processing boundaries. Broadcast cuts still limit inference: its report contains 38 inferred rally segments and only five classified shots, so this verifies the complete workflow rather than a reliable scorecard. [Full-match evidence](../research/local-notes/fullmatch-verification/README.md) records the run and limitations.

## What the demo demonstrates

- A working local video import, preparation, calibration, job, and review flow.
- Model-backed player pose and ball tracking, followed by event classification and derived reports.
- Video evidence connected to timeline events and correction controls, with court coordinates when calibration supports them.
- Persistent match data, report revisions, reanalysis, and exports.

The model registry currently uses `yolo11n-pose.pt` from Ultralytics and `checkpoints/balltrack_best.pth` from `linfeng302/RacketVision-Models` on Hugging Face. Source, revision, size, checksum, and readiness are tracked by the application. These are third-party model weights; the portfolio should distinguish the models from the pipeline, interaction design, and analysis software built around them.

## Limits and evaluation status

This is prerecorded analysis with interactive replay, not live camera inference. Processing time varies with recording length, hardware, profile, and model readiness. There is no accuracy or real-time throughput claim in this demo.

Calibration, occlusion, camera position, and footage quality affect detections and derived metrics. A connected sequence of court contact points is a **contact path**, not a measured continuous three-dimensional ball trajectory. Missing observations remain gaps. Reviewable predictions are not automatically verified ground truth.

Synthetic or repeated-frame fixtures test application behavior; they do not establish performance on real squash matches. For a portfolio recording, identify the footage and show both the result and its corresponding video evidence. Do not present a seeded fixture as a new successful inference run.

The local demo uses the **250–275 second excerpt** of the existing `ElShorbagy v Farag Free Game.mp4` recording. Initial model inference on this 25-second clip took **401.84 seconds on CPU** at the maximum profile. After adding the playing-area mask, reanalysis took **36.5 seconds on CPU while reusing the cached ball results**. These are different workloads, not a fresh-inference speed comparison. The demo now opens **report revision 2**; revision 1 is preserved.

A separate **65-second personal practice clip**, source interval 176–241 seconds, has been imported as match `6396ff4c-fa54-4c77-a342-d7027853e029`. Its calibration and analysis run are pending; no successful analysis or accuracy result is claimed for that clip yet.

Revision 2 contains **1,119 player observation rows: 1,102 observed and 17 interpolated**. Ball output remains **622 rows**, with **581 marked visible**. Full API pagination matched the saved observation artifacts without duplicates. These counts describe model output, not independently verified detection accuracy. The compact record is `runtime/evidence/verification-summary.json`; [the evidence notes](../research/local-notes/evidence/README.md) explain the source and artifacts.

The `runtime/evidence/roi-tracking-verification.json` found no retained player observation with both its feet and box-bottom center outside the saved floor boundary plus a 7.2-pixel tolerance. The `runtime/evidence/roi-tracking-contact-sheet.jpg` shows the actual detections; at the original 12.52-second spectator failure, both on-court players are now boxed and the audience is not. This is a specific correction, not proof of complete tracking accuracy. A/B identity switches remain, the tracks have not been matched to the named players, and **198 observations are marked ambiguous**.

A later torso-appearance and motion-history fix addresses crossing swaps in new analyses. Its saved-pose replay improved identity consistency at the audited frames; it did not rerun the pose model, rewrite report revision 2, or establish general identity accuracy. Contact detection remains a separate unresolved source of missed or false candidates. See the [identity and candidate-count audit](identity-audit.md).

Automatic calibration declined insufficient court topology. The demo now has a separate **manual calibration revision 1**, using nine reviewed front-floor, short-line, and service-box landmarks. All nine are fit inliers, with a 0.38-pixel fitting residual; this is geometric fit consistency, not a ground-truth accuracy measurement. The image-edge playing-area corners were not substituted for the offscreen rear court corners. `runtime/evidence/manual-calibration.json` records the landmarks and WSF dimensions.

The playback panel applies that calibration to report revision 2's saved observations without rerunning models or rewriting the historical report. Movement builds as the video plays: at 5 seconds, A has travelled **4.4 m** and B **6.6 m**; final retained-path totals are **26.4 m for A over 14.44 s (58% coverage)** and **29.1 m for B over 14.80 s (59%)**. The live speed uses image displacement scaled by projected court width, and disappears when the displayed frame lacks a reliable interval. It is a **2D estimate**, not recovered airborne 3D speed.

The two courts display **floor landings only**. A coordinate describes the ball's projected landing, not the player's feet. A landing inherits a player only from a preceding supported racket hit with continuous tracking; unknown contacts and gaps clear that assignment. There is no forced alternation or balancing of A/B totals. Shot counts are omitted because candidate contacts are not verified shots. Position, timing, and player attribution remain estimates, with confidence available in accessible marker tooltips. Four bounce candidates were checked against their before/at/after source frames. See [the methods](tracking-stats.md), `runtime/evidence/tracking-timeline.json`, and `runtime/evidence/floor-bounce-frame-check.jpg`.

The collapsed summary retains its separate floor-projected speed calculation: **9.0 m/s median** and **24.7 m/s 90th percentile**, over 7.52 s (30% coverage). It is not the live speed calculation. `runtime/evidence/tracking-stats.json` includes retained and excluded coverage.

The original published report retained **17 inferred racket-contact candidates**, but only **two classified shot events** with usable hitter positions. Those summary coordinates describe the player's feet, not ball landing positions. The new playback impact estimates are a separate derived series and do not change that historical shot count. The predicted serve inside this mid-rally excerpt remains unverified.

Validation recorded for this working copy:

- Before the stats addition: **171 frontend tests passed across 21 files**, including the playing-area setup and exact-frame overlay flows; TypeScript checking and the production build passed.
- Stats addition: **9 new frontend tests**, **7 rally court regression checks**, and **13 new backend tests plus the existing OpenAPI contract check** passed. The live `runtime/browser-review/stats-verification.json` verified actual numbers, player filters, metre coordinates, exact contact seeking, unknown positions, and mobile layout with no browser errors.
- Backend: **452 distinct tests passed** across the full suite and targeted regression runs. Overlapping reruns are not counted again.
- The real-footage HTML/JSON/CSV export downloaded successfully and its checksum matched the saved record.
- In a disposable copy of the baseline data, a correction created report revision 2, a stale revision returned HTTP 409, and revision 1 remained intact. That test did not alter the demonstration data; the demo's current revision 2 comes from the actual mask-based reanalysis.

The earlier `runtime/browser-review/verification.json` passed on report revision 2 and the playing-area flow. Its 12 checks cover playback, seeking, evidence-frame stepping, pose overlays, fullscreen, all eight report sections, report download, and a real video upload with metadata followed by deletion of that disposable upload. Drawing and saving the playing area survived reload and enabled **Start tracking**. Library, analysis, and setup mobile layouts had no horizontal overflow; no browser errors were recorded.

The current landing-only `runtime/browser-review/live-verification.json` passes **six checks** covering the clean default layout, running measurements, rewind, exact landing seeks, real playback, and mobile overflow. The two colored courts contain only assigned landings, without shot counts or an event list. Video and both courts fit together in the tested 1440×1000 desktop viewport. Seven focused playback UI tests, ten summary tests, and seven impact-estimator regressions pass. The attribution update passes 36 focused backend stats/temporal checks plus the OpenAPI contract check. The production TypeScript check and build pass; `start.sh` uses the application build configuration, while the separate full `typecheck` includes tests. That full check is currently blocked by unrelated iCloud-offloaded test files. These checks establish the exercised interactions, not model accuracy or live inference performance.

Use the [one-minute demo walkthrough](demo-walkthrough.md) to present the actual tracking playback and its limitations. See [design notes](design-notes.md) for the visual direction and references.
