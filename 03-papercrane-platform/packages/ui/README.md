# @papercrane/ui

Shared UI component library for Paper Crane. Consumed by `apps/web` (landing) and `apps/app` (product).

- Pure Tailwind + React — **zero** Radix / Headless UI / shadcn
- Every component `forwardRef`s where applicable and accepts `className` (merged via `cn`)
- Accessibility baked in: ARIA attrs, keyboard nav, focus management
- Tiny runtime footprint — peerDeps are `react`, `react-dom`, `lucide-react`, `clsx`, `tailwind-merge`

## Install / wire up in a consumer app

Workspace dependency (already configured via `pnpm-workspace.yaml`):

```json
// apps/<app>/package.json
{
  "dependencies": {
    "@papercrane/ui": "workspace:*",
    "clsx": "*",
    "tailwind-merge": "*",
    "lucide-react": "*"
  }
}
```

### Tailwind preset

```ts
// apps/<app>/tailwind.config.ts
import type { Config } from "tailwindcss";
import papercranePreset from "@papercrane/ui/tailwind-preset";

export default {
  presets: [papercranePreset],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "../../packages/ui/src/**/*.{ts,tsx}", // so UI classes aren't purged
  ],
} satisfies Config;
```

### Global toast

```tsx
// apps/<app>/app/layout.tsx
import { ToastProvider } from "@papercrane/ui";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
```

## Exports

### Primitives
`Button`, `Input`, `Textarea`, `Checkbox`, `Radio`, `Switch`, `Select`,
`Card`, `CardHeader`, `CardBody`, `CardFooter`,
`Dialog`, `Dropdown`, `Tooltip`,
`Badge`, `Avatar`, `Skeleton`, `Separator`

### Feedback
`ToastProvider`, `useToast`, `Banner`, `Spinner`

### Layout
`PageHeader`, `EmptyState`, `Stack`

### Hooks
`useMediaQuery`, `useLocalStorage`, `useKeyPress`

### Utils
`cn(...classes)` — `clsx` + `tailwind-merge` combined

## Scripts

```bash
pnpm --filter @papercrane/ui test        # run vitest
pnpm --filter @papercrane/ui test:watch  # watch mode
pnpm --filter @papercrane/ui typecheck   # tsc --noEmit
```

## Design principles

1. Keep components small, composable, and unopinionated about layout.
2. Prefer native elements over ARIA widgets (`<button>`, `<select>`) unless a native
   equivalent does not exist.
3. Never own global state beyond `ToastProvider`.
4. Minimum moving parts — one dependency per concern.
