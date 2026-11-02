> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# One-minute SquashVision walkthrough

Start `./start.sh`, then open the [local demo analysis](http://127.0.0.1:8950/matches/5ebf3351-5a26-48c0-839b-5da930aa7913/analysis?revision=2). This presents report revision 2 with the synchronized, landing-only courts. The current `../runtime/browser-review/live-verification.json` (local artifact not bundled) cover the clean layout, running measurements, rewind, landing seeks, real playback, and mobile overflow. Rehearse the sequence once before recording.

| Time | On screen | Suggested narration |
| --- | --- | --- |
| 0–10 s | Open the match and press **Play** with player and ball overlays enabled. | “I built SquashVision's local processing and review interface around third-party pose and ball-tracking models. This view connects their predictions to the actual match video.” |
| 10–23 s | Let the player skeletons and small yellow ball marker play; point to the running movement and speed beside the video. | “Movement accumulates with the rally. The ball speed changes with each tracked frame; it is an estimate from image motion scaled using the court.” |
| 23–35 s | Pause, hover a landing mark for its X/Y coordinates, then click it in either player's court. | “Blue is Player A, coral is Player B. These marks estimate where the ball landed, grouped by the inferred hitter. Selecting one returns to its video frame so I can check it.” |
| 35–48 s | Scrub backwards, then replay several seconds. | “Rewinding rolls back the distances and landings. These partial paths and estimates need review, especially when players cross or become occluded.” |
| 48–60 s | Open **Export options**, select HTML/JSON/CSV, leave media options off, and choose **Build local export**. Show the completed download when available. | “I can export the report and underlying data. My contribution is the application workflow and review tooling; the pose and ball model weights are third-party.” |

## Presenter notes

- The source excerpt is **250–275 seconds** of the local `ElShorbagy v Farag Free Game.mp4`, 1280×720 at 25 fps. A/B track labels are not verified player-name assignments.
- Revision 2 contains **1,119 player observations: 1,102 observed and 17 interpolated**; **198 are marked ambiguous**. Ball output is **622 observations**, of which **581 were marked visible**. These are output counts, not accuracy measurements.
- The mask-based rerun took **36.5 seconds on CPU**, reusing cached ball results. Do not present that as the runtime for a fresh full analysis. The original run took **401.84 seconds**.
- The `../runtime/evidence/roi-tracking-contact-sheet.jpg` (local artifact not bundled) includes the corrected spectator failure at 12.52 seconds. The `../runtime/evidence/roi-tracking-verification.json` (local artifact not bundled) found no player observations failing the floor-eligibility check with its 7.2-pixel edge tolerance. The archived demo still contains A/B switches. A later crossing fix improved a saved-pose replay at audited frames, but does not update this report or prove general identity/contact accuracy; see the [identity audit](identity-audit.md).
- The running distances finish at **26.4 m for A** and **29.1 m for B**, covering 58% and 59% of the excerpt. At 5 seconds, they are approximately 4.4 m and 6.6 m. The live ball speed is a court-scaled 2D estimate and is hidden across gaps. The collapsed **Match summary** uses a separate floor-projected median of 9.0 m/s over 30% coverage.
- Each court contains only uniform ball-landing marks. Their tooltips retain estimated metre coordinates and confidence; player feet are not shown as ball landings. Unassigned landings stay off both courts. Shot counts, the activity list, legend, and extra details below the courts are removed. Do not infer complete shot detection, equal A/B totals, or a recovered 3D ball path from these marks.
- The separate 65-second personal practice clip is imported as match `6396ff4c-fa54-4c77-a342-d7027853e029`; calibration and analysis are pending. Use the verified broadcast excerpt for this walkthrough until that clip has been processed and reviewed.
- The original published report separately has **17 inferred racket-contact candidates**, of which two have assigned hitters and usable foot coordinates. Its predicted serve is unverified. The playback series does not rewrite those classifications.
- Show the correction controls without committing an arbitrary edit to the demonstration report. Correction persistence and stale-revision handling were separately verified in a disposable data copy. The original demonstration report revision 1 remains available alongside the mask-based revision 2.
- The existing verified export is `../runtime/evidence/squashvision-report.zip` (local artifact not bundled). If generating a new export takes longer than the recording segment, continue the download demonstration after it completes.
- Models: Ultralytics `yolo11n-pose.pt` and Hugging Face `linfeng302/RacketVision-Models/checkpoints/balltrack_best.pth`. Describe application development and model integration separately from model training.

The run details, limitations, correction verification, and export checksum are in `../runtime/evidence/verification-summary.json` (local artifact not bundled). The footage is local demonstration material; redistribution rights have not been established. Nothing in this walkthrough publishes it externally.
