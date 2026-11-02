> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Personal practice footage

The local recording is `Downloads/Sports_Squash/squashanalysisvideo/IMG_1314.mov`.
The demo excerpt contains source **176–241 seconds**, about 65 seconds, with audio.
The original 35-minute recording remains unchanged.

Match: `6396ff4c-fa54-4c77-a342-d7027853e029`.
[Open locally](http://localhost:8950/matches/6396ff4c-fa54-4c77-a342-d7027853e029/analysis).
The extraction, source/clip hashes, processing jobs and exports are recorded in
`../runtime/personal-rally/manifest.json` (local artifact not bundled).

The reviewed camera calibration uses 11 visible front-floor and service-line
landmarks. All 11 are fit inliers, with a 0.884 pixel fitting residual. That residual
measures geometric consistency.
Rear court corners extend outside the image and were not replaced with image-edge
points. The separate playing-area mask excludes the walls from player selection.

An actual-frame audit of 12 selected player views, including crossings and the
processing overlap, found **A = yellow shirt, B = navy shirt**. The 171 common observed
player/frame rows in the overlap agree exactly. The audit covered those selected views and overlap rows. See the
`../runtime/personal-rally/player-identity-audit.json` (local artifact not bundled).

## Ball tracking findings

The first unmodified model run completed all 10 pipeline chunks and exported a
report. It produced only 7 distinct visible ball detections over the excerpt,
with no continuous clean ball-speed intervals or supported landing estimates.
The pipeline completed, but ball tracking was too sparse for useful speed or landing estimates.

A separate contrast diagnostic inverted both the four model-input frames and
their median background, preserving all source coordinates and the same model
weights. On the one-second diagnostic, the model detected the visibly reviewed
frame 255 ball within approximately 1.3 pixels, while the original input missed it.
It also produced false positives. Independent original-image motion support
rejects a demonstrated false jump.

The 19-second diagnostic produced 266 visible model predictions over 570 frames.
Only 60 passed the conservative independent pixel-and-trajectory check. Those
included one estimated floor bounce, with no supported hitter assignment. Player landing maps and shot totals need more supported contacts.
Diagnostic files stay separate from published observations.

The setup option **Ball contrast → Dark ball on light court** selects the
versioned preprocessing mode. **Standard** preserves the original input. Each
job records its selection; changing contrast invalidates the relevant ball and
derived caches. After processing, the final personal-demo report needs a frame-by-frame review.

## What to show in the demo

- Show the original recording, calibrated player movement and synchronized replay.
- The two colored courts show supported ball landings.
- Missing tracking stays missing. Reviewed points, if added, must be identified
  as reviewed annotations rather than automatic model output.
- Inference runs before replay; playback shows the saved results in sync with the video.
- The pose and ball checkpoint weights are third-party; the pipeline, tracking
  fixes, calibration, interface and review work are separate contributions.

The old `SquashBall.v1-1.yolov5pytorch.zip` in Downloads contains broadcast-match
annotations, not labels from this personal recording. It was audited, not used
to train a personal-video model. See the
[dataset audit](../research/local-notes/personal-rally/dataset-audit/README.md).
