> Archived local experiment note. Original data, output files and saved IDs are not included here. The measurements below describe the original run; they were not rerun for the portfolio source review.

# Real footage verification

The isolated demo uses 250–275 seconds of the user's existing `ElShorbagy v Farag Free Game.mp4`, a moving, full-court broadcast rally. The source is 1280×720 at 25 fps. Source and excerpt hashes, metadata, and offsets are recorded in `demo.json`.

The copied application ran its actual YOLO pose and TrackNet models at maximum profile. Both cached weight files were verified against the installed application's recorded SHA-256 hashes before copying. No observations were fabricated. Initial CPU processing took 401.84 seconds. A reviewed image-only playing-area mask corrected spectator detections; reanalysis took 36.5 seconds while reusing the unchanged ball inference. Playback is synchronized with saved model results, not live inference.

- Revision 2 contains 1,119 player rows: 1,102 observed and 17 explicitly interpolated; 198 carry ambiguous identity associations.
- Every player row satisfies the reviewed image playing area within a 7.2 px edge tolerance. Nine rendered timestamps, including the original 12.52-second spectator failure, show the corrected player locations. Player IDs can still switch through occlusion and are not verified person identities.
- 622 ball observation rows; 581 marked visible.
- Full observation pagination matched the underlying artifact rows without duplicates.
- The report estimated one open-ended rally and two classified shot events. A full contact count needs manual annotation. The predicted serve within this mid-rally excerpt awaits review.
- Automatic calibration refused insufficient court topology. The manually reviewed floor polygon is only an image detection mask; its rear vertices meet the image edge and are not claimed to be metric court corners. No manual metric calibration was inserted. Distances and ball speed remain unavailable.
- The HTML/JSON/CSV ZIP downloaded successfully and matched its recorded checksum.
- In a disposable data copy, a correction created revision 2, a stale revision returned HTTP 409, and revision 1 remained unchanged. That test action is absent from the portfolio data. The live portfolio's revision 2 instead comes from the actual image-mask reanalysis; its original revision 1 remains unchanged.

`verification-summary.json` provides the compact evidence record. `report.json` contains the current model-generated report. `report-before-roi.json` preserves revision 1. `roi-tracking-verification.json` and `roi-tracking-contact-sheet.jpg` document the spectator regression. `squashvision-report.zip` is the verified current export. `correction-verification.json` describes the isolated correction test.

The demo match ID is `5ebf3351-5a26-48c0-839b-5da930aa7913`; the application data directory is `runtime/demo-data`. No worker from the preparation script remains running.
