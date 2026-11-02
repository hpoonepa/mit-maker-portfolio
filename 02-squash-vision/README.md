# SquashVision

I have played squash for eight years. I used to review match footage manually and write notes on paper, trying to understand what I missed after a tough match. I built SquashVision to bring the replay, player movement and shot placement into one place.

When I started uploading my own games, the software gave me statistics, but I still had to watch the footage to know whether they were accurate. It could miss where the ball bounced or pick up someone standing behind the court. A setup that worked on one recording could struggle with another court or camera angle.

The separately submitted demo shows an ElShorbagy vs Farag Canary Wharf rally with saved tracking and separately reviewed shot markers.

## How the pipeline works

The Python pipeline prepares the video and keeps detections tied to their source frames. I use Ultralytics YOLO for player pose and a TrackNetV3 adaptation for ball tracking. A playing-area outline helps exclude people outside the court; separate calibration maps positions into court coordinates for movement estimates. The React interface puts the replay beside those measurements and shot annotations.

The hardest part has been deciding what I can reasonably infer from that output. I made shot markers editable and linked them to the relevant video frames so I can check a suspicious result directly. Corrections save a new report revision, keeping the previous result available.

For shot ratings, I use explicit heuristic targets: rules about placement, such as how deep a drive lands and how close it stays to a side wall. If a first bounce is missing, the app can show a limited wall-placement score without including it in bounce-based averages. The score's usefulness still depends on the tracking and annotations behind it.

Uploading and processing different recordings is still a work in progress. I'm improving how the pipeline handles different courts and camera angles. Tracking accuracy and the ratings' agreement with coaching judgments have not been measured. Movement covers retained tracking intervals, and ball speed is a 2D estimate.

This source-only archive excludes submission videos, images and PDFs. The source includes the application, tests, migrations and local experiment helpers. The [code map](docs/CODE_MAP.md) explains where each part lives. [Citations](CITATIONS.md) credit the models, libraries and footage; [third-party notices](THIRD_PARTY_NOTICES.md) distinguish their licenses. Model weights and imported recordings are separate.

[Build notes](docs/BUILD-NOTES.md) · [Setup](docs/SETUP.md) · [Validation](docs/VERIFICATION.md) · [Local experiments](research/README.md) · [Media provenance](assets/PROVENANCE.md)
