# SquashVision

I've played squash for over eight years, and I review matches whether I win or lose. For the past few years, I drew courts on paper and marked where I missed shots. Working through a match could take about an hour. I wanted to spend more of that time learning from the match and applying it on court. My interest in coding gave me a way to build the review tool I wanted.

## From footage to a review

I built SquashVision around a Python processing pipeline and a React interface. The pipeline uses Ultralytics YOLO for player pose and an adaptation of TrackNetV3 for the ball. Calibration maps image positions into court coordinates. Detections keep their timestamps and source frames, so the interface can show the replay alongside movement maps and shot markers. The upstream tracking models retain their authors' credits.

The demo uses an ElShorbagy-Farag match from Canary Wharf. I can follow a rally, inspect a shot and check its measurements against the footage.

## Getting the tracking to behave

The ball is small and fast, and wall contacts and floor bounces can be hard to distinguish. Early attempts could lose it, mistake someone behind the court for a player, or struggle when the camera angle changed. I spent a lot of time iterating on those cases.

I added a playing-area outline to exclude people outside the court, calibrated the geometry and made shot markers editable. In one Canary Wharf shot, the detector assigns the hitter to Player B. The saved review corrects it to Player A and leaves the hidden bounce unknown. My placement rules also allow a partial wall score when the first bounce is missing, keeping it out of bounce-based averages.

## Using it in my training

I now use SquashVision for my own match review, and its feedback helped me make a new training plan. I'm happy to have a tool I can use and keep improving. My next work is better tracking across courts and a complete web workflow for uploading a match, processing it and returning to the saved review.
