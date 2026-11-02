# Paper Crane — Brand Style Guide

Version 0.1 · Last updated 2026-04-23

---

## 1. The Mark

The Paper Crane glyph is an origami crane silhouette rendered as a solid
five-point fold. It lives on a 100×100 artboard and is legible from 16px
up to 512px.

```
                 .
                / \
               /   \
              /  *  \          <- crane eye, paper-colored speck
             /_______\
              \  |  /
               \ | /
                \|/            <- tail
```

### Variants

| Variant   | When to use                                                   |
|-----------|---------------------------------------------------------------|
| `mark`    | favicon, app icon, social avatar, tight chrome (< 48px wide)  |
| `wordmark`| footer, places where the mark is already present above        |
| `lockup`  | navigation bar, marketing headers, OG images                  |

### Clear space

Leave clear space equal to **25% of the mark's height** on every side.
For a 32px mark that's 8px of padding. No other elements may intrude.

### Minimum size

- Digital: **16px** for the mark, **120px wide** for the lockup
- Print: **10mm** for the mark, **35mm wide** for the lockup

Below these sizes the fold geometry collapses — use the mark alone.

### Do

- Let the crane red (`#C1272D`) do the work on paper backgrounds
- Flip to paper (`#F7F4ED`) on ink backgrounds
- Keep the glyph on its baseline — no rotation, no skew

### Don't

- Don't recolor the glyph to arbitrary colors (only `crane`, `craneDeep`,
  `ink`, or `paper` are permitted)
- Don't add drop shadows, gradients, or 3D effects
- Don't stretch the lockup disproportionately
- Don't place the red mark on a saturated red or green background

---

## 2. Color palette

All tokens exist in `packages/brand/src/index.ts` **and** the Tailwind
theme in `apps/*/tailwind.config.ts`. Change them in both places or
neither.

### Core

| Token             | Hex                          | Role                                  |
|-------------------|------------------------------|---------------------------------------|
| `paper`           | `#F7F4ED`                    | Primary surface (warm off-white)      |
| `paper-fold`      | `#EEE9DE`                    | Cards, secondary surfaces             |
| `paper-deep`      | `#E5DED0`                    | Pressed / recessed states             |
| `ink`             | `#14110D`                    | Primary type                          |
| `ink-soft`        | `#2A2621`                    | Secondary copy                        |
| `crane`           | `#C1272D`                    | Brand accent, logo fill               |
| `crane-deep`      | `#961C21`                    | Hover / active state for crane        |
| `crane-glow`      | `rgba(193, 39, 45, 0.12)`    | Radial wash behind the mark           |
| `graphite`        | `#5A554D`                    | Muted UI, metadata, labels            |
| `graphite-soft`   | `#8A857B`                    | Tertiary type, disabled               |
| `lattice`         | `rgba(20, 17, 13, 0.08)`     | Hairline grids                        |
| `lattice-strong`  | `rgba(20, 17, 13, 0.18)`     | Stronger grid lines                   |

### Swatches

```
paper         #F7F4ED  ░░░░░░░░░░
paper-fold    #EEE9DE  ▒▒▒▒▒▒▒▒▒▒
paper-deep    #E5DED0  ▓▓▓▓▓▓▓▓▓▓
ink           #14110D  ██████████
ink-soft      #2A2621  █████████▒
crane         #C1272D  ██████████  <- accent
crane-deep    #961C21  █████████▓
graphite      #5A554D  ▓▓▓▓▓▓▓▓▓▓
graphite-soft #8A857B  ▒▒▒▒▒▒▒▒▒▒
```

### Contrast

- `ink` on `paper` → 14.8:1 (AAA)
- `crane` on `paper` → 4.7:1 (AA for normal text, AAA for large text)
- `graphite` on `paper` → 6.3:1 (AA)
- Never set `crane` on `paper-fold` for body copy — drops below 4.5:1
  at 16px.

---

## 3. Typography

Three stacks. Load once via `next/font` in the root layout.

| Stack     | Family             | CSS var                     | Use                            |
|-----------|--------------------|-----------------------------|--------------------------------|
| `display` | Fraunces (soft 50) | `--font-fraunces`           | Hero, section titles, wordmark |
| `sans`    | Instrument Sans    | `--font-instrument`         | Body copy, UI                  |
| `mono`    | JetBrains Mono     | `--font-jetbrains`          | Metric values, code, IDs       |

### Scale (from Tailwind theme)

| Token         | Clamp                     | Line-height | Letter-spacing | Use           |
|---------------|---------------------------|-------------|----------------|---------------|
| `display-xl`  | `clamp(4rem, 11vw, 10.5rem)` | 0.88        | -0.035em       | Hero headline |
| `display-lg`  | `clamp(3rem, 7vw, 6rem)`     | 0.95        | -0.03em        | Section title |
| `display-md`  | `clamp(2rem, 4.5vw, 4rem)`   | 1.02        | -0.025em       | Subsection    |
| `eyebrow`     | `0.72rem`                    | 1           | 0.24em         | Eyebrow caps  |

### Do

- Pair Fraunces (display) with Instrument Sans (body) — never Fraunces body
- Use `mono` for anything that's a number, a seed, or an ID
- Keep tracking tight on display (`-0.025em` or tighter)

### Don't

- Don't use Fraunces below 24px — loses its character
- Don't ALL-CAPS Fraunces; that's the `eyebrow` token's job
- Don't introduce a fourth typeface

---

## 4. Voice

- **Precise, not clinical.** We write for scientists who are tired of
  hype.
- **Numbers when we have them**, plain English otherwise.
- Tagline: *Every protein design tool. One workflow.*
- Avoid: "revolutionary", "cutting-edge", "AI-powered"
- Prefer: "reproducible", "under one methodology", "benchmarked"

---

## 5. Asset checklist

When shipping a new surface (app, email, doc), confirm:

- [ ] Mark rendered via `<Logo />` from `@papercrane/brand` — **never** a copy-pasted SVG
- [ ] Background is `paper`, `ink`, or a gradient of the two
- [ ] Minimum clear space respected (25% of mark height)
- [ ] All type uses the three loaded stacks
- [ ] OG image is 1200×630, favicon dynamic via `app/icon.tsx`
- [ ] Contrast passes WCAG AA

---

For questions: open an issue tagged `brand`.
