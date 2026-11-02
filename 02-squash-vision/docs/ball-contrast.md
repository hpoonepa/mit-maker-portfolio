> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Ball contrast

Analysis jobs accept `ballInputMode: "original" | "inverted"`. The default is
`original`, including jobs created before migration 0015. The choice is saved on
the job and retained when pausing, resuming, or retrying it. A new analysis job is
required to change it.

The optional **Dark ball on light court** setting uses the existing TrackNet
weights with `255 - image` applied to all four input frames and their median
background. Source coordinates, source frame indices, and timestamps do not
change. This is an input transform, not a newly trained model. It requires the
Balanced or Maximum profile because its support check needs observed player
boxes on each source frame; Fast is rejected by the API.

Before an inverted-model observation is published, an independent check in the
original image must find a moving dark component within eight pixels at 720p,
with image-size scaling. The component must belong to an unambiguous trajectory
of at least five observations. Player, racket-reach, shadow, and vertical glass
regions are excluded. Missing exact-frame player evidence fails closed. This
check only removes observations: it never substitutes a component center or
creates a ball detection. Rejected candidates are also removed so later track
repair cannot revive them.

This conservative setting has substantial gaps, particularly around players,
rackets, glass, and occlusions. It does not establish reliable shot attribution,
complete landing counts, or full three-dimensional ball speed. Any downstream
contact is still an inferred event requiring its own evidence.

The original input mode keeps its existing cache contract. Inverted ball stages
depend on the player artifacts used for exclusion. Ball and derived artifact
envelopes record `uint8_invert_all_frames_and_median_v1` and the support-policy
version while preserving the actual model-weight identity. JSON/HTML exports
carry this preprocessing description under the ball model's
`inputPreprocessing` field, read from the immutable report artifact.

The personal recording's 3–22 second diagnostic contains 570 source frames.
Unmodified inputs missed the clearly visible ball at frame 255. Inversion placed
that detection at (164.91, 515.71), near the visually reviewed center (166, 515).
Across the wider window, inversion produced 266 visible raw predictions; the
original-image guard retained 60 and rejected inspected false detections at
frames 262 and 266. These are development checks on this recording, not a held-out
accuracy evaluation. Detailed evidence is under
`runtime/personal-rally/photometry-wide` and
`runtime/personal-rally/cv-experiment/production-guard-replay.json`.
