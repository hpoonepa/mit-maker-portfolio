> Archived development note from the canonical working source. Saved-run results below were not rerun for this portfolio review. Unbundled local artifact references are retained as literal paths; see [fresh verification](VERIFICATION.md).

# SquashVision design notes

The portfolio demo should make the recording, analysis, and review process easy to follow. The visual center is the match footage and its court evidence. Navigation, labels, and controls stay quiet around it.

## Direction

| Role | Color |
| --- | --- |
| Navy canvas | `#122435` |
| Slate surface | `#193248` |
| Raised surface | `#203C50` |
| Ivory text | `#F4F4F0` |
| Secondary text | `#ABC0CD` |
| Player A / ice blue | `#7BC4EA` |
| Player B / coral | `#EF997B` |
| Ball | `#E3D78B` |

Inter Tight provides the main type system: approximately 36–44 px page titles, 20 px section headings, 15 px body text, and 12–13 px supporting labels. Numeric comparisons use tabular figures. Technical identifiers can use monospace inside details and exports, rather than throughout the interface.

On desktop, a compact header leads into the match title and a prominent replay beside two separate player courts. Live movement and shot evidence follow playback. Review tools and the timeline remain collapsed below the video; the match summary loads on first open. At narrow widths, the recording comes first and the courts follow below it. The library retains one main title, an obvious import action, and a featured preview for the most recent match.

The matte navy background, 21–25 rem stats panel, contrast checks, and control treatment are specified in [Match console visual direction](match-console-design.md). The layout and palette use no decorative gradients or glow.

The shell/library implementation removes repeated headings and promotional copy, keeps upload progress and cancellation intact, and moves operational details under System status. A generated report is labeled as a version, not as evidence that a human has reviewed it.

## References

- **Lambert 2026 wiki:** the local project's subject-specific illustrations and asymmetric reading hierarchy informed the court-centered empty state and the balance between main content and context. Its science artwork and brand palette were not copied.
- **Papercrane:** quiet navigation and contextual information around a central working view informed the hierarchy. The squash interface does not reproduce the laboratory scene.
- **[Core Sports AI](https://coresportsai.com/) / [Core Insights](https://coresportsai.com/core-insights):** court-based movement and shot analysis support the decision to connect findings to visible match evidence.
- **[RallyVision](https://rallyvision.ai/):** match review, shot summaries, highlights, and movement views support a workflow organized around footage and rallies.
- **[PlaySight](https://www.playsight.tv/playsight-app):** replay, slow motion, annotations, and activity organization inform familiar review controls.

The precise squash product meant by “Core Vision” was not established; [CourtVision](https://courtvision.app/) appears to concern basketball. These references are inspiration, not comparisons of measured model performance or claims of equivalent features.

## Critique and constraints

A near-black canvas with a bright acid-green accent was too generic for this brief. Court materials and two meaningful player colors make the dark interface specific to squash. Repeated KPI panels, all-caps labels, slogans, decorative motion, and identical cards compete with the footage and are reduced. The court illustration is illustrative; analytical plots must use actual available observations and preserve missing data.

Keyboard focus, readable contrast, mobile layout, and truthful pending/error/empty states are part of the working product. The design must remain useful when inference is incomplete, a model is missing, or the recording cannot provide a requested metric.
