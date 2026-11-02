# @papercrane/brand

The Paper Crane brand system — a single, dependency-light source of truth for
color tokens, typography, and the paper-crane logo. Consumed by:

- `apps/web` — the public landing site
- `apps/app` — the signed-in product
- route handlers (Next.js `ImageResponse`, email templates, CLI badges)

## Install

Already wired as a workspace dep. In any `apps/*` or `packages/*`:

```jsonc
// package.json
"dependencies": {
  "@papercrane/brand": "workspace:*"
}
```

## Usage

### React components

```tsx
import { Logo } from "@papercrane/brand";

// Favicon-sized mark:
<Logo size={32} />

// Full lockup in the navbar:
<Logo variant="lockup" size={28} />

// Wordmark only:
<Logo variant="wordmark" size={40} />

// Override the crane red (e.g. on a dark background):
<Logo color="#F7F4ED" />
```

### Tokens

```ts
import { colors, typography, brand } from "@papercrane/brand";

colors.crane;         // "#C1272D"
typography.display;   // { family: "Fraunces, serif", cssVar: "var(--font-fraunces)" }
brand.tagline;        // "Every protein design tool. One workflow."
```

### Raw SVG string (for headless contexts)

```ts
import { logoSvg } from "@papercrane/brand";

// Email template, CLI output, Next.js metadata route, etc.
res.setHeader("Content-Type", "image/svg+xml");
res.end(logoSvg);
```

### Standalone SVG asset

Import the raw file when you need a stable URL (e.g. Resend email template
or a static CDN upload):

```ts
import markSvg from "@papercrane/brand/logo.svg";
```

## Variants

| Variant    | Use                                                  |
|------------|------------------------------------------------------|
| `mark`     | favicons, app icons, social avatars, tight UI chrome |
| `wordmark` | footer, when the mark is already present nearby      |
| `lockup`   | navbar, marketing headers — mark + wordmark together |

## See also

- [`STYLE_GUIDE.md`](./STYLE_GUIDE.md) — clear space, sizing, do's and don'ts
- `apps/web/tailwind.config.ts` — the tokens mirrored here as Tailwind theme
