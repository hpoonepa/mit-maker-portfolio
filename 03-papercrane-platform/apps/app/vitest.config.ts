import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * Vitest config for the authenticated Paper Crane dashboard (apps/app).
 *
 * Environment
 * -----------
 * jsdom: React component + hook tests need a DOM. Node-only utility tests in
 * `lib/` still work under jsdom; we don't need a separate project.
 *
 * Include
 * -------
 * Co-located tests only. Anything matching `**\/*.test.ts(x)` is picked up, so
 * component tests live next to the component file and shared-lib tests next
 * to the source.
 *
 * Path resolver
 * -------------
 * `@/*` is the Next.js import alias configured in `tsconfig.json` (paths
 * entry). Vitest doesn't read tsconfig paths by default, so we mirror the
 * alias here. Keep both in sync if the alias root changes.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["**/*.test.ts", "**/*.test.tsx"],
    setupFiles: ["./tests/setup.ts"],
    globals: false,
    reporters: ["default"],
  },
  // Use the React 17+ automatic JSX runtime so client components don't need
  // an explicit `import React from 'react'`. Wave 9 surfaced this when newer
  // client components (Toast, DesignGrid) relied on the Next.js auto runtime
  // but vitest's default esbuild transform fell back to the classic runtime.
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
      // Stub Next.js' `server-only` shim: it's a build-time guard with no
      // runtime export, so importing it under vitest fails resolution.
      "server-only": path.resolve(__dirname, "./tests/stubs/server-only.ts"),
    },
  },
});
