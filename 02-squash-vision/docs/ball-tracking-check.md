> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Ball tracking alignment check

Checked on 2026-10-25 against the saved 25-second ElShorbagy–Farag excerpt and the registered RacketVision checkpoint. **No backend coordinate or timestamp change is indicated by this audit.** The visible marker can be made smaller and synchronized more closely to playback without shifting the stored predictions.

## Checkpoint and input contract

The registry uses [`linfeng302/RacketVision-Models/checkpoints/balltrack_best.pth`](https://huggingface.co/linfeng302/RacketVision-Models/blob/a3760773233a0988c9605259743fbdd87c59d3a3/checkpoints/balltrack_best.pth), resolved revision `a3760773233a0988c9605259743fbdd87c59d3a3`. Its saved SHA-256 is `00d707b9db7a49561c411e4765956e79bcd7c7e20c7a0a535073440b3e972342`. The [official checkpoint downloader](https://github.com/OrcustD/RacketVision/blob/main/source/download_checkpoints.py) identifies that same repository and file.

- The [official configuration](https://github.com/OrcustD/RacketVision/blob/main/source/BallTrack/configs/tracknetv3_base.py) specifies four input frames, 512×288 resolution, concatenated median background, 15 input channels, and the last output channel.
- The [training dataset](https://github.com/OrcustD/RacketVision/blob/main/source/BallTrack/dataset/uball.py) reads with OpenCV, keeps **BGR**, prepends the median, rearranges channels, and divides by 255. The local preprocessing follows this channel order. The README's RGB wording does not reflect the actual dataset code.
- Training windows include the target frame as their last image. The [model](https://github.com/OrcustD/RacketVision/blob/main/source/BallTrack/model/tracknet_v3.py) selects its last heatmap, and the [evaluation code](https://github.com/OrcustD/RacketVision/blob/main/source/BallTrack/metrics/ball_metrics.py) selects the last input-frame identifier. The local tracker follows that pairing.
- The upstream [standalone inference script](https://github.com/OrcustD/RacketVision/blob/main/source/BallTrack/inference.py) differs: it feeds frames `i−4` through `i−1` while labeling the prediction `i`. That appears to be a one-frame indexing error in that script. It is not a reason to shift the correctly paired local observations.

Local scaling maps heatmap coordinates independently by source width/512 and source height/288. Both factors are 2.5 for this 1280×720 clip. The local decoder uses a probability-weighted component center; upstream uses a thresholded component bounding-box center. Neither the code comparison nor the spot check establishes that changing the local center estimator would improve accuracy.

## Exact-frame spot check

The `../runtime/evidence/ball-alignment-crops.png` (local artifact not bundled) uses saved observation timestamps and exact PyAV-decoded source frames at 0.12, 3.00, 6.00, 9.00, 12.40, 12.52, 12.60, 15.00, and 18.00 seconds. Each visible crop is 128×128 source pixels, enlarged threefold with nearest-neighbor sampling. The red crosshair marks the stored center; its gap leaves the image underneath visible.

Eight sampled observations have visible predictions near the small bright ball or its motion streak. The 6.00-second observation is unavailable and has no manual visibility label. At **12.52 seconds**, the saved observation is **source frame 313**, centered at **(242.02899, 644.53384)** in 1280×720 source pixels. This is the reference point for comparing the browser overlay.

No gross scale, axis, or timing displacement appears in these samples. Small localization differences and motion blur remain. This visual spot check supports the current coordinate alignment. Measuring precision, recall and localization error across the match requires independently annotated ball centers.

The training heatmap uses a fixed Gaussian spread (`sigma=3.5` at network resolution). Its blob size and decoded covariance are not measurements of the physical ball's radius or a calibrated error bound. Keep the ball marker small, show only the observation associated with the displayed frame, and present optional trail/uncertainty information separately.

No model weights, backend coordinates, application data, or inference settings were changed during this audit.
