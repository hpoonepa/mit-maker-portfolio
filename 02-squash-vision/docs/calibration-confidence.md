> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Calibration confidence and image framing

Calibration confidence is a heuristic quality score with a measurement threshold of 0.65. Manual landmark residuals measure the fit to a planar model. Glass and lens distortion remain sources of measurement error.

The score combines RANSAC inlier ratio, reprojection residual, world-coordinate coverage, normalized homography conditioning, and image support. Image support now divides the inlier-hull area by the fitted court-floor footprint visible inside the image, rather than the entire sensor rectangle. Blank ceiling or wall area therefore does not reduce the score when that padding/crop leaves the visible floor unchanged. Letterboxing that changes the visible floor clipping requires a separately known content rectangle.

Before using the fitted footprint, the algorithm rejects non-finite/empty geometry and a projective horizon crossing the court (opposite homogeneous-denominator signs at court corners). The existing minimum correspondence coverage, duplicate/near-collinear checks, world bounds, RANSAC threshold, condition limit, covariance calculation, and 0.65 score threshold remain in place.

Self-normalization alone would incorrectly make a tiny court occupying 80×60 pixels look fully supported. A separate conservative resolution factor, `min(1, sqrt(visible_floor_area_px) / 160)`, now multiplies coverage quality. The equivalent square side of 160 pixels is an explicit heuristic reference, independent of blank image area. It preserves a penalty for very small court footprints without using ceiling/wall size as a proxy for resolution.

Tests cover equivalent blank-wall crop/padding, horizon-crossing extrapolation, tiny footprints, near-collinear points, duplicate points, RANSAC outliers, and projection capability gates. The personal recording’s independently reviewed landmarks are documented in `runtime/personal-rally/manual-calibration.json`; their read-only framing comparison is in `calibration-math-review.json` beside it.
