> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Player identity and candidate-count audit

The original 25-second broadcast demo, report 2, contains **18 estimated racket candidates: A 4, B 9, unknown 5**. The A 3/B 8 prefix occurs between source 18.40 and 21.56 seconds. These are not verified shot totals. The review below uses the saved observations and exact source frames; it does not alter the archived report.

| Source time (s) | Selected track | Hitter support |
| --- | --- | --- |
| 0.20 | B | 0.565 |
| 1.20 | Unknown | 0.030 |
| 2.32 | B | 0.549 |
| 3.44 | A | 0.556 |
| 4.88 | B | 0.455 |
| 5.96 | B | 0.463 |
| 6.96 | A | 0.485 |
| 7.96 | B | 0.540 |
| 9.12 | B | 0.462 |
| 10.08 | B | 0.555 |
| 11.28 | Unknown | 0.271 |
| 13.56 | A | 0.607 |
| 14.72 | Unknown | 0.291 |
| 16.96 | Unknown | 0.342 |
| 18.40 | B | 0.525 |
| 21.56 | B | 0.716 |
| 23.04 | Unknown | 0.286 |
| 24.12 | A | 0.475 |

Support values are heuristic association scores, not calibrated probabilities of correct identity or impact.

## Confirmed identity failure

At 4.88 seconds A follows the black shirt and B the navy shirt. At 5.96 seconds these assignments are reversed. The original assignments reverse again between 7.96 and 9.12 seconds, then again by 10.08 seconds. At least seven of the thirteen assigned racket candidates select a track whose visible shirt differs from its initial A/B shirt. The heavily overlapping 24.12-second frame is excluded from that count. This is a direct frame audit of identity consistency, not a ground-truth count of physical racket hits.

The previous appearance vector used the entire person bounding box, including court background, skin and shorts. Association compared it with the immediately preceding detection. An ambiguous pairing still overwrote the appearance, position and velocity history. A locally clear next pairing could then clear ambiguity while preserving a swapped person identity.

Evidence: `runtime/evidence/racket-identity-audit.jpg` shows the actual source frames with original A/B boxes and candidate scores. `runtime/evidence/tracking-timeline.json` preserves the complete candidate sequence.

## Bounded correction

`torso-anchor-v1` isolates the inner shoulder/hip polygon when all four pose landmarks are reliable. Missing or degenerate torso geometry supplies no color evidence. Each track retains its first usable torso appearance anchor through occlusion. Ambiguous assignments cannot overwrite its motion history or anchor. Strong evidence for a distinct other shirt can veto a motion-only swap; similar or absent appearances do not force a choice. There is no alternating-hitter rule.

The identity-policy version is included in player-stage cache inputs and flows into dependent event/report contracts. New analyses cannot silently reuse the old player association artifacts. Existing reports and model weights remain unchanged.

Validation: 45 player/ROI tests pass, including background-independent torso color, ambiguous history, crossings, missing observations and existing interpolation/ambiguity behavior. A separate pipeline-contract regression confirms the policy invalidates player and dependent stages while preserving unrelated ball/prepare/calibration caches.

An association-only replay reused 1,102 saved observed poses and the 625 actual source frames; it did not rerun the pose model. All visible labels at the eighteen candidate audit frames consistently follow black=A and navy=B after the change. Two audit frames have only one retained detection. The replay produced 1,084 observed and 78 interpolated rows. This is a bounded demonstrated improvement, not a full identity-accuracy benchmark. The annotated result is `runtime/evidence/racket-identity-torso-replay.jpg`.

## Remaining contact limitation

Identity association and contact detection are separate. The impact estimator has no learned racket-head detector and no verified hit labels. Its sharp image-speed increase rule can miss a soft return or a contact whose perspective reduces apparent speed. Some plausible contact neighborhoods, including 12.36 seconds, currently carry another surface label; they require video review before calling them missed hits. An unknown hitter is intentionally retained when pose support or separation is insufficient.

For the personal yellow/navy clip, verify shirt identity at crossings and each candidate contact after inference, then manually review a short complete rally for false/missed contacts before displaying any shot count. Floor marks remain estimated ball landings, separate from player feet. The original A/B totals must not be relabeled as verified performance statistics.
