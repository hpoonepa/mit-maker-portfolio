> Archived local experiment note. Original data, output files and saved IDs are not included here. The measurements below describe the original run; they were not rerun for the portfolio source review.

# Ball annotation archive audit

The archive contains annotations from the ElShorbagy–Farag Canary Wharf 2020 broadcast used by the existing demo. It does **not** match personal video `IMG_1314.mov`. No model weights are present, and no training was run.

## Contents

| Split | Images | Labels | Ball boxes |
| --- | ---: | ---: | ---: |
| train | 57 | 57 | 57 |
| valid | 17 | 17 | 17 |
| test | 8 | 8 | 8 |
| Total | 82 | 82 | 82 |

Every image is 640 × 640. All labels contain one valid class-0 YOLO box within image bounds; no empty labels or byte-identical duplicate images were found. Three spot-checked labels (5280, 5310, 6540) cover visible ball/streak regions. The manual review covered those three frames; the remaining labels await review.

Archive metadata describes one class, `ball`, export on 24 November 2024, automatic orientation, stretch to 640 × 640, and no augmentation. It lists CC BY 4.0 and Roboflow project `squashball-jsgth`, version 1. These are local archive statements, not independent verification of ownership or video rights.

## Source comparison

Both source videos were decoded directly and resized to the export dimensions for comparison. The broadcast comparison also checked two neighboring frames on each side.

| Archive frame | Source | Exact source time | Pixel MAE / 255 | PSNR |
| --- | --- | ---: | ---: | ---: |
| 05280 | Personal IMG_1314 | 176.073333 s | 108.436 | 6.41 dB |
| 05280 | Broadcast source-match.mp4 | 211.200000 s | 2.405 | 36.71 dB |
| 06540 | Broadcast source-match.mp4 | 261.600000 s | 2.405 | 36.67 dB |

The exact broadcast frames match the same players, court, scoreboard, and ball locations. Neighboring broadcast frames scored approximately 27–30 dB. The remaining small pixel differences are compatible with export resizing/JPEG encoding; no temporal offset is indicated at the two checked indices. The personal frame shows an entirely different white court and players.

## Future training holdout

The existing broadcast demo covers source seconds **250–275**, corresponding to zero-based frames **[6250, 6875)** at 25 fps. Exclude both overlapping annotations from any future training or tuning:

- Train frame **6480**, 259.20 s.
- Validation frame **6540**, 261.60 s.

The supplied `future-training-holdout.csv` also excludes train frame **6180**, 247.20 s, using a conservative five-second temporal buffer around the demo. This is a proposed exclusion manifest, not a changed dataset split. For a generalization claim, a separate recording/court is a stronger test than randomly splitting frames from this same recording.

The eight IDs 5280, 5310, 5640, 5730, 6180, 6480, 6540, and 7050 happen to fall near the personal clip's frame-number interval. They belong to the broadcast and must not be represented as personal-video annotations. No verified annotations for the personal 176–241 s clip were found in this archive.

`dataset-audit.json` records every image/label, normalized box, hash, source time, and exclusion flag. `broadcast-frame-comparison.json` and `frame-05280-comparison.json` contain the comparison measurements. Only three selected image/label pairs were extracted; paths were checked for traversal and symlinks before writing beneath this audit directory. Source files and the archive were not modified.
