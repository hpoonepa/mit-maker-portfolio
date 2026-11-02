> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# Match console visual direction

The playback workspace uses a flat navy background with slate surfaces. The video remains the largest region; the adjacent 21–25 rem panel holds separate Player A and Player B courts. At widths below 62 rem the panel moves below the video, keeping both courts readable without squeezing the player.

The global palette is defined in `src/squashvision/web/src/styles/tokens.css`:

| Role | Color |
| --- | --- |
| Page | `#122435` |
| Primary surface | `#193248` |
| Raised surface | `#203c50` |
| Hover surface | `#244458` |
| Border | `#345164` |
| Main text | `#f4f4f0` |
| Player A | `#7bc4ea` |
| Player B | `#ef997b` |
| Ball | `#e3d78b` |

Player colors are consistent across court points, paths, labels, and the video skeleton. The canvas overlay must use the same A/B values as the CSS variables. Player letters remain visible so identity does not depend only on color. The yellow ball remains distinct from both players.

Primary playback and form controls retain the existing typography, labels, and 44 px minimum height. A light primary Play control, restrained borders, and a filled selected speed distinguish actions without gradients, glow, decorative animation, or added promotional copy. Keyboard focus stays visible. The darkest media surface is reserved for video letterboxing.

Text contrast was checked against the lightest surface: ivory 9.3:1, normal text 7.7:1, muted text 5.5:1, Player A 5.4:1, and Player B 4.7:1 (rounded). Court linework and surface dividers intentionally remain quieter than text. Dynamic measurements, uncertainty rules, playback synchronization, and the review workflow are unchanged by this theme pass.
